"""
索引状态检查工具

用途：
- 在聊天服务入口处检查向量索引是否就绪
- 提供优雅降级（返回友好提示而非直接报错）
- 支持构建进度查询
"""

import logging
from enum import Enum
from typing import Dict, Literal, Optional

from graphrag_agent.graph.core import connection_manager
from server.utils.build_lock import get_build_lock_manager
from server.utils.progress_manager import get_progress_manager

_LOGGER = logging.getLogger(__name__)


class IndexStatus(str, Enum):
    """索引状态枚举"""

    READY = "ready"  # 就绪：索引存在且无构建任务
    BUILDING = "building"  # 构建中：索引可能不完整，有构建任务正在运行
    EMPTY = "empty"  # 空：索引不存在且无构建任务
    ERROR = "error"  # 错误：检查失败


def check_vector_index_exists(index_name: str) -> bool:
    """
    检查向量索引是否存在

    Args:
        index_name: 索引名称（如 "chunk_embedding_index", "entity_embedding_index"）

    Returns:
        bool: 索引是否存在
    """
    try:
        query = """
        SHOW INDEXES
        YIELD name, type
        WHERE name = $index_name AND type = 'VECTOR'
        RETURN count(*) as count
        """
        result = connection_manager.execute_query(query, {"index_name": index_name})

        if result and len(result) > 0:
            count = result[0].get("count", 0)
            return count > 0

        return False
    except Exception as e:
        _LOGGER.error(f"检查索引失败: {index_name}, 错误: {e}")
        return False


def check_index_has_data(label: str) -> bool:
    """
    检查索引是否有数据（节点是否存在）

    Args:
        label: 节点标签（如 "__Chunk__", "__Entity__"）

    Returns:
        bool: 是否有数据
    """
    try:
        query = f"MATCH (n:{label}) RETURN count(n) as count LIMIT 1"
        result = connection_manager.execute_query(query)

        if result and len(result) > 0:
            count = result[0].get("count", 0)
            return count > 0

        return False
    except Exception as e:
        _LOGGER.error(f"检查节点数据失败: {label}, 错误: {e}")
        return False


def get_index_status() -> Dict:
    """
    获取索引状态（聊天服务使用）

    返回格式：
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
    """
    try:
        # 1. 检查是否有构建任务正在运行
        lock_manager = get_build_lock_manager()
        is_building = lock_manager.is_locked("graph_build")

        # 2. 检查索引是否存在
        chunk_index_exists = check_vector_index_exists("chunk_embedding_index")
        entity_index_exists = check_vector_index_exists("entity_embedding_index")

        # 3. 检查是否有数据
        chunk_data_exists = check_index_has_data("__Chunk__")
        entity_data_exists = check_index_has_data("__Entity__")

        # 4. 构建详情对象
        details = {
            "chunk_index_exists": chunk_index_exists,
            "entity_index_exists": entity_index_exists,
            "chunk_data_exists": chunk_data_exists,
            "entity_data_exists": entity_data_exists,
            "is_building": is_building,
        }

        # 5. 判断总体状态
        # 优先级: building > empty > ready
        if is_building:
            # 构建中
            progress_mgr = get_progress_manager()
            progress = progress_mgr.get_current_status()

            details["build_progress"] = {
                "percent": progress.get("percent", 0),
                "stage": progress.get("stage", "unknown"),
                "details": progress.get("details", "构建中..."),
            }

            return {
                "status": IndexStatus.BUILDING,
                "message": "知识图谱正在构建中，请稍候...",
                "details": details,
                "retry_after": 10,  # 建议 10 秒后重试
            }

        elif not (chunk_index_exists or entity_index_exists) or not (chunk_data_exists or entity_data_exists):
            # 索引不存在或无数据
            return {
                "status": IndexStatus.EMPTY,
                "message": (
                    "知识图谱尚未构建，请先完成以下步骤：\n"
                    "1. 进入「📚 文档管理」上传文档\n"
                    "2. 进入「🏗️ 构建管理」点击「全量构建」\n"
                    "3. 等待构建完成后再进行查询\n\n"
                    "注意：首次构建可能需要几分钟时间，具体取决于文档数量。"
                ),
                "details": details,
            }

        else:
            # 索引就绪
            return {"status": IndexStatus.READY, "message": "索引就绪，可以查询", "details": details}

    except Exception as e:
        _LOGGER.exception(f"获取索引状态失败: {e}")
        return {"status": IndexStatus.ERROR, "message": f"检查索引状态时出错: {str(e)}", "details": {"error": str(e)}}
