# Neo4j 部署改进文档

## 概述

本文档总结了针对 Neo4j 生产环境部署的四大改进，旨在提升系统的**可维护性**、**性能**、**安全性**和**可观测性**。

---

## 1. APOC 插件配置

### 问题背景

Neo4j 的 APOC (Awesome Procedures On Cypher) 插件提供了高级图算法和实用工具，但非 Docker 部署时需要手动配置。

### 当前配置（Docker）

在 `docker-compose.yaml` 中已正确配置：

```yaml
services:
  neo4j:
    environment:
      NEO4J_PLUGINS: '["apoc", "graph-data-science"]'
      NEO4J_dbms_security_procedures_unrestricted: "apoc.*,gds.*"
      NEO4J_apoc_trigger_enabled: "true"
```

### 非 Docker 部署配置

**1. 下载 APOC 插件**

从 [APOC Releases](https://github.com/neo4j-contrib/neo4j-apoc-procedures/releases) 下载与 Neo4j 版本匹配的 JAR 文件（例如 `apoc-5.22.0-core.jar`）。

**2. 安装插件**

将 JAR 文件放入 Neo4j 插件目录：

```bash
# Linux/Mac
cp apoc-5.22.0-core.jar $NEO4J_HOME/plugins/

# Windows
copy apoc-5.22.0-core.jar %NEO4J_HOME%\plugins\
```

**3. 配置 neo4j.conf**

编辑 `$NEO4J_HOME/conf/neo4j.conf`，添加以下配置：

```properties
# 允许 APOC 和 GDS 过程不受限制执行
dbms.security.procedures.unrestricted=apoc.*,gds.*

# 启用 APOC 触发器（可选）
apoc.trigger.enabled=true
```

**4. 重启 Neo4j**

```bash
# Linux/Mac
$NEO4J_HOME/bin/neo4j restart

# Windows
%NEO4J_HOME%\bin\neo4j.bat restart
```

**5. 验证安装**

在 Neo4j 浏览器中执行：

```cypher
RETURN apoc.version() AS version;
```

如果返回版本号，则安装成功。

---

## 2. 索引预创建和动态开关

### 问题背景

- **问题**：应用启动时调用 `refresh_schema()` 导致启动缓慢（尤其在大规模图谱中）
- **风险**：频繁刷新 Schema 可能影响生产环境性能

### 解决方案

#### 生产环境：关闭自动刷新

在 `.env` 中配置：

```env
NEO4J_REFRESH_SCHEMA=false
```

#### 使用索引预创建脚本

**方式一：使用 Cypher 脚本**

运行 `scripts/init_indices.cypher`：

```bash
# 连接到 Neo4j 浏览器，执行脚本内容
# 或使用 cypher-shell
cat scripts/init_indices.cypher | cypher-shell -u neo4j -p 12345678
```

**方式二：使用 Python 工具**

```bash
# 查看使用帮助
python scripts/init_indices.py --help

# 使用默认配置创建索引
python scripts/init_indices.py

# 使用自定义连接参数
python scripts/init_indices.py \
  --uri neo4j://production-server:7687 \
  --user neo4j \
  --password production-password

# 仅检查现有索引（不创建）
python scripts/init_indices.py --check-only

# 删除所有索引（危险操作！需要二次确认）
python scripts/init_indices.py --drop-all
```

#### 索引清单

脚本会创建以下索引：

**唯一约束（自动创建索引）：**
- `__Chunk__.id` - UNIQUE
- `__Entity__.id` - UNIQUE
- `__Community__.id` - UNIQUE
- `__Document__.id` - UNIQUE

**向量索引（用于语义搜索）：**
- `chunk_embedding_index` - Chunk 向量索引（1536 维，cosine 相似度）
- `entity_embedding_index` - Entity 向量索引
- `community_summary_embedding_index` - Community 摘要向量索引

**属性索引（加速查询）：**
- `chunk_source_id_index` - Chunk 按 source_id 查询
- `entity_name_index` - Entity 按名称查询
- `entity_type_index` - Entity 按类型查询
- `community_level_index` - Community 按层级查询
- `community_size_index` - Community 按大小查询
- `document_path_index` - Document 按路径查询
- `document_extension_index` - Document 按扩展名查询

**全文索引（支持文本搜索）：**
- `chunk_text_index` - Chunk 文本全文检索
- `entity_description_index` - Entity 描述全文检索

#### 最佳实践

1. **开发环境**：保持 `NEO4J_REFRESH_SCHEMA=true`，自动同步 Schema
2. **测试环境**：首次部署后运行 `init_indices.py`，后续关闭自动刷新
3. **生产环境**：
   - 部署前运行 `init_indices.py --check-only` 检查索引
   - 设置 `NEO4J_REFRESH_SCHEMA=false`
   - 每次 Schema 变更后手动运行索引脚本
   - 定期使用 `--check-only` 验证索引状态

---

## 3. 资源调优

### 问题背景

`docker-compose.yaml` 中 Neo4j 内存设置硬编码为 2G，无法根据服务器规格灵活调整。

### 改进方案

#### 1. 环境变量化

修改 `docker-compose.yaml`：

```yaml
services:
  neo4j:
    environment:
      NEO4J_dbms_memory_heap_initial__size: "${NEO4J_HEAP_INITIAL_SIZE:-2G}"
      NEO4J_dbms_memory_heap_max__size: "${NEO4J_HEAP_MAX_SIZE:-2G}"
      NEO4J_dbms_memory_pagecache_size: "${NEO4J_PAGECACHE_SIZE:-1G}"
```

#### 2. 在 .env 中配置

添加到 `.env` 文件：

```env
# === Neo4j 内存配置（Docker 部署）===
# 堆内存初始大小（建议：服务器内存的 25%-50%）
NEO4J_HEAP_INITIAL_SIZE=2G

# 堆内存最大大小（建议：服务器内存的 25%-50%）
NEO4J_HEAP_MAX_SIZE=2G

# 页面缓存大小（建议：服务器内存的 50%，用于加速查询）
NEO4J_PAGECACHE_SIZE=1G
```

#### 3. 按服务器规格调优

| 服务器内存 | HEAP_INITIAL_SIZE | HEAP_MAX_SIZE | PAGECACHE_SIZE | 总计 |
|-----------|-------------------|---------------|----------------|-----|
| 4GB       | 1G                | 1G            | 1G             | 2G  |
| 8GB       | 2G                | 2G            | 2G             | 4G  |
| 16GB      | 4G                | 4G            | 6G             | 10G |
| 32GB      | 8G                | 8G            | 12G            | 20G |
| 64GB      | 16G               | 16G           | 24G            | 40G |

**调优原则**：
- **Heap（堆内存）**：用于图算法、事务处理
  - 推荐：服务器内存的 25%-50%
  - 过小：频繁 GC，性能下降
  - 过大：GC 停顿时间长
- **PageCache（页缓存）**：用于缓存图数据
  - 推荐：服务器内存的 50%
  - 越大越好（在不影响系统的情况下）
- **预留内存**：为操作系统和其他进程预留 20%-30% 内存

#### 4. 监控和调优

**查看当前配置**：

```bash
# 连接到 Neo4j
docker exec -it neo4j cypher-shell -u neo4j -p 12345678

# 查询配置
CALL dbms.listConfig() YIELD name, value
WHERE name CONTAINS 'memory'
RETURN name, value;
```

**监控内存使用**：

```cypher
// 查看 Page Cache 使用情况
CALL dbms.queryJmx('org.neo4j:*,name=Page cache')
YIELD name, attributes
RETURN name, attributes;

// 查看堆内存使用
CALL dbms.queryJmx('java.lang:type=Memory')
YIELD attributes
RETURN attributes.HeapMemoryUsage;
```

---

## 4. 其他综合改进

### 4.1 文件上传校验（安全性增强）

#### 问题背景

文件上传缺少校验，存在安全隐患：
- 恶意文件上传（病毒、木马）
- 文件类型伪造（修改扩展名绕过检查）
- 超大文件 DoS 攻击
- 路径遍历攻击

#### 解决方案

创建了 `server/routers/upload.py` 作为**文件上传校验的最佳实践参考**，包含：

**1. 文件名安全检查**

```python
# 防止路径遍历
DANGEROUS_PATTERNS = [r"\.\.", r"\/", r"\\", r"\x00", r"[<>:\"|?*]"]

def validate_filename(filename: str):
    # 长度检查
    if len(filename) > MAX_FILENAME_LENGTH:
        raise ValidationError(f"文件名过长（最大 {MAX_FILENAME_LENGTH} 字符）")

    # 危险模式检查
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, filename):
            raise ValidationError(f"文件名包含非法字符: {pattern}")
```

**2. 扩展名白名单**

```python
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".doc", ".docx", ".csv", ".json", ".yaml", ".yml"}

def validate_file_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(f"不支持的文件类型: {ext}")
    return ext
```

**3. MIME 类型验证（防止扩展名伪造）**

```python
MIME_TYPE_WHITELIST = {
    ".pdf": ["application/pdf"],
    ".txt": ["text/plain"],
    ".docx": ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
}

def validate_mime_type(content_type: str, extension: str):
    allowed_mimes = MIME_TYPE_WHITELIST.get(extension, [])
    if content_type not in allowed_mimes:
        raise ValidationError(f"MIME 类型不匹配: 期望 {allowed_mimes}，实际 {content_type}")
```

**4. 文件内容校验（魔术字节检查）**

```python
MAGIC_BYTES = {
    ".pdf": [b"%PDF"],
    ".docx": [b"PK\x03\x04"],  # ZIP 格式
}

async def validate_file_content(file: UploadFile, extension: str) -> bytes:
    content = await file.read()

    # 大小检查
    if len(content) > MAX_FILE_SIZE:
        raise ValidationError(f"文件过大（最大 {MAX_FILE_SIZE / 1024 / 1024:.1f}MB）")

    # 魔术字节检查
    magic_bytes = MAGIC_BYTES.get(extension)
    if magic_bytes:
        header = content[:100]
        if not any(header.startswith(magic) for magic in magic_bytes):
            raise ValidationError(f"文件内容与扩展名 {extension} 不匹配")

    return content
```

**5. 哈希计算（去重和完整性）**

```python
def compute_file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
```

**6. 病毒扫描占位（生产环境推荐）**

```python
# TODO: 生产环境集成 ClamAV
# scan_result = scan_file_with_clamav(content)
# if scan_result.is_infected:
#     raise ValidationError("文件包含恶意内容", virus=scan_result.virus_name)
```

#### API 使用示例

**单文件上传**：

```bash
curl -X POST "http://localhost:8000/api/v1/upload/file" \
  -F "file=@document.pdf" \
  -F "description=测试文档"
```

**批量上传**：

```bash
curl -X POST "http://localhost:8000/api/v1/upload/batch" \
  -F "files=@file1.pdf" \
  -F "files=@file2.txt"
```

**删除文件**：

```bash
curl -X DELETE "http://localhost:8000/api/v1/upload/document.pdf"
```

#### 如何应用到现有路由

参考 `upload.py` 中的校验函数，在其他需要文件上传的路由中复用：

```python
from server.routers.upload import (
    validate_filename,
    validate_file_extension,
    validate_mime_type,
    validate_file_content,
    compute_file_hash
)

@router.post("/your-upload-endpoint")
async def your_upload_handler(file: UploadFile = File(...)):
    # 1. 文件名校验
    validate_filename(file.filename)

    # 2. 扩展名校验
    extension = validate_file_extension(file.filename)

    # 3. MIME 类型校验
    validate_mime_type(file.content_type, extension)

    # 4. 文件内容校验
    content = await validate_file_content(file, extension)

    # 5. 计算哈希
    file_hash = compute_file_hash(content)

    # 6. 保存文件
    # ...
```

---

### 4.2 健康检查增强

#### 问题背景

原有 `/health` 接口仅检查 `RETURN 1`，无法全面反映系统健康状态。

#### 改进方案

增强 `server/routers/admin.py` 中的 `/health` 端点，新增以下检查：

**1. Neo4j 读取测试（带延迟测量）**

```python
start = time.time()
connection_manager.execute_query("RETURN 1 AS test")
latency_ms = (time.time() - start) * 1000

# 超过 100ms 标记为 degraded
if latency_ms > 100:
    status = "degraded"
```

**2. Neo4j 写入测试（创建并删除临时节点）**

```python
test_id = str(uuid.uuid4())

# 创建临时节点
create_query = "CREATE (n:__HealthCheck__ {id: $id}) RETURN n.id"
connection_manager.execute_query(create_query)

# 删除测试节点
delete_query = "MATCH (n:__HealthCheck__ {id: $id}) DELETE n"
connection_manager.execute_query(delete_query)

# 超过 200ms 标记为 degraded
if latency_ms > 200:
    status = "degraded"
```

**3. 连接池状态检查（需要 APOC）**

```cypher
CALL dbms.queryJmx('org.neo4j:*,name=Pool,*')
YIELD name, attributes
RETURN attributes.NumIdle AS idle, attributes.NumActive AS active
```

**4. 磁盘空间检查**

```python
import shutil
total, used, free = shutil.disk_usage("/")
free_gb = free / (1024 ** 3)

# 少于 1GB 标记为 unhealthy
# 少于 5GB 标记为 degraded
```

**5. 文件目录可写性检查**

```python
# 尝试创建临时文件
test_file = files_dir / f".health_check_{uuid.uuid4()}.tmp"
test_file.write_text("health check test")
test_file.unlink()
```

#### 响应格式

```json
{
  "status": "healthy",  // healthy | degraded | unhealthy
  "checks": {
    "neo4j_read": {
      "status": "healthy",
      "latency_ms": 12.34,
      "error": null
    },
    "neo4j_write": {
      "status": "healthy",
      "latency_ms": 45.67,
      "error": null
    },
    "neo4j_pool": {
      "status": "healthy",
      "active": 2,
      "idle": 8,
      "error": null
    },
    "disk_space": {
      "status": "healthy",
      "free_gb": 123.45,
      "error": null
    },
    "files_dir": {
      "status": "healthy",
      "writable": true,
      "error": null
    }
  },
  "timestamp": "2025-12-24T10:00:00.000Z"
}
```

#### 使用场景

**1. 监控告警集成**

```bash
# Prometheus 抓取
curl http://localhost:8000/api/v1/admin/health

# 告警规则：status != "healthy"
```

**2. 负载均衡健康检查**

```nginx
# Nginx upstream health check
upstream backend {
    server backend1:8000;
    check interval=3000 rise=2 fall=3 timeout=1000 type=http;
    check_http_send "GET /api/v1/admin/health HTTP/1.0\r\n\r\n";
    check_http_expect_alive http_2xx;
}
```

**3. Kubernetes 探针**

```yaml
livenessProbe:
  httpGet:
    path: /api/v1/admin/health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /api/v1/admin/health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
```

---

## 部署清单（Deployment Checklist）

### 开发环境

- [ ] 使用默认配置（2G heap, 1G pagecache）
- [ ] 保持 `NEO4J_REFRESH_SCHEMA=true`
- [ ] 可选：定期运行 `init_indices.py --check-only` 检查索引

### 测试环境

- [ ] 根据服务器规格调整 Neo4j 内存配置
- [ ] 首次部署后运行 `init_indices.py` 创建索引
- [ ] 设置 `NEO4J_REFRESH_SCHEMA=false`
- [ ] 配置健康检查监控（5 分钟间隔）

### 生产环境

- [ ] **内存调优**：
  - [ ] 根据服务器规格配置 `.env` 中的 Neo4j 内存参数
  - [ ] 预留 20%-30% 内存给操作系统
  - [ ] 监控 GC 日志，调整堆内存大小
- [ ] **索引管理**：
  - [ ] 部署前运行 `init_indices.py --check-only` 验证索引
  - [ ] 确认 `NEO4J_REFRESH_SCHEMA=false`
  - [ ] Schema 变更后手动运行索引脚本
- [ ] **文件上传安全**：
  - [ ] 参考 `upload.py` 实现文件校验
  - [ ] 配置文件大小限制（建议 100MB）
  - [ ] 可选：集成 ClamAV 病毒扫描
- [ ] **健康检查**：
  - [ ] 配置负载均衡健康检查（使用 `/health`）
  - [ ] 集成监控告警（Prometheus/Grafana）
  - [ ] 设置告警阈值（latency > 200ms, free_gb < 5）
- [ ] **APOC 插件**：
  - [ ] 验证 APOC 安装：`RETURN apoc.version()`
  - [ ] 确认权限配置：`dbms.security.procedures.unrestricted=apoc.*,gds.*`

---

## 常见问题（FAQ）

### Q1: 索引创建失败怎么办？

**A1**: 检查以下几点：
- Neo4j 版本是否支持向量索引（需要 5.11+）
- 向量维度配置是否正确（默认 1536）
- 是否有足够的磁盘空间
- 查看 Neo4j 日志：`docker logs neo4j` 或 `$NEO4J_HOME/logs/debug.log`

### Q2: 健康检查中连接池检查失败？

**A2**: 这是正常的，连接池检查需要 APOC 插件的 JMX 功能。如果 APOC 不可用，会标记为 `degraded`，不影响整体健康状态。

### Q3: 文件上传后立即查询为何找不到？

**A3**: 文件上传后需要运行构建任务：
- L0 快速索引（文本分块和向量化）
- L1 深度索引（实体抽取和图构建）

使用 `/admin/build/incremental` 触发构建。

### Q4: 如何调整 Neo4j 内存配置？

**A4**: 修改 `.env` 文件中的以下参数，然后重启 Docker Compose：

```env
NEO4J_HEAP_INITIAL_SIZE=4G
NEO4J_HEAP_MAX_SIZE=4G
NEO4J_PAGECACHE_SIZE=6G
```

```bash
docker compose down
docker compose up -d
```

### Q5: 生产环境是否需要关闭 refresh_schema？

**A5**: **强烈建议**。`refresh_schema()` 会遍历整个图谱，在大规模数据时（百万级节点）可能耗时数十秒甚至分钟，影响启动速度和用户体验。使用索引预创建脚本替代。

---

## 参考资源

### 官方文档

- [Neo4j 内存配置指南](https://neo4j.com/docs/operations-manual/current/performance/memory-configuration/)
- [APOC 用户手册](https://neo4j.com/labs/apoc/5/)
- [Neo4j 向量索引](https://neo4j.com/docs/cypher-manual/current/indexes-for-vector-search/)

### 项目文档

- `API_IMPROVEMENTS.md` - API 架构改进
- `LOGGING_AND_EXCEPTION_IMPROVEMENTS.md` - 日志和异常处理改进
- `TASK_QUEUE_AND_PROGRESS_IMPROVEMENTS.md` - 任务队列改进

### 脚本工具

- `scripts/init_indices.cypher` - Cypher 索引创建脚本
- `scripts/init_indices.py` - Python 索引管理工具
- `server/routers/upload.py` - 文件上传校验参考实现
- `server/routers/admin.py` - 健康检查端点（`/health`）

---

## 变更记录

| 日期       | 版本  | 变更内容                                      |
|-----------|-------|-----------------------------------------------|
| 2025-12-24| 1.0.0 | 初始版本，包含四大改进：APOC、索引、资源调优、综合改进 |

---

**作者**: GraphRAG Team
**最后更新**: 2025-12-24
