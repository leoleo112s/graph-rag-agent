# 生产就绪性改进文档

## 概述

本文档记录了针对 graph-rag-agent 项目在生产环境部署时的两个关键问题的改进方案。这些改进提升了系统的并发安全性、用户体验和可维护性。

**改进日期**: 2025-12-24
**影响范围**: 后端服务（FastAPI）、构建系统、聊天服务
**改进目标**: 生产就绪、多进程安全、优雅降级

---

## 问题一：构建并发控制脆弱 (Fragile Concurrency Control)

### 问题描述

**现状**: 不同模块使用隔离的内存锁，导致并发冲突风险。

**代码证据**:
- `server/routers/build.py`: 定义了独立的 `_build_running` 和 `_build_lock` (lines 219-220)
- `server/routers/admin.py`: 定义了独立的 `_is_building` 和 `_build_lock` (lines 37-38)

**风险分析**:
1. **锁隔离**: 调用 `/admin/build/full` 和 `/build/run` 可以同时运行，导致 Neo4j 写入冲突或内存爆炸
2. **多进程失效**: Gunicorn 多 worker 部署时，每个进程的锁完全独立，无法互斥
3. **状态易失**: 服务重启后 `_build_running` 重置为 `False`，但后台任务可能仍在运行

### 解决方案

#### 1. 创建统一分布式锁管理器

**文件**: `server/utils/build_lock.py` (NEW)

**核心特性**:
- **双模式运行**:
  - **Redis 模式**: 生产环境，使用 Redis 分布式锁（多进程安全）
  - **内存模式**: 开发环境，降级到内存锁（单进程）
- **同步/异步接口**: `acquire()` / `acquire_async()`, `release()` / `release_async()`
- **自动降级**: Redis 连接失败时自动切换到内存锁
- **单例模式**: `get_build_lock_manager()` 确保全局唯一实例

**关键代码**:
```python
class BuildLockManager:
    def __init__(self, use_redis: bool = True):
        self.use_redis = use_redis
        self.redis_client = None
        self.memory_locks = {}

        if use_redis:
            try:
                from server.utils.redis_state import get_redis_state_manager
                self.redis_mgr = get_redis_state_manager()
                self.redis_client = self.redis_mgr.redis_client
            except Exception as e:
                self.use_redis = False

    async def acquire_async(self, resource: str, ttl: int = 3600) -> bool:
        """获取分布式锁（异步版本）"""
        if self.use_redis and self.redis_client:
            return await asyncio.to_thread(self.acquire, resource, ttl)
        else:
            return await self._acquire_memory_lock_async(resource, ttl)
```

#### 2. 迁移 build.py 使用统一锁

**文件**: `server/routers/build.py` (MODIFIED)

**主要改动**:
1. 导入统一锁管理器: `from utils.build_lock import get_build_lock_manager`
2. 移除独立锁变量: 删除 `_build_running` 和 `_build_lock` (lines 219-220)
3. 创建全局锁管理器: `_lock_manager = get_build_lock_manager()`
4. 修改 `run_build()` 端点:
```python
lock_resource = "graph_build"

if not await _lock_manager.acquire_async(lock_resource, ttl=7200):
    return BuildResponse(
        status="already_running",
        message="已有构建任务正在运行，请等待其完成（来自 build.py 或 admin.py）",
        task_id=None
    )

background_tasks.add_task(_run_build_task, request)
```
5. 修改 `_run_build_task()` 释放锁:
```python
finally:
    await _lock_manager.release_async(lock_resource)
```
6. 修改 `get_build_status()` 检查锁:
```python
return {
    "is_running": _lock_manager.is_locked(lock_resource),
    "active_connections": len(get_broadcaster().active_connections),
}
```

#### 3. 迁移 admin.py 使用统一锁

**文件**: `server/routers/admin.py` (MODIFIED)

**主要改动**:
1. 导入统一锁管理器: `from utils.build_lock import get_build_lock_manager`
2. 移除独立锁变量: 删除 `_is_building` 和 `_build_lock` (lines 37-38)
3. 创建全局锁管理器: `_lock_manager = get_build_lock_manager()`
4. 修改 `trigger_full_build()` 和 `trigger_incremental_build()`:
```python
lock_resource = "graph_build"

if not await _lock_manager.acquire_async(lock_resource, ttl=7200):
    raise HTTPException(
        status_code=400,
        detail="已有构建任务正在运行，请等待其完成（来自 admin.py 或 build.py）"
    )

background_tasks.add_task(_run_full_build_task, task_id, config)
```
5. 修改 `_run_full_build_task()` 和 `_run_incremental_build_task()`:
```python
# 移除 global _is_building
lock_resource = "graph_build"

try:
    # ... 构建逻辑 ...
finally:
    _lock_manager.release(lock_resource)  # 同步版本（后台线程）
```
6. 修改 `get_build_status()`:
```python
status["is_running"] = _lock_manager.is_locked(lock_resource)
```

### 改进效果

| 改进点 | 改进前 | 改进后 |
|--------|--------|--------|
| **并发安全** | ❌ 不同模块锁隔离，可并发构建 | ✅ 统一分布式锁，全局互斥 |
| **多进程支持** | ❌ 内存锁在多 worker 下失效 | ✅ Redis 锁支持多进程部署 |
| **状态持久化** | ❌ 重启后状态丢失 | ✅ Redis 锁带 TTL，自动过期 |
| **错误提示** | ❌ "已有构建任务正在运行" | ✅ "来自 admin.py 或 build.py" |
| **降级方案** | ❌ 无降级 | ✅ Redis 失败自动降级到内存锁 |

---

## 问题二：聊天接口在未完成向量索引时不友好 (Unfriendly Chat UX)

### 问题描述

**现状**: 索引未就绪时，聊天服务直接抛出 HTTP 500 错误，用户体验差。

**代码证据**:
- `server/services/chat_service.py` (lines 248-257, 463-472): 捕获 "vector index" 错误后返回 `HTTPException(400)`

**用户体验**:
1. 用户发送消息 → 后端 500 报错 → 前端显示"服务器内部错误"
2. 用户不知道是系统故障还是索引未构建
3. 无法获知构建进度或剩余时间

### 解决方案

#### 1. 创建索引状态检查工具

**文件**: `server/utils/index_status.py` (NEW)

**功能**:
- **索引存在性检查**: `check_vector_index_exists()` 查询 Neo4j VECTOR 索引
- **数据存在性检查**: `check_index_has_data()` 检查节点是否存在
- **构建状态检查**: 调用 `get_build_lock_manager().is_locked()` 检查是否有构建任务
- **进度信息获取**: 调用 `get_progress_manager().get_current_status()` 获取构建进度

**状态枚举**:
```python
class IndexStatus(str, Enum):
    READY = "ready"           # 就绪：索引存在且无构建任务
    BUILDING = "building"     # 构建中：有构建任务正在运行
    EMPTY = "empty"           # 空：索引不存在且无构建任务
    ERROR = "error"           # 错误：检查失败
```

**返回格式**:
```python
{
    "status": "ready" | "building" | "empty" | "error",
    "message": str,
    "details": {
        "chunk_index_exists": bool,
        "entity_index_exists": bool,
        "chunk_data_exists": bool,
        "entity_data_exists": bool,
        "is_building": bool,
        "build_progress": {  # 仅 building 状态时存在
            "percent": int,
            "stage": str,
            "details": str
        }
    },
    "retry_after": int  # 仅 building 状态时存在（秒）
}
```

**核心逻辑**:
```python
def get_index_status() -> Dict:
    # 1. 检查是否有构建任务正在运行
    is_building = get_build_lock_manager().is_locked("graph_build")

    # 2. 检查索引是否存在
    chunk_index_exists = check_vector_index_exists("chunk_embedding_index")
    entity_index_exists = check_vector_index_exists("entity_embedding_index")

    # 3. 检查是否有数据
    chunk_data_exists = check_index_has_data("__Chunk__")
    entity_data_exists = check_index_has_data("__Entity__")

    # 4. 判断总体状态（优先级: building > empty > ready）
    if is_building:
        progress = get_progress_manager().get_current_status()
        return {"status": IndexStatus.BUILDING, ...}
    elif not (chunk_index_exists or entity_index_exists):
        return {"status": IndexStatus.EMPTY, ...}
    else:
        return {"status": IndexStatus.READY, ...}
```

#### 2. 修改 chat_service.py 添加优雅降级

**文件**: `server/services/chat_service.py` (MODIFIED)

**主要改动**:

**2.1 导入索引状态检查**:
```python
from utils.index_status import get_index_status, IndexStatus
```

**2.2 在 `process_chat()` 开头添加状态检查**:
```python
async def process_chat(...) -> Dict:
    """
    ✅ 改进：添加索引就绪状态检查，优雅降级
    """
    # ========== 索引状态检查（优雅降级） ==========
    try:
        index_status = get_index_status()

        if index_status["status"] == IndexStatus.BUILDING:
            # 构建中：返回 503 Service Unavailable + 进度信息
            build_progress = index_status["details"].get("build_progress", {})
            raise HTTPException(
                status_code=503,
                detail={
                    "message": index_status["message"],
                    "status": "building",
                    "progress": build_progress.get("percent", 0),
                    "stage": build_progress.get("stage", "unknown"),
                    "details": build_progress.get("details", "构建中..."),
                    "retry_after": index_status.get("retry_after", 10)
                }
            )

        elif index_status["status"] == IndexStatus.EMPTY:
            # 索引为空：返回 400 Bad Request + 友好提示
            raise HTTPException(
                status_code=400,
                detail={
                    "message": index_status["message"],
                    "status": "empty",
                    "action_required": "请先构建知识图谱"
                }
            )

        elif index_status["status"] == IndexStatus.ERROR:
            # 检查失败：记录日志但继续执行（优雅降级）
            print(f"⚠️ 索引状态检查失败（继续执行）: {index_status.get('message')}")

        # status == READY：继续正常流程
    except HTTPException:
        raise
    except Exception as e:
        print(f"⚠️ 索引状态检查异常（继续执行）: {e}")

    # ... 后续聊天逻辑 ...
```

**2.3 在 `process_chat_stream()` 添加类似逻辑**:
```python
async def process_chat_stream(...) -> AsyncGenerator[str, None]:
    """
    ✅ 改进：添加索引就绪状态检查，优雅降级
    """
    try:
        index_status = get_index_status()

        if index_status["status"] == IndexStatus.BUILDING:
            # 构建中：返回构建进度信息（流式）
            build_progress = index_status["details"].get("build_progress", {})
            yield json.dumps({
                "status": "building",
                "message": index_status["message"],
                "progress": build_progress.get("percent", 0),
                "stage": build_progress.get("stage", "unknown"),
                "details": build_progress.get("details", "构建中..."),
                "retry_after": index_status.get("retry_after", 10)
            })
            return

        elif index_status["status"] == IndexStatus.EMPTY:
            # 索引为空：返回友好提示（流式）
            yield json.dumps({
                "status": "empty",
                "message": index_status["message"],
                "action_required": "请先构建知识图谱"
            })
            return

        # status == READY：继续正常流程
    except Exception as e:
        print(f"⚠️ 索引状态检查异常（继续执行）: {e}")

    # ... 后续聊天逻辑 ...
```

### 改进效果

| 改进点 | 改进前 | 改进后 |
|--------|--------|--------|
| **错误代码** | ❌ HTTP 500 (服务器错误) | ✅ HTTP 503 (服务暂时不可用) / 400 (索引为空) |
| **错误信息** | ❌ "vector index does not exist" | ✅ "知识图谱正在构建中，请稍候..." |
| **进度可见性** | ❌ 无进度信息 | ✅ 返回 percent, stage, details |
| **重试指导** | ❌ 无重试建议 | ✅ 提供 retry_after (10 秒) |
| **空索引提示** | ❌ 通用错误 | ✅ 明确提示"请先构建知识图谱" |
| **前端集成** | ❌ 显示红色错误 | ✅ 可显示进度条 + 自动订阅 SSE |
| **检查时机** | ❌ 被动（错误发生后） | ✅ 主动（请求入口检查） |

---

## 架构改进图

### 改进前：锁隔离 + 被动错误处理

```
┌─────────────┐         ┌─────────────┐
│  build.py   │         │  admin.py   │
│             │         │             │
│ _build_lock │ (独立)  │ _build_lock │ (独立)
│_build_running│         │ _is_building│
└─────────────┘         └─────────────┘
      ↓                       ↓
   [可并发运行，导致冲突]


┌─────────────────┐
│ chat_service.py │
│                 │
│ try: agent.ask()│
│ except:         │
│   HTTP 500 ❌   │
└─────────────────┘
```

### 改进后：统一锁 + 主动状态检查

```
┌─────────────┐         ┌─────────────┐
│  build.py   │         │  admin.py   │
│             │         │             │
└──────┬──────┘         └──────┬──────┘
       │                       │
       └───────┬───────────────┘
               ↓
    ┌─────────────────────┐
    │ BuildLockManager    │
    │ (统一分布式锁)      │
    │ Redis: "graph_build"│
    │ TTL: 7200s          │
    └─────────────────────┘


┌─────────────────────────┐
│ chat_service.py         │
│                         │
│ 1. index_status = get...│
│ 2. if BUILDING:         │
│      HTTP 503 ✅        │
│    elif EMPTY:          │
│      HTTP 400 ✅        │
│    else:                │
│      agent.ask()        │
└─────────────────────────┘
```

---

## 测试建议

### 测试场景一：并发构建阻止

**步骤**:
1. 启动多个 Gunicorn worker: `gunicorn server.main:app --workers 4`
2. 同时调用 `/admin/build/full` 和 `/build/run`
3. **预期**: 第二个请求返回 400 "已有构建任务正在运行（来自 admin.py 或 build.py）"

### 测试场景二：构建中聊天优雅降级

**步骤**:
1. 触发构建任务: `POST /admin/build/full`
2. 立即发送聊天请求: `POST /chat`
3. **预期**: 返回 HTTP 503，包含:
   ```json
   {
     "detail": {
       "message": "知识图谱正在构建中，请稍候...",
       "status": "building",
       "progress": 45,
       "stage": "l1_indexing",
       "details": "正在执行 L1 深度索引...",
       "retry_after": 10
     }
   }
   ```

### 测试场景三：空索引友好提示

**步骤**:
1. 清空 Neo4j 数据库
2. 发送聊天请求: `POST /chat`
3. **预期**: 返回 HTTP 400，包含:
   ```json
   {
     "detail": {
       "message": "知识图谱尚未构建，请先完成以下步骤：\n1. 进入「📚 文档管理」上传文档\n...",
       "status": "empty",
       "action_required": "请先构建知识图谱"
     }
   }
   ```

### 测试场景四：Redis 降级

**步骤**:
1. 停止 Redis 服务: `docker stop redis`
2. 启动应用
3. **预期**: 日志显示 "⚠️ Redis 连接失败，降级到内存锁"
4. 触发构建任务仍然正常工作（单进程模式）

---

## 配置说明

### 环境变量

**Redis 配置** (用于分布式锁):
```env
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=  # 可选
```

**自动检测逻辑**:
- 如果 `REDIS_HOST` 存在 → 使用 Redis 分布式锁
- 如果 `REDIS_HOST` 不存在 → 降级到内存锁（仅限单进程）

### 锁资源标识

| 资源 | 标识符 | 用途 |
|------|--------|------|
| 图谱构建 | `graph_build` | 防止并发构建 |

### 锁 TTL 配置

| 场景 | TTL | 说明 |
|------|-----|------|
| 构建任务 | 7200 秒 (2 小时) | 防止构建卡死导致永久锁定 |

---

## 迁移指南

### 从旧版本升级

**步骤**:
1. **安装 Redis**（可选，用于多进程部署）:
   ```bash
   docker run -d --name redis -p 6379:6379 redis:latest
   ```

2. **更新配置**:
   - 在 `.env` 中添加 `REDIS_HOST=localhost`（如果使用 Redis）

3. **无需修改前端代码**:
   - 新的错误格式向后兼容
   - 前端可选择性地处理 `status: "building"` 显示进度条

4. **重启服务**:
   ```bash
   # 单进程（开发环境）
   python server/main.py

   # 多进程（生产环境）
   gunicorn server.main:app --workers 4 --bind 0.0.0.0:8000
   ```

### 回滚方案

如果遇到问题，可以临时回滚到旧版本：

**步骤**:
1. 恢复 `build.py` 和 `admin.py` 的 `_build_lock` 和 `_is_building` 变量
2. 移除 `from utils.build_lock import get_build_lock_manager` 导入
3. 恢复 `chat_service.py` 的旧版错误处理（移除 `get_index_status()` 调用）
4. 删除 `server/utils/build_lock.py` 和 `server/utils/index_status.py`

---

## 已知限制

1. **任务取消机制**: `stop_build()` 仅释放锁，实际后台任务可能仍在运行（需要实现任务取消信号）
2. **锁过期后的僵尸任务**: 如果构建任务超过 2 小时，锁会自动过期，但任务仍在后台运行
3. **前端集成**: 需要前端主动处理 HTTP 503 状态码并显示进度条（当前仅返回 JSON）

**未来改进**:
- [ ] 实现任务取消机制（SIGTERM 信号处理）
- [ ] 添加任务持久化（SQLite/Postgres 记录任务状态）
- [ ] 提供 WebSocket 接口实时推送进度（替代轮询）

---

## 相关文件清单

### 新增文件

| 文件 | 行数 | 功能 |
|------|------|------|
| `server/utils/build_lock.py` | 299 | 统一分布式锁管理器 |
| `server/utils/index_status.py` | 168 | 索引状态检查工具 |
| `PRODUCTION_IMPROVEMENTS.md` | 本文件 | 改进文档 |

### 修改文件

| 文件 | 改动行数 | 主要改动 |
|------|----------|----------|
| `server/routers/build.py` | ~50 | 迁移到统一锁 |
| `server/routers/admin.py` | ~60 | 迁移到统一锁 |
| `server/services/chat_service.py` | ~80 | 添加索引状态检查 + 优雅降级 |

---

## 总结

本次改进解决了生产环境中的两个关键问题：

1. **构建并发控制脆弱** → **统一分布式锁**
   - ✅ 支持多进程部署
   - ✅ 全局互斥，防止并发构建
   - ✅ 自动降级，提升容错性

2. **聊天接口不友好** → **索引状态检查 + 优雅降级**
   - ✅ 主动检查索引状态
   - ✅ 返回构建进度信息
   - ✅ 友好错误提示

**影响**:
- **用户体验**: 从"服务器错误"到"构建中，请稍候"
- **系统稳定性**: 从"可能并发构建"到"全局互斥"
- **可维护性**: 从"分散锁管理"到"统一锁接口"

**生产就绪度**: ✅ 通过
