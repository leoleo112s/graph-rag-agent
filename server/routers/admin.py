"""
管理路由 (Admin Router)
提供文档管理、配置管理、构建管理 (V2集成) 等管理 API
"""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException
from fastapi.responses import StreamingResponse

# 引入构建历史数据库
from models.build_history import BuildStage as HistoryBuildStage
from models.build_history import BuildStatus, BuildType, get_build_history_db
from pydantic import BaseModel

# 引入配置服务（热更新机制）
from services.graph_config_service import get_config_service
from utils.build_lock import get_build_lock_manager  # ✅ 使用统一的锁管理器
from utils.progress_broadcaster import get_broadcaster
from utils.progress_manager import get_progress_manager

from graphrag_agent.config.graph_config_model import GraphConfig
from graphrag_agent.config.graph_config_storage import get_storage
from graphrag_agent.config.neo4jdb import get_db_manager

# 引入配置
from graphrag_agent.config.settings import FILES_DIR
from graphrag_agent.graph.core import connection_manager

# 引入 V2 构建管理器和广播器
from graphrag_agent.integrations.build.incremental_update_v2 import IncrementalUpdateManagerV2

# 配置日志
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# ✅ 移除独立的锁和状态变量（已由 BuildLockManager 统一管理）
# _build_lock = asyncio.Lock()  # ❌ 删除
# _is_building = False  # ❌ 删除

# 全局锁管理器
_lock_manager = get_build_lock_manager()

# ==================== 🟢 关键：配置格式转换辅助函数 ====================


def _process_config_for_pipeline(raw_config: Optional[Dict]) -> Dict:
    """
    将前端复杂的图谱配置（Domain/Bridge结构）
    转换为 Pipeline 能理解的扁平化配置（entity_types, relationship_types, chunking_strategy）
    """
    if not raw_config:
        return {}

    print(f"DEBUG: [Admin] 正在解析配置... 项目: {raw_config.get('project_name')}")

    # 1. 提取实体类型
    entities = set()
    # 兼容旧格式（直接在根目录）
    if raw_config.get("entity_types"):
        entities.update(raw_config["entity_types"])

    # 处理新格式（从 domain_definitions 里提取）
    domains = raw_config.get("domain_definitions", [])
    for domain in domains:
        schema = domain.get("schema", {})
        if schema.get("entities"):
            entities.update(schema["entities"])

    # 2. 提取关系类型
    relations = set()
    if raw_config.get("relationship_types"):
        relations.update(raw_config["relationship_types"])

    for domain in domains:
        schema = domain.get("schema", {})
        if schema.get("relations"):
            relations.update(schema["relations"])

    # 3. 提取分块配置
    chunking_strategy = raw_config.get("chunking_strategy", "simple")
    chunk_size = raw_config.get("chunk_size", 500)
    chunk_overlap = raw_config.get("chunk_overlap", 100)

    # 4. 构造结果
    result = {}
    if entities:
        result["entity_types"] = list(entities)
        print(f"DEBUG: [Admin] 提取到 {len(entities)} 种实体类型: {list(entities)[:5]}...")

    if relations:
        result["relationship_types"] = list(relations)
        print(f"DEBUG: [Admin] 提取到 {len(relations)} 种关系类型")

    # 🔥 添加分块配置到result
    result["chunking_strategy"] = chunking_strategy
    result["chunk_size"] = chunk_size
    result["chunk_overlap"] = chunk_overlap
    print(f"DEBUG: [Admin] 分块配置: {chunking_strategy}, size={chunk_size}, overlap={chunk_overlap}")

    return result


def _apply_graph_config(raw_config: Optional[Dict]) -> None:
    """
    将前端选择的配置写入 GraphConfigService（持久化到 graph_config.json）
    以确保构建管道的动态提示词和抽取逻辑使用最新配置。
    """
    if not raw_config:
        return

    try:
        config_obj = GraphConfig(**raw_config)
    except Exception as exc:
        raise ValueError(f"图谱配置解析失败: {exc}") from exc

    config_service = get_config_service()
    config_service.update_config_obj(config_obj)
    logger.info("已同步图谱配置到 graph_config.json: %s", config_obj.project_name)

# ==================== 核心构建逻辑 (V2 集成) ====================


def _run_full_build_task(task_id: str, config: Optional[Dict] = None):
    """后台执行全量构建任务"""
    # ✅ 定义锁资源名称
    lock_resource = "graph_build"
    pm = get_progress_manager()
    history_db = get_build_history_db()

    # 创建历史记录
    record_id = history_db.create_record(task_type=BuildType.FULL, config_snapshot=config)
    logger.info(f"创建构建历史记录: {record_id}")

    try:
        # 0. 同步用户选择的图谱配置（确保构建使用当前配置）
        _apply_graph_config(config)

        # 1. 处理配置格式
        pipeline_config = _process_config_for_pipeline(config)

        # 2. 初始化管理器
        manager = IncrementalUpdateManagerV2(config=pipeline_config)

        # 3. 执行构建
        logger.info(f"开始执行全量构建: {task_id}")
        pm.update_status("initializing", 5, "初始化构建环境")

        # 🔥 使用 asyncio.run 运行异步管道（clean=True 清空现有数据）
        result = asyncio.run(manager.run_full_pipeline(clean=True))

        # 4. 更新状态和历史
        l0_count = result.get("l0", {}).get("files_processed", 0)
        l1_count = result.get("l1", {}).get("submitted_count", 0)

        stats = {"l0_files": l0_count, "l1_tasks": l1_count}

        msg = f"全量构建完成: 处理 {l0_count} 个文件, 提交 {l1_count} 个图谱任务"
        pm.update_status("completed", 100, msg)

        # 更新历史记录为成功
        history_db.update_record(
            record_id=record_id, status=BuildStatus.COMPLETED, stats=stats, final_stage="completed"
        )

    except Exception as e:
        logger.error(f"全量构建发生异常: {str(e)}", exc_info=True)
        error_msg = str(e)
        pm.update_status("failed", 0, f"构建失败: {error_msg}")

        # 更新历史记录为失败
        history_db.update_record(
            record_id=record_id, status=BuildStatus.FAILED, error_msg=error_msg, final_stage="failed"
        )
    finally:
        # ✅ 关键修复：释放分布式锁（同步版本，因为此函数在后台线程中运行）
        # 在释放前检查是否持有锁，避免重复释放导致的错误
        if _lock_manager.is_locked(lock_resource):
            _lock_manager.release(lock_resource)


def _run_incremental_build_task(task_id: str, config: Optional[Dict] = None):
    """后台执行增量构建任务"""
    # ✅ 使用统一的分布式锁（无需 global 变量）
    lock_resource = "graph_build"

    pm = get_progress_manager()
    history_db = get_build_history_db()

    # 创建历史记录
    record_id = history_db.create_record(task_type=BuildType.INCREMENTAL, config_snapshot=config)
    logger.info(f"创建构建历史记录: {record_id}")

    try:
        # 0. 同步用户选择的图谱配置（确保构建使用当前配置）
        _apply_graph_config(config)

        # 1. 处理配置格式
        pipeline_config = _process_config_for_pipeline(config)

        # 2. 初始化管理器
        manager = IncrementalUpdateManagerV2(config=pipeline_config)

        # 3. 执行构建
        logger.info(f"开始执行增量构建: {task_id}")
        pm.update_status("detecting_changes", 10, "检测文件变化")

        # 🔥 增量构建：clean=False 保留现有数据
        result = asyncio.run(manager.run_full_pipeline(clean=False))

        # 4. 更新状态和历史
        l0_count = result.get("l0", {}).get("files_processed", 0)
        l1_count = result.get("l1", {}).get("submitted_count", 0)

        stats = {"l0_files": l0_count, "l1_tasks": l1_count}

        msg = f"增量构建完成: 处理 {l0_count} 个文件, 提交 {l1_count} 个图谱任务"
        pm.update_status("completed", 100, msg)

        # 更新历史记录为成功
        history_db.update_record(
            record_id=record_id, status=BuildStatus.COMPLETED, stats=stats, final_stage="completed"
        )

    except Exception as e:
        logger.error(f"增量构建发生异常: {str(e)}", exc_info=True)
        error_msg = str(e)
        pm.update_status("failed", 0, f"构建失败: {error_msg}")

        # 更新历史记录为失败
        history_db.update_record(
            record_id=record_id, status=BuildStatus.FAILED, error_msg=error_msg, final_stage="failed"
        )
    finally:
        # ✅ 释放分布式锁（同步版本，因为此函数在后台线程中运行）
        _lock_manager.release(lock_resource)


# ==================== 构建 API ====================


@router.post("/build/full")
async def trigger_full_build(
    background_tasks: BackgroundTasks, config: Dict = Body(default=None)  # 🟢 接收前端传来的 JSON 配置
):
    """触发完整构建 (V2集成版，支持动态配置)

    ✅ 改进：使用分布式锁，支持多进程部署
    ✅ 与 build.py 共享同一个锁，防止并发冲突
    """
    logger.info("收到完整构建请求")

    lock_resource = "graph_build"

    # ✅ 尝试获取分布式锁
    if not await _lock_manager.acquire_async(lock_resource, ttl=7200):  # 2 小时 TTL
        raise HTTPException(status_code=400, detail="已有构建任务正在运行，请等待其完成（来自 admin.py 或 build.py）")

    task_id = str(uuid.uuid4())
    # 启动后台任务 (🟢 将 config 传递给任务，锁会在任务完成后释放)
    background_tasks.add_task(_run_full_build_task, task_id, config)

    return {"message": "完整构建已在后台启动", "status": "running", "task_id": task_id}


@router.post("/build/incremental")
async def trigger_incremental_build(
    background_tasks: BackgroundTasks, config: Dict = Body(default=None)  # 🟢 接收前端传来的 JSON 配置
):
    """触发增量构建 (V2集成版，支持动态配置)

    ✅ 改进：使用分布式锁，支持多进程部署
    ✅ 与 build.py 共享同一个锁，防止并发冲突
    """
    logger.info("收到增量构建请求")

    lock_resource = "graph_build"

    # ✅ 尝试获取分布式锁
    if not await _lock_manager.acquire_async(lock_resource, ttl=7200):  # 2 小时 TTL
        raise HTTPException(status_code=400, detail="已有构建任务正在运行，请等待其完成（来自 admin.py 或 build.py）")

    task_id = str(uuid.uuid4())
    # 启动后台任务 (🟢 将 config 传递给任务，锁会在任务完成后释放)
    background_tasks.add_task(_run_incremental_build_task, task_id, config)

    return {"message": "增量构建已在后台启动", "status": "running", "task_id": task_id}


@router.post("/build/stop")
async def stop_build():
    """停止构建

    ✅ 改进：使用分布式锁
    """
    lock_resource = "graph_build"

    # ✅ 检查是否有任务在运行
    if not _lock_manager.is_locked(lock_resource):
        raise HTTPException(status_code=400, detail="当前没有运行中的构建任务")

    # TODO: 实现实际的停止逻辑（需要任务取消机制）
    # 目前仅释放锁，实际任务可能仍在运行
    await _lock_manager.release_async(lock_resource)

    await get_broadcaster().emit_status("stopped", "构建任务已被用户停止")

    return {"status": "stopped", "message": "构建任务停止指令已发送（锁已释放）"}


@router.get("/build/status")
async def get_build_status():
    """获取构建状态

    ✅ 改进：使用分布式锁状态，支持多进程
    ✅ 字段映射：将 ProgressManager 格式转换为前端期望的格式
    """
    from datetime import datetime

    lock_resource = "graph_build"

    pm_status = get_progress_manager().get_current_status()

    # 判断总体状态
    is_locked = _lock_manager.is_locked(lock_resource)
    stage = pm_status.get("stage", "idle")

    # 根据 stage 和 lock 状态推断总体状态
    if is_locked:
        overall_status = "running"
    elif stage == "completed":
        overall_status = "completed"
    elif stage == "failed":
        overall_status = "failed"
    else:
        overall_status = "idle"

    # 计算已用时间（秒）
    elapsed_time = 0
    start_time_str = pm_status.get("start_time")
    if start_time_str:
        try:
            start_time = datetime.fromisoformat(start_time_str)
            elapsed_time = int((datetime.now() - start_time).total_seconds())
        except (ValueError, TypeError):
            elapsed_time = 0

    # 映射字段：ProgressManager 格式 -> 前端期望格式
    frontend_status = {
        # 前端期望的字段
        "status": overall_status,                # running/completed/idle/failed
        "progress": pm_status.get("percent", 0),  # 进度百分比
        "current_stage": pm_status.get("stage", "N/A"),  # 当前阶段
        "processed": pm_status.get("stats", {}).get("l0_files", 0),  # 已处理文件数
        "total": pm_status.get("stats", {}).get("l0_files", 0),  # 总文件数（暂时相同）
        "elapsed_time": elapsed_time,  # 已用时间（秒）
        "logs": pm_status.get("logs", []),  # 日志列表

        # 兼容旧字段
        "is_running": is_locked,
        "details": pm_status.get("details", ""),
        "stats": pm_status.get("stats", {}),
        "last_update": pm_status.get("last_update", ""),

        # 原始字段（调试用）
        "percent": pm_status.get("percent", 0),
        "stage": pm_status.get("stage", "idle"),
    }

    return frontend_status


@router.get("/build/stream")
async def stream_build_progress():
    """
    SSE 接口：实时推送构建进度

    Returns:
        StreamingResponse: Server-Sent Events 流
    """
    logger.info("新的 SSE 客户端连接")

    async def event_stream():
        """生成 SSE 事件流"""
        pm = get_progress_manager()

        try:
            async for event in pm.event_generator():
                # 格式化为 SSE 格式
                event_name = event.get("event", "message")
                data = event.get("data", "{}")

                yield f"event: {event_name}\n"
                yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            logger.info("SSE 客户端断开连接")
        except Exception as e:
            logger.error(f"SSE 流错误: {str(e)}", exc_info=True)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/build/history")
async def get_build_history(
    limit: int = 50, offset: int = 0, status: Optional[str] = None, task_type: Optional[str] = None
):
    """
    获取构建历史记录

    Args:
        limit: 返回数量限制
        offset: 偏移量
        status: 过滤状态 (running/completed/failed/cancelled)
        task_type: 过滤构建类型 (full/incremental)

    Returns:
        构建历史记录列表
    """
    logger.info(f"查询构建历史: limit={limit}, offset={offset}")

    try:
        history_db = get_build_history_db()

        # 转换过滤参数
        status_filter = BuildStatus(status) if status else None
        type_filter = BuildType(task_type) if task_type else None

        records = history_db.list_records(limit=limit, offset=offset, status=status_filter, task_type=type_filter)

        return {"records": [r.model_dump() for r in records], "count": len(records), "limit": limit, "offset": offset}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"无效的过滤参数: {str(e)}")
    except Exception as e:
        logger.error(f"获取构建历史失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取构建历史失败: {str(e)}")


@router.get("/build/statistics")
async def get_build_statistics():
    """
    获取构建统计信息

    Returns:
        统计数据
    """
    logger.info("查询构建统计信息")

    try:
        history_db = get_build_history_db()
        stats = history_db.get_statistics()
        return stats

    except Exception as e:
        logger.error(f"获取构建统计失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取构建统计失败: {str(e)}")


# ==================== 统计与文件 API ====================


@router.get("/graph/stats")
async def get_graph_stats():
    """获取图谱统计信息（包含类型分布）"""
    logger.info("收到图谱统计请求")
    try:
        # 查询实体数量
        entity_count_query = "MATCH (n:`__Entity__`) RETURN count(n) as count"
        entity_result = connection_manager.execute_query(entity_count_query)
        entity_count = entity_result[0]["count"] if entity_result else 0

        # 查询关系数量
        relationship_count_query = "MATCH ()-[r:`__Relationship__`]->() RETURN count(r) as count"
        relationship_result = connection_manager.execute_query(relationship_count_query)
        relationship_count = relationship_result[0]["count"] if relationship_result else 0

        # 查询实体类型分布
        entity_type_query = """
        MATCH (e:`__Entity__`)
        WHERE e.type IS NOT NULL AND e.type <> ''
        RETURN e.type AS type, count(e) AS count
        ORDER BY count DESC
        """
        entity_type_result = connection_manager.execute_query(entity_type_query)
        entity_type_distribution = {
            row["type"]: row["count"] for row in entity_type_result
        } if entity_type_result else {}

        # 查询关系类型分布
        relationship_type_query = """
        MATCH ()-[r:`__Relationship__`]->()
        WHERE r.type IS NOT NULL AND r.type <> ''
        RETURN r.type AS type, count(r) AS count
        ORDER BY count DESC
        """
        relationship_type_result = connection_manager.execute_query(relationship_type_query)
        relationship_type_distribution = {
            row["type"]: row["count"] for row in relationship_type_result
        } if relationship_type_result else {}

        # 查询社区数量
        community_count_query = (
            "MATCH (n) WHERE n.community_id IS NOT NULL RETURN count(DISTINCT n.community_id) as count"
        )
        community_result = connection_manager.execute_query(community_count_query)
        community_count = community_result[0]["count"] if community_result else 0

        # 统计文档数量
        files_dir = Path(FILES_DIR)
        document_count = len([f for f in files_dir.iterdir() if f.is_file()]) if files_dir.exists() else 0

        return {
            "entity_count": entity_count,
            "relationship_count": relationship_count,
            "community_count": community_count,
            "document_count": document_count,
            "entity_type_distribution": entity_type_distribution,  # 新增
            "relationship_type_distribution": relationship_type_distribution,  # 新增
            "last_build_time": datetime.now().isoformat() if entity_count > 0 else None,
        }
    except Exception as e:
        logger.error(f"获取图谱统计失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取图谱统计失败: {str(e)}")


@router.get("/health")
async def health_check():
    """
    健康检查（增强版）

    检查项：
    1. Neo4j 连接状态（读取测试）
    2. Neo4j 写入测试（延迟测量）
    3. 连接池状态（活跃/空闲连接数）
    4. 磁盘空间检查
    5. 文件目录可写性

    返回：
    - status: 总体状态（healthy, degraded, unhealthy）
    - checks: 各项检查详情
    - timestamp: 检查时间戳
    """
    import time

    checks = {
        "neo4j_read": {"status": "unknown", "latency_ms": None, "error": None},
        "neo4j_write": {"status": "unknown", "latency_ms": None, "error": None},
        "neo4j_pool": {"status": "unknown", "active": None, "idle": None, "error": None},
        "disk_space": {"status": "unknown", "free_gb": None, "error": None},
        "files_dir": {"status": "unknown", "writable": False, "error": None},
    }

    overall_status = "healthy"

    # 1. Neo4j 读取测试
    try:
        start = time.time()
        connection_manager.execute_query("RETURN 1 AS test")
        latency_ms = (time.time() - start) * 1000

        checks["neo4j_read"]["status"] = "healthy"
        checks["neo4j_read"]["latency_ms"] = round(latency_ms, 2)

        # 超过 100ms 标记为降级
        if latency_ms > 100:
            checks["neo4j_read"]["status"] = "degraded"
            overall_status = "degraded"
    except Exception as e:
        checks["neo4j_read"]["status"] = "unhealthy"
        checks["neo4j_read"]["error"] = str(e)
        overall_status = "unhealthy"

    # 2. Neo4j 写入测试（使用临时节点）
    try:
        start = time.time()
        test_id = str(uuid.uuid4())

        # 创建临时测试节点
        create_query = f"""
        CREATE (n:__HealthCheck__ {{id: '{test_id}', timestamp: timestamp()}})
        RETURN n.id AS id
        """
        result = connection_manager.execute_query(create_query)

        # 删除测试节点
        delete_query = f"MATCH (n:__HealthCheck__ {{id: '{test_id}'}}) DELETE n"
        connection_manager.execute_query(delete_query)

        latency_ms = (time.time() - start) * 1000

        checks["neo4j_write"]["status"] = "healthy"
        checks["neo4j_write"]["latency_ms"] = round(latency_ms, 2)

        # 超过 200ms 标记为降级
        if latency_ms > 200:
            checks["neo4j_write"]["status"] = "degraded"
            if overall_status == "healthy":
                overall_status = "degraded"
    except Exception as e:
        checks["neo4j_write"]["status"] = "unhealthy"
        checks["neo4j_write"]["error"] = str(e)
        overall_status = "unhealthy"

    # 3. 连接池状态检查
    try:
        # 查询连接池信息（需要 APOC 插件）
        pool_query = """
        CALL dbms.queryJmx('org.neo4j:*,name=Pool,*')
        YIELD name, attributes
        RETURN name, attributes
        """
        pool_result = connection_manager.execute_query(pool_query)

        if pool_result:
            # 提取连接池指标
            for record in pool_result:
                attrs = record.get("attributes", {})
                if "NumIdle" in attrs and "NumActive" in attrs:
                    checks["neo4j_pool"]["idle"] = attrs["NumIdle"]
                    checks["neo4j_pool"]["active"] = attrs["NumActive"]
                    checks["neo4j_pool"]["status"] = "healthy"
                    break
        else:
            # 如果 APOC 不可用，使用备用检查
            checks["neo4j_pool"]["status"] = "healthy"
            checks["neo4j_pool"]["error"] = "APOC unavailable, pool metrics not available"
    except Exception as e:
        # 连接池检查失败不影响整体状态（非关键）
        checks["neo4j_pool"]["status"] = "degraded"
        checks["neo4j_pool"]["error"] = f"Pool check failed: {str(e)}"

    # 4. 磁盘空间检查
    try:
        import shutil

        total, used, free = shutil.disk_usage("/")
        free_gb = free / (1024**3)

        checks["disk_space"]["free_gb"] = round(free_gb, 2)

        if free_gb < 1:  # 少于 1GB
            checks["disk_space"]["status"] = "unhealthy"
            overall_status = "unhealthy"
        elif free_gb < 5:  # 少于 5GB
            checks["disk_space"]["status"] = "degraded"
            if overall_status == "healthy":
                overall_status = "degraded"
        else:
            checks["disk_space"]["status"] = "healthy"
    except Exception as e:
        checks["disk_space"]["status"] = "degraded"
        checks["disk_space"]["error"] = str(e)

    # 5. 文件目录可写性检查
    try:
        files_dir = Path(FILES_DIR)

        # 确保目录存在
        files_dir.mkdir(parents=True, exist_ok=True)

        # 测试写入
        test_file = files_dir / f".health_check_{uuid.uuid4()}.tmp"
        test_file.write_text("health check test")
        test_file.unlink()  # 删除测试文件

        checks["files_dir"]["status"] = "healthy"
        checks["files_dir"]["writable"] = True
    except Exception as e:
        checks["files_dir"]["status"] = "unhealthy"
        checks["files_dir"]["writable"] = False
        checks["files_dir"]["error"] = str(e)
        overall_status = "unhealthy"

    return {"status": overall_status, "checks": checks, "timestamp": datetime.now().isoformat()}


@router.get("/files/list")
async def list_files():
    """列出所有已上传的文档"""
    try:
        files_dir = Path(FILES_DIR)
        if not files_dir.exists():
            files_dir.mkdir(parents=True, exist_ok=True)
            return {"files": [], "count": 0}

        files = []
        for file_path in files_dir.iterdir():
            if file_path.is_file():
                stat = file_path.stat()
                files.append(
                    {
                        "name": file_path.name,
                        "path": str(file_path),
                        "size": stat.st_size,
                        "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )
        files.sort(key=lambda x: x["modified_at"], reverse=True)
        return {"files": files, "count": len(files), "directory": str(files_dir)}
    except Exception as e:
        logger.error(f"获取文件列表失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取文件列表失败: {str(e)}")


# ==================== 图谱配置管理 API ====================


@router.get("/graph/config")
async def get_graph_config():
    """获取当前图谱配置（从内存缓存读取）"""
    logger.info("收到获取图谱配置请求")

    try:
        # 🔥 使用 GraphConfigService 获取配置（优先读缓存）
        config_service = get_config_service()
        config = config_service.get_config()

        if config is None:
            logger.info("当前无配置，返回空")
            return {"exists": False, "config": None}

        logger.info(f"返回配置: {config.project_name} (缓存状态: {config_service.get_cache_status()})")
        return {"exists": True, "config": config.model_dump(mode="json")}

    except Exception as e:
        logger.error(f"获取图谱配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.post("/graph/config")
async def save_graph_config(config: GraphConfig):
    """保存图谱配置并刷新内存缓存（热更新）"""
    logger.info(f"收到保存图谱配置请求: {config.project_name}")

    try:
        # 🔥 使用 GraphConfigService 保存配置（自动刷新缓存）
        config_service = get_config_service()
        saved_config = config_service.update_config_obj(config)

        logger.info(f"配置保存成功并已刷新缓存: {saved_config.project_name}")
        return {
            "message": "配置保存成功，已自动刷新缓存",
            "project_name": saved_config.project_name,
            "cache_status": config_service.get_cache_status(),
        }

    except ValueError as e:
        # 配置验证失败
        logger.error(f"配置验证失败: {str(e)}")
        raise HTTPException(status_code=400, detail=f"配置验证失败: {str(e)}")
    except Exception as e:
        logger.error(f"保存图谱配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存配置失败: {str(e)}")


@router.delete("/graph/config")
async def delete_graph_config():
    """删除图谱配置并清空内存缓存"""
    logger.info("收到删除图谱配置请求")

    try:
        # 🔥 使用 GraphConfigService 删除配置（自动清空缓存）
        config_service = get_config_service()
        success = config_service.delete_config()

        if success:
            logger.info("配置删除成功并已清空缓存")
            return {"message": "配置删除成功，缓存已清空", "cache_status": config_service.get_cache_status()}
        else:
            logger.error("配置删除失败")
            raise HTTPException(status_code=500, detail="配置删除失败")

    except Exception as e:
        logger.error(f"删除图谱配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除配置失败: {str(e)}")


@router.get("/graph/templates")
async def list_graph_templates():
    """列出所有可用的行业模板"""
    logger.info("收到列出模板请求")

    try:
        storage = get_storage()
        templates = storage.list_templates()

        logger.info(f"返回 {len(templates)} 个模板")
        return {"templates": templates}

    except Exception as e:
        logger.error(f"列出模板失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"列出模板失败: {str(e)}")


@router.get("/graph/templates/{template_name}")
async def get_graph_template(template_name: str):
    """获取指定模板的详细信息"""
    logger.info(f"收到获取模板请求: {template_name}")

    try:
        storage = get_storage()
        config = storage.load_template(template_name)

        if config is None:
            logger.warning(f"模板不存在: {template_name}")
            raise HTTPException(status_code=404, detail=f"模板 '{template_name}' 不存在")

        logger.info(f"返回模板: {template_name}")
        return {"config": config.model_dump(mode="json")}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取模板失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取模板失败: {str(e)}")


@router.post("/graph/config/from-template")
async def create_config_from_template(
    template_name: str, project_name: Optional[str] = None, created_by: Optional[str] = None
):
    """从模板创建并保存配置"""
    logger.info(f"收到从模板创建配置请求: {template_name}")

    try:
        storage = get_storage()
        success = storage.save_from_template(
            template_name=template_name, project_name=project_name, created_by=created_by
        )

        if success:
            logger.info(f"从模板创建配置成功: {template_name}")
            return {
                "message": "配置创建成功",
                "template_name": template_name,
                "project_name": project_name or f"{template_name}_project",
            }
        else:
            logger.error(f"模板不存在或保存失败: {template_name}")
            raise HTTPException(status_code=400, detail=f"模板 '{template_name}' 不存在或保存失败")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"从模板创建配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"从模板创建配置失败: {str(e)}")


# ==================== AI Copilot API ====================


@router.post("/ai-copilot/analyze-documents")
async def analyze_documents_for_config(industry_hint: Optional[str] = None, num_clusters: Optional[int] = None):
    """
    分析已上传的文档，生成配置推荐

    Args:
        industry_hint: 行业提示（可选）
        num_clusters: 聚类数量（可选，默认自动确定）

    Returns:
        文档分析结果和配置推荐
    """
    logger.info("收到 AI Copilot 文档分析请求")

    try:
        from graphrag_agent.ai_copilot import DocumentAnalyzer
        from graphrag_agent.config.settings import CHUNK_SIZE, FILES_DIR, OVERLAP
        from graphrag_agent.models.get_models import get_embeddings_model, get_llm_model
        from graphrag_agent.pipelines.ingestion.document_processor import DocumentProcessor

        # 初始化模型
        llm = get_llm_model()
        embeddings = get_embeddings_model()

        # 创建文档分析器
        analyzer = DocumentAnalyzer(llm, embeddings)

        # 读取文档
        doc_processor = DocumentProcessor(FILES_DIR, CHUNK_SIZE, OVERLAP)
        results, summary = doc_processor.process_directory()  # 🔥 正确解包元组

        if not results:
            logger.warning("没有找到可分析的文档")
            raise HTTPException(status_code=400, detail="没有找到可分析的文档，请先上传文档")

        # 准备文档数据（使用 results，而不是 processed_docs）
        documents = [{"filename": doc["filename"], "content": doc["content"]} for doc in results]

        logger.info(f"开始分析 {len(documents)} 个文档")

        # 分析文档
        analysis_result = analyzer.analyze_documents(documents, num_clusters)

        logger.info(f"文档分析完成，聚类数: {len(analysis_result['clusters'])}")

        # 生成推荐
        logger.info("开始生成配置推荐")
        recommendations = analyzer.recommend_domains_and_bridges(analysis_result, industry_hint)

        logger.info("配置推荐生成完成")

        return {"analysis": analysis_result, "recommendations": recommendations}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI Copilot 分析失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文档分析失败: {str(e)}")


@router.post("/ai-copilot/refine-config")
async def refine_configuration(user_feedback: str, current_config: Optional[Dict] = None):
    """
    基于用户反馈优化配置

    Args:
        user_feedback: 用户反馈
        current_config: 当前配置（可选，如果为空则从存储加载）

    Returns:
        优化后的配置
    """
    logger.info("收到 AI Copilot 配置优化请求")

    try:
        from graphrag_agent.ai_copilot import DocumentAnalyzer
        from graphrag_agent.models.get_models import get_embeddings_model, get_llm_model

        # 初始化模型
        llm = get_llm_model()
        embeddings = get_embeddings_model()

        # 创建文档分析器
        analyzer = DocumentAnalyzer(llm, embeddings)

        # 获取当前配置
        if current_config is None:
            storage = get_storage()
            config_obj = storage.load()
            if config_obj is None:
                raise HTTPException(status_code=400, detail="当前无配置，请先创建配置")
            current_config = config_obj.model_dump(mode="json")

        logger.info(f"开始优化配置，用户反馈: {user_feedback[:100]}...")

        # 优化配置
        refined_config = analyzer.refine_recommendations(current_config, user_feedback)

        logger.info("配置优化完成")

        return refined_config

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI Copilot 配置优化失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"配置优化失败: {str(e)}")


@router.post("/ai-copilot/apply-recommendations")
async def apply_ai_recommendations(
    recommendations: Dict, project_name: str, industry: Optional[str] = None, description: Optional[str] = None
):
    """
    将 AI 推荐应用为新配置

    Args:
        recommendations: AI 推荐结果
        project_name: 项目名称
        industry: 行业
        description: 项目描述

    Returns:
        创建的配置
    """
    logger.info(f"收到应用 AI 推荐请求: {project_name}")

    try:
        # 构建配置
        config_dict = {
            "project_name": project_name,
            "version": "1.0",
            "description": description or "基于 AI 推荐创建",
            "industry": industry or "通用",
            "bridge_definitions": recommendations.get("recommended_bridges", []),
            "domain_definitions": recommendations.get("recommended_domains", []),
        }

        # 验证并保存
        config = GraphConfig(**config_dict)
        storage = get_storage()
        success = storage.save(config)

        if success:
            logger.info(f"AI 推荐配置已保存: {project_name}")
            return {"message": "配置创建成功", "config": config.model_dump(mode="json")}
        else:
            raise HTTPException(status_code=500, detail="配置保存失败")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"应用 AI 推荐失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"应用推荐失败: {str(e)}")
