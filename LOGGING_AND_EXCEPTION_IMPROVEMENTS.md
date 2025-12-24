# 日志结构化与统一异常处理改进文档

## 📋 概述

本文档记录了对 GraphRAG 系统进行的两项代码质量改进：

1. **日志结构化 (Structured Logging)** - 替代 print()，提供统一的结构化日志系统
2. **统一异常处理 (Unified Exception Handling)** - 消除重复的 try-except，统一错误处理逻辑

---

## 1️⃣ 日志结构化 (Structured Logging)

### 问题背景

**Print 满天飞：**
- ✅ **604 个 `print()` 调用** 分布在 76 个文件中
- ✅ **363 个 `console.print()` 调用** 分布在 15 个文件中
- ❌ 没有统一的日志系统
- ❌ 缺乏上下文信息（request_id, user_id, timestamp）
- ❌ 生产环境无法被 ELK 等日志系统采集
- ❌ 调试困难，无法追踪请求链路

**示例（旧代码）：**
```python
# ❌ 旧方式 - 无结构化，无上下文
print(f"🔥 处理文件: {filename}")
print(f"Chunk {idx} 处理异常: {e}")
self.console.print(f"[yellow]警告: 文件 {filename} 返回格式异常[/yellow]")
```

### 解决方案

#### 1.1 结构化日志工具

**位置：** `server/utils/logger.py`

**核心功能：**
- **JSONFormatter** - JSON 格式输出，便于机器解析和 ELK 采集
- **ColoredConsoleFormatter** - 彩色控制台输出，提升开发体验
- **StructuredLogger** - 支持上下文信息（request_id, user_id 等）
- **日志轮转** - 自动分割日志文件，避免过大
- **分级日志** - app.log（全部）+ error.log（仅错误）

**配置（server/main.py）：**
```python
from utils.logger import setup_logging, get_logger

# 配置日志系统
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
setup_logging(
    log_level="DEBUG" if DEBUG else "INFO",
    log_dir=Path("logs") if not DEBUG else None,  # 开发环境不写文件
    use_json=not DEBUG  # 生产环境使用 JSON 格式
)

# 获取日志器
logger = get_logger(__name__)
```

#### 1.2 使用方法

**基础使用：**
```python
from utils.logger import get_logger

logger = get_logger(__name__)

# ✅ 推荐：结构化日志
logger.info("用户登录成功", user_id="123", ip="192.168.1.1")
logger.error("数据库连接失败", exc_info=True, db_host="localhost")
logger.warning("缓存未命中", cache_key="entity_123")
logger.debug("实体类型过滤", allowed_types=["学生", "奖学金"], count=10)
```

**添加上下文信息：**
```python
# 方式 1: 手动设置
logger.set_context(request_id="abc123", user_id="user_456")
logger.info("处理请求")  # 自动包含 request_id 和 user_id
logger.clear_context()

# 方式 2: 使用上下文管理器
from utils.logger import LogContext

with LogContext(request_id="abc123", session_id="sess_789"):
    logger.info("开始处理")  # 自动添加 request_id 和 session_id
    # ... 处理逻辑 ...
    logger.info("处理完成")  # 自动添加 request_id 和 session_id
```

**记录异常：**
```python
try:
    risky_operation()
except Exception as e:
    logger.error("操作失败", exc_info=True, operation="risky_operation")
    # exc_info=True 会自动记录完整的堆栈追踪
```

#### 1.3 日志格式示例

**开发环境（彩色文本）：**
```
2025-12-23 14:30:15 | INFO     | server.main                    | 知识图谱问答系统启动 | version=1.0.0 | debug=True
2025-12-23 14:30:16 | DEBUG    | graphrag_agent.graph.extraction.entity_extractor | 实体类型过滤白名单 | allowed_types=['学生类型', '奖学金类型'] | raw_entity_count=15
2025-12-23 14:30:20 | WARNING  | server.routers.graph           | 业务异常: 实体不存在 | code=404 | entity_id=entity_123
2025-12-23 14:30:25 | ERROR    | server.main                    | 系统异常捕获: connection timeout | path=/api/v1/graph/overview | method=GET
```

**生产环境（JSON格式）：**
```json
{
  "timestamp": "2025-12-23T14:30:15.123Z",
  "level": "INFO",
  "logger": "server.main",
  "message": "知识图谱问答系统启动",
  "version": "1.0.0",
  "debug": false,
  "module": "main",
  "function": "startup_event",
  "line": 151
}
{
  "timestamp": "2025-12-23T14:30:25.456Z",
  "level": "ERROR",
  "logger": "server.main",
  "message": "系统异常捕获: connection timeout",
  "path": "/api/v1/graph/overview",
  "method": "GET",
  "exception": {
    "type": "TimeoutError",
    "message": "connection timeout",
    "traceback": "Traceback (most recent call last):\n  File ..."
  }
}
```

#### 1.4 迁移指南

**步骤 1: 导入日志器**
```python
# ❌ 旧代码
print(f"处理文件: {filename}")

# ✅ 新代码
from utils.logger import get_logger
logger = get_logger(__name__)

logger.info("处理文件", filename=filename)
```

**步骤 2: 替换 print() 调用**

| 旧代码（print） | 新代码（logger） | 日志级别 |
|----------------|-----------------|----------|
| `print(f"🔍 DEBUG: {info}")` | `logger.debug("Debug信息", info=info)` | DEBUG |
| `print(f"处理文件: {f}")` | `logger.info("处理文件", filename=f)` | INFO |
| `print(f"⚠️ 警告: {msg}")` | `logger.warning("警告", message=msg)` | WARNING |
| `print(f"❌ 错误: {e}")` | `logger.error("错误", exc_info=True)` | ERROR |

**步骤 3: 替换 console.print() 调用**
```python
# ❌ 旧代码
from rich.console import Console
console = Console()
console.print(f"[yellow]警告: 文件 {filename} 格式异常[/yellow]")

# ✅ 新代码
logger.warning("文件格式异常", filename=filename)
```

**步骤 4: 添加上下文信息**
```python
# 在 API endpoint 中添加 request_id
@router.get("/overview")
async def get_overview(request: Request):
    request_id = str(uuid.uuid4())
    logger.set_context(request_id=request_id)

    logger.info("获取图谱概览")
    # ... 处理逻辑 ...

    logger.clear_context()
```

#### 1.5 环境变量配置

**开发环境（`.env`）：**
```env
DEBUG=true
```
- 彩色控制台输出
- 不写日志文件
- 显示 DEBUG 级别日志

**生产环境（`.env`）：**
```env
DEBUG=false
```
- JSON 格式输出
- 写入 `logs/app.log` 和 `logs/error.log`
- 仅显示 INFO 及以上级别日志
- 日志文件自动轮转（100 MB / 文件，保留 5 个备份）

---

## 2️⃣ 统一异常处理 (Unified Exception Handling)

### 问题背景

**代码重复：**
```python
# ❌ 每个 endpoint 都重复相同的 try-except
@router.get("/overview")
async def get_overview():
    try:
        result = get_data()
        return result
    except Exception as e:
        print(f"错误: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/subgraph")
async def get_subgraph():
    try:
        result = get_data()
        return result
    except Exception as e:
        print(f"错误: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
```

**Main 入口裸奔：**
- ❌ 没有全局异常处理器
- ❌ 异常处理分散在各个 router 中
- ❌ 错误消息不统一
- ❌ 无法区分业务异常和系统异常

### 解决方案

#### 2.1 自定义异常类

**位置：** `server/utils/exceptions.py`

**核心异常类：**

```python
from utils.exceptions import (
    BusinessException,        # 业务异常基类
    ValidationError,          # 参数验证错误 (400)
    ResourceNotFoundError,    # 资源未找到 (404)
    LLMTimeoutError,         # LLM 超时 (5102)
    DatabaseError,           # 数据库错误 (5201)
    ExtractionError          # 实体抽取错误 (5501)
)
```

**使用示例：**
```python
# ✅ 推荐：抛出具体的业务异常
if not entity:
    raise ResourceNotFoundError(f"实体 {entity_id} 不存在", entity_id=entity_id)

if len(text) > MAX_LENGTH:
    raise LLMTokenLimitError(f"文本过长（{len(text)} > {MAX_LENGTH}）", length=len(text))

if not db.is_connected():
    raise DatabaseConnectionError("Neo4j 连接失败", host="localhost", port=7687)
```

#### 2.2 全局异常处理器

**位置：** `server/main.py:44-135`

**三层异常处理：**

1. **BusinessException 处理器** - 处理预期的业务异常
2. **HTTPException 处理器** - 处理 FastAPI 的 HTTP 异常
3. **Exception 处理器** - 兜底处理所有未捕获的系统异常

**代码示例（server/main.py）：**
```python
@app.exception_handler(BusinessException)
async def business_exception_handler(request: Request, exc: BusinessException):
    """业务异常返回 200，通过 code 字段区分错误类型"""
    logger.warning(f"业务异常: {exc.message}", code=exc.code, path=request.url.path)

    return JSONResponse(
        status_code=200,  # 业务异常返回 200
        content=BaseResponse(
            code=exc.code,
            msg=exc.message,
            data=exc.details
        ).dict()
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """系统异常返回 500，DEBUG 模式显示详细信息"""
    logger.error(f"系统异常: {str(exc)}", exc_info=True, path=request.url.path)

    # DEBUG 模式显示详细错误，生产环境隐藏
    if DEBUG:
        response_msg = str(exc)
        response_data = {"traceback": traceback.format_exc()}
    else:
        response_msg = "服务器内部错误，请联系管理员"
        response_data = None

    return JSONResponse(
        status_code=500,
        content=BaseResponse(
            code=ErrorCode.SERVER_ERROR,
            msg=response_msg,
            data=response_data
        ).dict()
    )
```

#### 2.3 Router 层简化

**旧代码（重复的 try-except）：**
```python
@router.get("/overview")
async def get_overview():
    try:
        result = get_knowledge_graph()

        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])

        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        print(f"获取图谱概览失败: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取图谱概览失败: {str(e)}")
```

**新代码（简洁，全局异常处理器自动捕获）：**
```python
from utils.exceptions import DatabaseError
from utils.logger import get_logger

logger = get_logger(__name__)

@router.get("/overview")
async def get_overview():
    # 移除 try-except，全局异常处理器会自动捕获
    logger.info("获取图谱概览")

    result = get_knowledge_graph()

    if "error" in result:
        # 使用 DatabaseError 抛出业务异常
        raise DatabaseError(result["error"])

    return {"status": "success", "data": result}
```

**代码对比：**
- ❌ 旧代码：18 行（包含重复的异常处理）
- ✅ 新代码：10 行（移除 try-except，使用全局异常处理器）

**减少代码量：44%**

#### 2.4 错误响应示例

**业务异常（404）：**
```json
// 请求: GET /api/v1/graph/entity/nonexistent_id
// HTTP 状态码: 200（业务异常返回 200）
{
  "code": 404,
  "msg": "实体 nonexistent_id 不存在",
  "data": {
    "entity_id": "nonexistent_id"
  }
}
```

**系统异常（开发环境）：**
```json
// 请求: GET /api/v1/graph/overview
// HTTP 状态码: 500
{
  "code": 5202,
  "msg": "connection timeout",
  "data": {
    "traceback": "Traceback (most recent call last):\n  File ..."
  }
}
```

**系统异常（生产环境）：**
```json
// 请求: GET /api/v1/graph/overview
// HTTP 状态码: 500
{
  "code": 5202,
  "msg": "服务器内部错误，请联系管理员",
  "data": null
}
```

#### 2.5 迁移指南

**步骤 1: 移除 router 层的 try-except**
```python
# ❌ 旧代码
@router.get("/path")
async def get_path():
    try:
        result = find_path()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ✅ 新代码
@router.get("/path")
async def get_path():
    result = find_path()
    return result  # 异常会被全局处理器捕获
```

**步骤 2: 使用具体的业务异常**
```python
# ❌ 旧代码
if not entity:
    raise HTTPException(status_code=404, detail="实体不存在")

# ✅ 新代码
from utils.exceptions import ResourceNotFoundError

if not entity:
    raise ResourceNotFoundError(f"实体 {entity_id} 不存在", entity_id=entity_id)
```

**步骤 3: 添加日志记录**
```python
from utils.logger import get_logger

logger = get_logger(__name__)

@router.get("/community")
async def get_community(entity_id: str):
    logger.info("查询实体社区", entity_id=entity_id)

    community = find_community(entity_id)

    if not community:
        raise ResourceNotFoundError(f"实体 {entity_id} 无社区信息")

    return {"status": "success", "data": community}
```

**步骤 4: 保留特定的恢复逻辑**
```python
# 注意：仅在需要特定恢复逻辑时才使用 try-except
@router.post("/extract")
async def extract_entities(text: str):
    try:
        entities = llm_extract(text)
        return entities
    except LLMTimeoutError:
        # 特定的恢复逻辑：超时时返回缓存结果
        logger.warning("LLM超时，返回缓存结果")
        return get_cached_entities(text)
    # 其他异常会被全局处理器捕获
```

---

## 📊 改进总结

| 改进项 | 问题 | 解决方案 | 文件 | 状态 |
|--------|------|---------|------|------|
| **结构化日志** | 604 个 print() 调用 | JSONFormatter + StructuredLogger | `utils/logger.py` | ✅ 已实现 |
| **日志配置** | 无统一日志系统 | setup_logging() | `server/main.py` | ✅ 已实现 |
| **业务异常** | 缺乏异常分类 | BusinessException 体系 | `utils/exceptions.py` | ✅ 已实现 |
| **全局异常处理** | 异常处理分散 | 三层异常处理器 | `server/main.py` | ✅ 已实现 |
| **DEBUG 模式** | 无环境区分 | DEBUG 环境变量 | `server/main.py` | ✅ 已实现 |
| **示例迁移** | - | entity_extractor.py | `graphrag_agent/graph/extraction/` | ✅ 已实现 |
| **示例迁移** | - | graph.py | `server/routers/` | ✅ 已实现 |

---

## 🚀 使用指南

### 对于开发者

#### 1. 日志记录

```python
from utils.logger import get_logger

logger = get_logger(__name__)

# ✅ 推荐：结构化日志
logger.info("处理文件", filename="test.pdf", size=1024)
logger.debug("实体过滤", allowed_types=["学生", "奖学金"], filtered_count=5)
logger.warning("缓存未命中", cache_key="entity_123")
logger.error("LLM调用失败", exc_info=True, model="gpt-4")

# ❌ 不推荐：print()
print(f"处理文件: test.pdf, 大小: 1024")
```

#### 2. 异常处理

```python
from utils.exceptions import ResourceNotFoundError, ValidationError

# ✅ 推荐：抛出具体的业务异常
if not entity:
    raise ResourceNotFoundError(f"实体 {entity_id} 不存在")

if len(text) > 10000:
    raise ValidationError("文本过长", max_length=10000, actual_length=len(text))

# ❌ 不推荐：泛化的 HTTPException
raise HTTPException(status_code=500, detail="查询失败")
```

#### 3. Router 开发

```python
from fastapi import APIRouter
from utils.logger import get_logger
from utils.exceptions import ResourceNotFoundError

logger = get_logger(__name__)
router = APIRouter()

@router.get("/entity/{entity_id}")
async def get_entity(entity_id: str):
    # 添加日志
    logger.info("查询实体", entity_id=entity_id)

    # 直接调用，不需要 try-except
    entity = find_entity(entity_id)

    # 抛出业务异常（全局处理器会捕获）
    if not entity:
        raise ResourceNotFoundError(f"实体 {entity_id} 不存在")

    return entity
```

### 对于运维人员

#### 1. 环境配置

**开发环境：**
```bash
export DEBUG=true
python server/main.py
```

**生产环境：**
```bash
export DEBUG=false
python server/main.py
```

#### 2. 日志查看

**开发环境（控制台）：**
```bash
# 彩色输出，直接查看
tail -f /dev/stdout
```

**生产环境（文件）：**
```bash
# 查看全部日志
tail -f logs/app.log | jq .

# 仅查看错误日志
tail -f logs/error.log | jq .

# 过滤特定字段
cat logs/app.log | jq 'select(.request_id == "abc123")'
```

#### 3. ELK 集成

**Filebeat 配置（filebeat.yml）：**
```yaml
filebeat.inputs:
- type: log
  enabled: true
  paths:
    - /path/to/graph-rag-agent/logs/app.log
  json.keys_under_root: true
  json.add_error_key: true

output.elasticsearch:
  hosts: ["localhost:9200"]
  index: "graphrag-%{+yyyy.MM.dd}"
```

---

## 📖 相关文档

- [结构化日志工具](server/utils/logger.py)
- [自定义异常类](server/utils/exceptions.py)
- [全局异常处理](server/main.py)
- [API 错误码规范](server/models/schemas.py)

---

## 🔄 迁移时间表

| 阶段 | 时间 | 任务 | 负责人 |
|------|------|------|--------|
| **阶段 1** | 当前 | ✅ 创建工具和文档<br>✅ 示例迁移 | 已完成 |
| **阶段 2** | 下一迭代 | 🔄 迁移核心模块（extraction, indexing）<br>🔄 迁移 build 相关脚本 | 待分配 |
| **阶段 3** | 计划中 | 🔜 迁移所有 routers<br>🔜 迁移 agents | 待分配 |
| **阶段 4** | 后续 | 📊 ELK 集成<br>📊 日志监控告警 | 待分配 |

---

## 🤝 贡献

如果发现新的异常类型需要添加，请：
1. 在 `server/utils/exceptions.py` 中添加新异常类
2. 在 `server/models/schemas.py` 中添加对应错误码
3. 更新本文档的异常类列表
4. 提交 PR

---

**最后更新：** 2025-12-23
**版本：** v1.0
