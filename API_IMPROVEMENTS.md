# API 改进文档

## 📋 概述

本文档记录了对 GraphRAG 系统进行的三项关键改进：

1. **统一 JSON 返回格式** - 移除旧的字符串格式，统一使用结构化 JSON
2. **错误码和消息规范** - 细化业务错误码，提供更精确的错误信息
3. **API 版本控制** - 添加版本前缀，支持平滑迁移

---

## 1️⃣ 统一 JSON 返回格式

### 问题背景

**上游数据不纯：**
- `entity_extractor.py` 中存在 `_build_compatible_result` 方法，生成旧的字符串格式
- 缓存中混杂字符串格式和 JSON 格式
- `_load_from_cache` 被迫处理多种格式

**下游逻辑污染：**
- `build_graph.py:294-308` 存在大量兼容性分支判断：
  ```python
  if isinstance(res, dict):
      # 新格式
  elif isinstance(res, (tuple, list)):
      # 老格式兼容
  elif isinstance(res, str):
      # 原始字符串兼容
  ```

### 解决方案

#### 1.1 定义标准响应模型

**位置：** `server/models/schemas.py`

```python
class ExtractionResult(BaseModel):
    """实体抽取结果模型（标准化JSON格式）"""
    entities: List[EntityItem] = []
    relations: List[RelationItem] = []
    chunk_id: Optional[str] = None
    file_name: Optional[str] = None
    processing_time: Optional[float] = None
    error: Optional[str] = None
```

#### 1.2 标记旧方法为 Deprecated

**位置：** `graphrag_agent/graph/extraction/entity_extractor.py:801`

```python
def _build_compatible_result(self, entities, relations) -> str:
    """
    ⚠️ DEPRECATED: 此方法将在 v2.0 中移除

    新代码应直接使用字典格式（ExtractionResult）
    """
    import warnings
    warnings.warn(
        "_build_compatible_result is deprecated...",
        DeprecationWarning
    )
    # ... 旧实现保留用于兼容性
```

#### 1.3 添加运行时警告

**位置：** `graphrag_agent/integrations/build/build_graph.py:310-328`

系统会自动检测旧格式并给出警告：

```
⚠️  检测到 3 个文件使用旧的实体抽取格式
   建议运行: python scripts/migrate_extraction_cache.py
   v2.0 将移除对旧格式的支持
```

#### 1.4 缓存迁移脚本

**位置：** `scripts/migrate_extraction_cache.py`

**用途：**
- 遍历所有缓存文件（session cache + global cache）
- 检测旧格式（字符串 / 元组）
- 转换为新格式（ExtractionResult JSON）
- 重新保存

**使用方法：**

```bash
# 检测但不修改（Dry run）
python scripts/migrate_extraction_cache.py --dry-run

# 迁移并备份
python scripts/migrate_extraction_cache.py --backup

# 正式迁移
python scripts/migrate_extraction_cache.py
```

**输出示例：**

```
================================================================================
迁移完成统计
================================================================================
总文件数: 142
✅ 迁移成功: 38
✓  已是新格式: 94
➖ 跳过: 7
❌ 失败: 3
================================================================================
```

### 迁移路径

#### Phase 1: 兼容期（当前版本 v1.x）
- ✅ 保留 `_build_compatible_result`（标记为 Deprecated）
- ✅ `build_graph.py` 支持旧格式但给出警告
- ✅ 缓存迁移脚本可用

#### Phase 2: 过渡期（v1.5）
- 强制警告：旧格式导致构建失败
- 文档标注：旧格式 API 不再推荐

#### Phase 3: 断舍离（v2.0）
- 完全移除 `_build_compatible_result`
- 移除 `build_graph.py` 中的兼容分支
- 仅支持 `ExtractionResult` JSON 格式

---

## 2️⃣ 错误码和消息规范

### 问题背景

**错误吞没：**
- `entity_extractor.py` 异常处理静默失败：
  ```python
  except Exception as e:
      print(f'Chunk {idx} 处理异常: {e}')
      llm_results[idx] = {"entities": [], ...}  # 无法区分"无实体"还是"LLM挂了"
  ```

**API 错误泛化：**
- 所有错误都是 `HTTPException(500, detail=str(e))`
- 前端无法区分 "Token 不足" vs "数据库连接失败"

### 解决方案

#### 2.1 定义业务错误码

**位置：** `server/models/schemas.py`

```python
class ErrorCode:
    """
    业务错误码定义

    分类规则：
    - 2xx: 成功类
    - 4xx: 客户端错误
    - 5xxx: 服务端错误
        - 50xx: 通用错误
        - 51xx: LLM相关错误
        - 52xx: 数据库相关错误
        - 53xx: 缓存相关错误
        - 54xx: 文件系统相关错误
        - 55xx: 实体抽取相关错误
    """
    SUCCESS = 200
    EMPTY_RESULT = 204

    PARAM_ERROR = 400
    UNAUTHORIZED = 401
    NOT_FOUND = 404

    SERVER_ERROR = 500

    LLM_ERROR = 5101
    LLM_TIMEOUT = 5102
    LLM_TOKEN_LIMIT = 5103
    LLM_PARSE_ERROR = 5104

    DB_ERROR = 5201
    DB_CONNECTION_ERROR = 5202
    DB_QUERY_ERROR = 5203

    EXTRACTION_ERROR = 5501
    EXTRACTION_TIMEOUT = 5502
    EXTRACTION_EMPTY = 5503
```

#### 2.2 统一响应结构

```python
class BaseResponse(BaseModel, Generic[T]):
    """统一响应结构"""
    code: int = 200
    msg: str = "success"
    data: Optional[T] = None
```

**使用示例：**

```python
# 成功响应
return BaseResponse[Dict](
    code=ErrorCode.SUCCESS,
    msg="查询成功",
    data={"entities": [...]}
)

# 错误响应
return BaseResponse[None](
    code=ErrorCode.LLM_TIMEOUT,
    msg="LLM 请求超时，请稍后重试",
    data=None
)
```

#### 2.3 全局异常处理

**位置：** `server/main.py:34-80`

```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    全局异常处理器

    根据异常类型返回不同的错误码：
    - ConnectionError/TimeoutError → DB_CONNECTION_ERROR
    - ValueError/KeyError → PARAM_ERROR
    - 其他 → SERVER_ERROR
    """
    error_msg = str(exc)
    error_code = ErrorCode.SERVER_ERROR

    # 根据异常类型分类
    if isinstance(exc, (ConnectionError, TimeoutError)):
        error_code = ErrorCode.DB_CONNECTION_ERROR
    elif "LLM" in error_msg:
        error_code = ErrorCode.LLM_ERROR
    elif "database" in error_msg.lower():
        error_code = ErrorCode.DB_ERROR

    logger.error(f"全局异常捕获: {error_msg}\n{traceback.format_exc()}")

    return JSONResponse(
        status_code=500,
        content=BaseResponse(
            code=error_code,
            msg=error_msg,
            data=None
        ).dict()
    )
```

### 前端错误处理示例

```typescript
// 旧方式 - 无法区分错误类型
try {
    const response = await fetch('/api/chat');
    const data = await response.json();
} catch (error) {
    alert('请求失败'); // 所有错误一视同仁
}

// 新方式 - 精确错误处理
try {
    const response = await fetch('/api/v1/chat');
    const result = await response.json();

    if (result.code === 200) {
        // 成功
        displayData(result.data);
    } else if (result.code === 5103) {
        // LLM Token 超限
        alert('问题过长，请缩短后重试');
    } else if (result.code === 5202) {
        // 数据库连接失败
        alert('系统维护中，请稍后重试');
    } else {
        // 其他错误
        alert(`错误: ${result.msg}`);
    }
} catch (error) {
    alert('网络错误');
}
```

---

## 3️⃣ API 版本控制

### 问题背景

- `server/main.py:20` - 没有版本前缀
- 路由直接挂载：`app.include_router(api_router)`
- API 路径：`/graph/overview` （无版本号）
- **风险**：修改返回结构后，旧客户端立即崩溃

### 解决方案

#### 3.1 添加版本前缀

**位置：** `server/main.py:86`

```python
# 旧方式
app.include_router(api_router)

# 新方式（带版本前缀）
app.include_router(api_router, prefix="/api/v1")
```

#### 3.2 API 路径变更

| 旧路径 | 新路径 | 状态 |
|--------|--------|------|
| `/graph/overview` | `/api/v1/graph/overview` | ✅ 新推荐 |
| `/chat` | `/api/v1/chat` | ✅ 新推荐 |
| `/source/chunk` | `/api/v1/source/chunk` | ✅ 新推荐 |

#### 3.3 平滑迁移策略

**方案 A: Nginx 重定向（推荐）**

```nginx
# 旧路径自动重定向到新路径
location /graph/ {
    rewrite ^/graph/(.*)$ /api/v1/graph/$1 permanent;
}

location /chat {
    rewrite ^/chat$ /api/v1/chat permanent;
}
```

**方案 B: FastAPI 双路由（兼容期）**

```python
# 保留旧路由（标记为 Deprecated）
app.include_router(api_router)  # 旧路由：/graph/overview

# 添加新路由
app.include_router(api_router, prefix="/api/v1")  # 新路由：/api/v1/graph/overview

# 添加警告响应头
@app.middleware("http")
async def add_deprecation_header(request: Request, call_next):
    if not request.url.path.startswith("/api/v1"):
        response = await call_next(request)
        response.headers["X-API-Deprecated"] = "true"
        response.headers["X-API-New-Path"] = f"/api/v1{request.url.path}"
        return response
    return await call_next(request)
```

**方案 C: 断舍离（v2.0）**

完全移除旧路由，仅保留 `/api/v1/*`。

---

## 📊 改进总结

| 改进项 | 问题 | 解决方案 | 文件 | 状态 |
|--------|------|---------|------|------|
| **JSON 格式** | 旧字符串格式混杂 | ExtractionResult 模型 | `schemas.py` | ✅ 已实现 |
| **缓存迁移** | 缓存格式不一致 | 迁移脚本 | `scripts/migrate_extraction_cache.py` | ✅ 已实现 |
| **Deprecated 警告** | 无废弃提示 | DeprecationWarning | `entity_extractor.py` | ✅ 已实现 |
| **运行时警告** | 无旧格式提示 | build_graph 检测 | `build_graph.py` | ✅ 已实现 |
| **错误码** | 错误信息泛化 | ErrorCode 类 | `schemas.py` | ✅ 已实现 |
| **统一响应** | 返回格式不一致 | BaseResponse | `schemas.py` | ✅ 已实现 |
| **全局异常处理** | 异常处理分散 | 全局 handler | `main.py` | ✅ 已实现 |
| **API 版本** | 无版本控制 | /api/v1 前缀 | `main.py` | ✅ 已实现 |

---

## 🚀 使用指南

### 对于开发者

#### 1. 实体抽取（推荐新格式）

```python
from server.models.schemas import ExtractionResult, EntityItem, RelationItem

# ✅ 推荐：使用 ExtractionResult
result = ExtractionResult(
    entities=[
        EntityItem(name="学生", type="学生类型", description="在校学生")
    ],
    relations=[
        RelationItem(source="学生", target="奖学金", type="申请", weight=0.8)
    ],
    chunk_id="chunk_123",
    processing_time=0.5
)

# ❌ 不推荐：旧的字符串格式（将在 v2.0 移除）
old_result = '("entity"<|>学生<|>学生类型<|>在校学生)<record>'
```

#### 2. API 错误处理

```python
from server.models.schemas import BaseResponse, ErrorCode
from fastapi import HTTPException

# ✅ 推荐：使用细化的错误码
if not entity_found:
    return BaseResponse[None](
        code=ErrorCode.NOT_FOUND,
        msg="实体不存在",
        data=None
    )

# ❌ 不推荐：泛化的 500 错误
raise HTTPException(status_code=500, detail="查询失败")
```

#### 3. API 调用（使用新路径）

```bash
# ✅ 推荐：v1 API
curl http://localhost:8000/api/v1/graph/overview

# ❌ 不推荐：旧 API（兼容期可用，v2.0 移除）
curl http://localhost:8000/graph/overview
```

### 对于运维人员

#### 1. 缓存迁移

```bash
# 在升级到 v2.0 前，运行迁移脚本
cd /path/to/graph-rag-agent
python scripts/migrate_extraction_cache.py --backup
```

#### 2. Nginx 配置更新

```nginx
# 添加版本前缀重定向
location /graph/ {
    rewrite ^/graph/(.*)$ /api/v1/graph/$1 permanent;
}
```

#### 3. 前端代码更新

```javascript
// 更新 API_URL
const API_URL = "http://localhost:8000/api/v1";

// 更新错误处理
if (response.code === 5202) {
    showAlert("数据库连接失败，请联系管理员");
}
```

---

## 🔄 版本时间表

| 版本 | 时间 | 变更 |
|------|------|------|
| **v1.0** | 当前 | ✅ 新格式支持<br>✅ 旧格式兼容<br>✅ Deprecated 警告 |
| **v1.5** | 下一版本 | ⚠️ 旧格式强制警告<br>⚠️ 构建失败提示 |
| **v2.0** | 计划中 | ❌ 移除旧格式支持<br>❌ 移除 `_build_compatible_result`<br>❌ 移除旧 API 路径 |

---

## 📖 相关文档

- [统一响应格式规范](server/models/schemas.py)
- [缓存迁移脚本使用指南](scripts/migrate_extraction_cache.py)
- [全局异常处理逻辑](server/main.py)
- [实体抽取 Deprecated 标记](graphrag_agent/graph/extraction/entity_extractor.py)

---

## 🤝 贡献

如果发现错误码定义不足，请：
1. 在 `server/models/schemas.py` 中添加新错误码
2. 更新本文档的错误码表
3. 提交 PR

---

**最后更新：** 2025-12-23
**版本：** v1.0
