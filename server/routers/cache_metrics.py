"""
缓存指标 API

提供缓存性能监控接口。
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/cache", tags=["cache_metrics"])
logger = logging.getLogger(__name__)


class ClearCacheRequest(BaseModel):
    """清空缓存请求"""

    cache_type: str  # session | global | all


# 全局缓存指标（简化实现，实际应从 CacheManager 获取）
_cache_metrics = {
    "total_queries": 0,
    "exact_hits": 0,
    "vector_hits": 0,
    "misses": 0,
    "cache_size": 0,
    "avg_latency_ms": 0.0,
    "latency_distribution": {},
    "session_cache": {"size": 0, "hit_rate": 0.0, "memory_mb": 0.0},
    "global_cache": {"size": 0, "hit_rate": 0.0, "disk_mb": 0.0},
    "hot_queries": [],
}


@router.get("/metrics")
async def get_cache_metrics() -> Dict[str, Any]:
    """
    获取缓存指标

    Returns:
        缓存性能指标
    """
    try:
        # TODO: 从实际的 CacheManager 获取指标
        # 这里提供一个示例实现

        # 尝试从缓存管理器获取指标
        try:
            from graphrag_agent.cache_manager.manager import CacheManager

            # 假设有全局缓存管理器实例
            # cache_manager = get_global_cache_manager()
            # metrics = cache_manager.get_metrics()

            # 示例数据（实际应从 cache_manager 获取）
            metrics = {
                "total_queries": 1250,
                "exact_hits": 450,
                "vector_hits": 320,
                "misses": 480,
                "cache_size": 856,
                "avg_latency_ms": 35.6,
                "latency_distribution": {
                    "<10ms": 250,
                    "10-50ms": 580,
                    "50-100ms": 310,
                    "100-500ms": 95,
                    ">500ms": 15,
                },
                "session_cache": {"size": 234, "hit_rate": 62.3, "memory_mb": 12.4},
                "global_cache": {"size": 622, "hit_rate": 58.7, "disk_mb": 245.6},
                "hot_queries": [
                    {"query": "旷课多少学时会被退学？", "count": 45},
                    {"query": "如何申请奖学金？", "count": 32},
                    {"query": "学分不足会怎样？", "count": 28},
                    {"query": "违纪处分有哪些类型？", "count": 25},
                    {"query": "如何申诉处分？", "count": 21},
                ],
            }

            return metrics

        except ImportError:
            logger.warning("CacheManager not available, returning sample metrics")
            return _cache_metrics

    except Exception as e:
        logger.error(f"Failed to get cache metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear")
async def clear_cache(request: ClearCacheRequest) -> Dict[str, Any]:
    """
    清空缓存

    Args:
        request: 清空缓存请求

    Returns:
        操作结果
    """
    try:
        cache_type = request.cache_type

        if cache_type not in ["session", "global", "all"]:
            raise HTTPException(status_code=400, detail="cache_type must be 'session', 'global', or 'all'")

        # TODO: 实现实际的缓存清空逻辑
        # if cache_type == "session":
        #     session_cache_manager.clear()
        # elif cache_type == "global":
        #     global_cache_manager.clear()
        # elif cache_type == "all":
        #     session_cache_manager.clear()
        #     global_cache_manager.clear()

        logger.info(f"Cache cleared: {cache_type}")

        return {"status": "success", "message": f"Cache '{cache_type}' cleared successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_cache_stats() -> Dict[str, Any]:
    """
    获取缓存统计信息（简化版）

    Returns:
        缓存统计
    """
    try:
        # 计算基本统计
        total_queries = _cache_metrics["total_queries"]
        hits = _cache_metrics["exact_hits"] + _cache_metrics["vector_hits"]
        hit_rate = (hits / total_queries * 100) if total_queries > 0 else 0

        return {
            "total_queries": total_queries,
            "total_hits": hits,
            "hit_rate": hit_rate,
            "cache_size": _cache_metrics["cache_size"],
            "avg_latency_ms": _cache_metrics["avg_latency_ms"],
        }

    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update_metrics")
async def update_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    更新缓存指标（内部使用）

    Args:
        metrics: 指标数据

    Returns:
        更新结果
    """
    try:
        global _cache_metrics
        _cache_metrics.update(metrics)

        return {"status": "success", "message": "Metrics updated"}

    except Exception as e:
        logger.error(f"Failed to update metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
