"""
图谱构建 API（Celery 版本）

用途：
- 替代 build.py 中的 BackgroundTasks
- 使用 Celery 任务队列处理构建任务
- 使用 Redis 状态管理支持多 Worker 进程

使用方法：
    1. 启动 Redis:
       docker run -d -p 6379:6379 redis:latest

    2. 启动 Celery Worker:
       celery -A server.celery_app worker --loglevel=info

    3. 启动 FastAPI:
       python server/main.py

    4. 提交构建任务:
       POST /api/v1/build_celery/run
       {
         "mode": "full",
         "files": ["file1.pdf", "file2.pdf"]
       }

    5. 查询任务状态:
       GET /api/v1/build_celery/status/{task_id}

    6. WebSocket 监听进度:
       ws://localhost:8000/api/v1/build_celery/ws/{task_id}
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from utils.redis_state import get_state_manager
from utils.logger import get_logger
from utils.exceptions import ResourceNotFoundError, BusinessException
from models.schemas import BaseResponse, ErrorCode
import asyncio

# 导入 Celery 任务
from tasks.build_tasks import build_graph_task, incremental_build_task

logger = get_logger(__name__)
state_mgr = get_state_manager()

router = APIRouter(prefix="/build_celery", tags=["图谱构建（Celery 版）"])


# ============================================================================
# 请求/响应模型
# ============================================================================

class BuildRequest(BaseModel):
    """构建请求"""
    mode: str = "full"  # full, l0, l1, incremental
    files: Optional[List[str]] = None
    config: Optional[Dict[str, Any]] = None


class BuildResponse(BaseModel):
    """构建响应"""
    task_id: str
    status: str
    message: str


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    status: str  # pending, running, success, failed
    progress: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("/run", response_model=BuildResponse, summary="提交构建任务")
async def submit_build_task(request: BuildRequest):
    """
    提交图谱构建任务到 Celery 队列

    流程：
    1. 验证请求参数
    2. 提交任务到 Celery
    3. 返回任务 ID

    注意：这个接口立即返回，不等待任务完成。
    使用 /status/{task_id} 查询任务进度，或使用 WebSocket 监听。
    """
    logger.info("收到构建请求", mode=request.mode, files_count=len(request.files or []))

    # 检查是否有构建任务正在运行（可选）
    lock_key = f"build_{request.mode}"
    if not state_mgr.acquire_build_lock(lock_key, ttl=10):
        # 锁已存在，说明有任务正在运行
        # 但我们仍然可以提交新任务到队列，由 Celery 自动排队
        logger.warning("已有构建任务排队中", mode=request.mode)
        # 释放临时锁
        state_mgr.release_build_lock(lock_key)

    # 提交任务到 Celery
    if request.mode == "incremental":
        task = incremental_build_task.delay(
            files=request.files,
            config=request.config
        )
    else:
        task = build_graph_task.delay(
            mode=request.mode,
            files=request.files,
            config=request.config
        )

    logger.info("任务已提交", task_id=task.id, mode=request.mode)

    return BuildResponse(
        task_id=task.id,
        status="submitted",
        message=f"构建任务已提交到队列，任务 ID: {task.id}"
    )


@router.get("/status/{task_id}", response_model=TaskStatusResponse, summary="查询任务状态")
async def get_task_status(task_id: str):
    """
    查询构建任务状态

    返回：
    - 任务状态（pending, running, success, failed）
    - 进度信息（百分比、当前阶段、详细信息）
    - 结果（如果已完成）
    - 错误信息（如果失败）
    """
    logger.debug("查询任务状态", task_id=task_id)

    # 从 Redis 获取进度
    progress = state_mgr.get_build_progress(task_id)

    # 从 Redis 获取任务状态
    task_status = state_mgr.get_task_status(task_id)

    if not task_status:
        # 如果 Redis 中没有状态，尝试从 Celery 获取
        from celery.result import AsyncResult
        celery_result = AsyncResult(task_id)

        if celery_result.state == "PENDING":
            status = "pending"
        elif celery_result.state == "STARTED" or celery_result.state == "PROGRESS":
            status = "running"
        elif celery_result.state == "SUCCESS":
            status = "success"
        elif celery_result.state == "FAILURE":
            status = "failed"
        else:
            status = celery_result.state.lower()

        task_status = {
            "status": status,
            "result": celery_result.result if celery_result.successful() else None,
            "error": str(celery_result.result) if celery_result.failed() else None
        }

    return TaskStatusResponse(
        task_id=task_id,
        status=task_status["status"],
        progress=progress,
        result=task_status.get("result"),
        error=task_status.get("error")
    )


@router.websocket("/ws/{task_id}")
async def websocket_progress(websocket: WebSocket, task_id: str):
    """
    WebSocket 实时监听构建进度

    客户端连接后，服务端会：
    1. 发送当前进度（如果存在）
    2. 实时推送进度更新
    3. 任务完成或失败后自动关闭连接

    消息格式：
    {
        "percent": 50,
        "stage": "entity_extraction",
        "details": "正在抽取实体...",
        "timestamp": 1640000000.0
    }
    """
    await websocket.accept()
    logger.info("WebSocket 连接建立", task_id=task_id)

    try:
        # 订阅 Redis Pub/Sub
        async for progress in state_mgr.subscribe_progress(task_id):
            await websocket.send_json(progress)

            # 如果任务完成或失败，自动关闭连接
            if progress.get("percent", 0) >= 100 or progress.get("stage") in ["completed", "failed"]:
                logger.info("任务结束，关闭 WebSocket", task_id=task_id, stage=progress.get("stage"))
                break

    except WebSocketDisconnect:
        logger.info("WebSocket 客户端断开连接", task_id=task_id)

    except Exception as e:
        logger.error(f"WebSocket 错误: {str(e)}", task_id=task_id, exc_info=True)

    finally:
        await websocket.close()


@router.delete("/{task_id}", summary="取消构建任务")
async def cancel_build_task(task_id: str):
    """
    取消构建任务

    注意：
    - 如果任务还在队列中（pending），可以成功取消
    - 如果任务正在执行（running），取消可能不会立即生效
    - Celery 会尽力终止任务，但无法保证 100% 成功
    """
    from celery.result import AsyncResult

    logger.info("尝试取消任务", task_id=task_id)

    result = AsyncResult(task_id)
    result.revoke(terminate=True, signal="SIGKILL")

    # 清理 Redis 状态
    state_mgr.delete_build_progress(task_id)
    state_mgr.set_task_status(task_id, "cancelled")

    return {
        "status": "success",
        "message": f"任务 {task_id} 已取消"
    }


@router.get("/list", summary="列出所有任务")
async def list_tasks(
    status: Optional[str] = Query(None, description="任务状态过滤（running, success, failed）"),
    limit: int = Query(100, description="返回数量限制", ge=1, le=1000)
):
    """
    列出构建任务（需要 Redis 支持）

    返回最近的构建任务列表
    """
    # 这需要在 Redis 中维护一个任务索引
    # 示例实现：使用 sorted set 存储任务 ID，按时间戳排序
    # ZADD build:tasks:index <timestamp> <task_id>

    # 这里仅作为示例，实际需要实现
    return {
        "tasks": [],
        "message": "Task listing requires Redis sorted set implementation"
    }
