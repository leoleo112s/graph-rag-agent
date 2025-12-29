"""
图谱构建 Celery 任务

用途：
- 将耗时的图谱构建任务移到独立的 Worker 进程
- 支持任务重试、超时控制、进度追踪
- 与 FastAPI 主进程解耦，避免资源竞争

使用方法：
    # 在 API router 中调用
    from server.tasks.build_tasks import build_graph_task

    @router.post("/build")
    async def start_build(request: BuildRequest):
        # 提交任务到 Celery
        task = build_graph_task.delay(
            mode="full",
            files=request.files
        )

        return {"task_id": task.id, "status": "submitted"}
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import time
from typing import Any, Dict, List, Optional

from graphrag_agent.integrations.build.incremental_graph_builder import IncrementalGraphBuilder
from graphrag_agent.pipelines.ingestion.document_processor import DocumentProcessor
from server.celery_app import app
from server.utils.logger import get_logger
from server.utils.redis_state import get_state_manager

logger = get_logger(__name__)
state_mgr = get_state_manager()


def progress_callback(percent: float, stage: str, details: str):
    """
    进度回调函数（被构建流程调用）

    Args:
        percent: 进度百分比 (0-100)
        stage: 当前阶段
        details: 详细信息
    """
    # 获取当前任务 ID（从 Celery 上下文）
    from celery import current_task

    if current_task and current_task.request.id:
        task_id = current_task.request.id

        # 更新进度到 Redis
        state_mgr.set_build_progress(
            task_id,
            {
                "percent": percent,
                "stage": stage,
                "details": details,
                "timestamp": time.time(),
            },
        )

        # 更新 Celery 任务状态（用于 Flower 监控）
        current_task.update_state(
            state="PROGRESS",
            meta={
                "percent": percent,
                "stage": stage,
                "details": details,
            },
        )

        logger.info(f"构建进度: {percent:.1f}% - {stage} - {details}", task_id=task_id)


@app.task(
    bind=True,  # 绑定任务实例，可以访问 self.request
    name="server.tasks.build_tasks.build_graph_task",
    max_retries=3,  # 最多重试 3 次
    soft_time_limit=3600,  # 1 小时软限制
    time_limit=3900,  # 1 小时 5 分钟硬限制
)
def build_graph_task(
    self,
    mode: str = "full",  # full, l0, l1
    files: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    图谱构建任务（完整构建）

    Args:
        self: Celery 任务实例
        mode: 构建模式（full, l0, l1）
        files: 文件列表（可选）
        config: 配置参数（可选）

    Returns:
        构建结果
    """
    task_id = self.request.id
    logger.info(f"开始图谱构建任务", task_id=task_id, mode=mode)

    # 获取分布式锁（防止并发构建）
    lock_key = f"build_{mode}"
    if not state_mgr.acquire_build_lock(lock_key, ttl=3600):
        logger.warning(f"构建任务已在运行中", task_id=task_id, lock_key=lock_key)
        return {"status": "error", "message": "已有构建任务正在运行，请稍后再试"}

    try:
        # 更新任务状态
        state_mgr.set_task_status(task_id, "running")

        # 初始化进度
        progress_callback(0, "initializing", "初始化构建环境")

        # 执行构建
        if mode == "full":
            result = _run_full_build(files, config, progress_callback)
        elif mode == "l0":
            result = _run_l0_build(files, config, progress_callback)
        elif mode == "l1":
            result = _run_l1_build(files, config, progress_callback)
        else:
            raise ValueError(f"未知的构建模式: {mode}")

        # 完成
        progress_callback(100, "completed", "构建完成")
        state_mgr.set_task_status(task_id, "success", result=result)

        logger.info(f"构建任务完成", task_id=task_id, result=result)
        return result

    except Exception as e:
        # 错误处理
        error_msg = str(e)
        logger.error(f"构建任务失败: {error_msg}", task_id=task_id, exc_info=True)

        progress_callback(0, "failed", f"构建失败: {error_msg}")
        state_mgr.set_task_status(task_id, "failed", error=error_msg)

        # 重试（如果还有重试次数）
        if self.request.retries < self.max_retries:
            logger.info(f"准备重试 ({self.request.retries + 1}/{self.max_retries})", task_id=task_id)
            raise self.retry(exc=e, countdown=60)  # 60秒后重试

        return {"status": "error", "message": error_msg}

    finally:
        # 释放锁
        state_mgr.release_build_lock(lock_key)


@app.task(
    bind=True,
    name="server.tasks.build_tasks.incremental_build_task",
    max_retries=3,
    soft_time_limit=1800,  # 30 分钟
    time_limit=2100,
)
def incremental_build_task(
    self,
    files: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    增量构建任务

    Args:
        self: Celery 任务实例
        files: 文件列表（可选）
        config: 配置参数（可选）

    Returns:
        构建结果
    """
    task_id = self.request.id
    logger.info(f"开始增量构建任务", task_id=task_id)

    # 获取分布式锁
    if not state_mgr.acquire_build_lock("incremental_build", ttl=1800):
        return {"status": "error", "message": "已有增量构建任务正在运行"}

    try:
        state_mgr.set_task_status(task_id, "running")
        progress_callback(0, "initializing", "初始化增量构建")

        # 执行增量构建
        builder = IncrementalGraphBuilder()
        result = builder.build(files=files, progress_callback=progress_callback)

        progress_callback(100, "completed", "增量构建完成")
        state_mgr.set_task_status(task_id, "success", result=result)

        return result

    except Exception as e:
        error_msg = str(e)
        logger.error(f"增量构建失败: {error_msg}", task_id=task_id, exc_info=True)

        progress_callback(0, "failed", f"构建失败: {error_msg}")
        state_mgr.set_task_status(task_id, "failed", error=error_msg)

        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60)

        return {"status": "error", "message": error_msg}

    finally:
        state_mgr.release_build_lock("incremental_build")


# ============================================================================
# 辅助函数
# ============================================================================


def _run_full_build(files: Optional[List[str]], config: Optional[Dict[str, Any]], callback) -> Dict[str, Any]:
    """执行完整构建"""
    callback(10, "processing_documents", "正在处理文档...")

    # 示例：文档处理
    processor = DocumentProcessor(directory_path="./files")
    documents, summary = processor.process_directory()

    callback(30, "extracting_entities", "正在抽取实体...")

    # 示例：实体抽取
    # ... 实际构建逻辑 ...

    callback(60, "building_graph", "正在构建图谱...")

    # 示例：图谱构建
    # ... 实际构建逻辑 ...

    callback(90, "indexing", "正在建立索引...")

    # 示例：索引构建
    # ... 实际构建逻辑 ...

    return {
        "status": "success",
        "documents_processed": len(documents),
        "entities_extracted": summary.total_entities if hasattr(summary, "total_entities") else 0,
    }


def _run_l0_build(files: Optional[List[str]], config: Optional[Dict[str, Any]], callback) -> Dict[str, Any]:
    """执行 L0 快速构建（仅文档处理和向量化）"""
    callback(10, "l0_processing", "L0 快速处理...")

    # L0 逻辑
    # ... 实际构建逻辑 ...

    callback(90, "l0_indexing", "L0 向量化...")

    return {"status": "success", "mode": "l0"}


def _run_l1_build(files: Optional[List[str]], config: Optional[Dict[str, Any]], callback) -> Dict[str, Any]:
    """执行 L1 图谱构建（实体抽取和图谱构建）"""
    callback(10, "l1_extraction", "L1 实体抽取...")

    # L1 逻辑
    # ... 实际构建逻辑 ...

    callback(90, "l1_graph_building", "L1 图谱构建...")

    return {"status": "success", "mode": "l1"}
