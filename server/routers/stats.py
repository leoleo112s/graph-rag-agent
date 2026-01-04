"""
统计与监控 API

提供构建任务和问答查询的统计与性能监控数据。
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from server.models.build_history import get_build_history_db
from server.models.query_log import get_query_log_db

router = APIRouter(prefix="/admin/stats", tags=["statistics"])
logger = logging.getLogger(__name__)


@router.get("/build")
async def get_build_statistics(
    start_time: Optional[str] = None, end_time: Optional[str] = None, task_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取构建任务统计信息

    Args:
        start_time: 开始时间（ISO格式，可选）
        end_time: 结束时间（ISO格式，可选）
        task_type: 任务类型过滤 (full/incremental)

    Returns:
        构建统计数据
    """
    try:
        db = get_build_history_db()

        # 获取基础统计
        stats = db.get_statistics()

        # 如果没有指定时间范围，默认最近7天
        if not start_time:
            start_time = (datetime.now() - timedelta(days=7)).isoformat()

        # 获取所有记录用于额外统计
        records = db.list_records(limit=1000, offset=0, status=None, task_type=task_type)  # 所有状态

        # 过滤时间范围
        filtered_records = []
        for record in records:
            record_time = datetime.fromisoformat(record.start_time)
            if start_time and record_time < datetime.fromisoformat(start_time):
                continue
            if end_time and record_time > datetime.fromisoformat(end_time):
                continue
            filtered_records.append(record)

        # 计算额外统计
        total_builds = len(filtered_records)
        successful_builds = sum(1 for r in filtered_records if r.status == "completed")
        failed_builds = sum(1 for r in filtered_records if r.status == "failed")

        # 平均耗时（仅统计完成的任务）
        durations = [r.duration for r in filtered_records if r.duration and r.status == "completed"]
        avg_duration = sum(durations) / len(durations) if durations else 0

        # chunk 和 node 统计
        total_chunks = 0
        total_nodes = 0
        for record in filtered_records:
            if record.stats:
                total_chunks += record.stats.get("chunk_count", 0)
                total_nodes += record.stats.get("entity_count", 0)

        avg_chunks = total_chunks / total_builds if total_builds > 0 else 0
        avg_nodes = total_nodes / total_builds if total_builds > 0 else 0

        # 按日期聚合
        daily_stats = {}
        for record in filtered_records:
            date = record.start_time.split("T")[0]
            if date not in daily_stats:
                daily_stats[date] = {"total": 0, "successful": 0, "failed": 0, "avg_duration": []}

            daily_stats[date]["total"] += 1
            if record.status == "completed":
                daily_stats[date]["successful"] += 1
                if record.duration:
                    daily_stats[date]["avg_duration"].append(record.duration)
            elif record.status == "failed":
                daily_stats[date]["failed"] += 1

        # 计算每日平均耗时
        for date, day_stats in daily_stats.items():
            durations = day_stats["avg_duration"]
            day_stats["avg_duration"] = sum(durations) / len(durations) if durations else 0
            day_stats["success_rate"] = (
                (day_stats["successful"] / day_stats["total"] * 100) if day_stats["total"] > 0 else 0
            )

        # 按类型统计
        type_stats = {}
        for record in filtered_records:
            task_type = record.task_type
            if task_type not in type_stats:
                type_stats[task_type] = 0
            type_stats[task_type] += 1

        return {
            "total_builds": total_builds,
            "successful_builds": successful_builds,
            "failed_builds": failed_builds,
            "success_rate": round((successful_builds / total_builds * 100) if total_builds > 0 else 0, 2),
            "avg_duration_seconds": round(avg_duration, 2),
            "avg_chunks_per_build": round(avg_chunks, 2),
            "avg_nodes_per_build": round(avg_nodes, 2),
            "total_chunks": total_chunks,
            "total_nodes": total_nodes,
            "daily_stats": daily_stats,
            "type_distribution": type_stats,
            "time_range": {"start": start_time, "end": end_time or datetime.now().isoformat()},
        }

    except Exception as e:
        logger.error(f"Failed to get build statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qa")
async def get_qa_statistics(
    start_time: Optional[str] = None, end_time: Optional[str] = None, agent_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取问答查询统计信息

    Args:
        start_time: 开始时间（ISO格式，可选）
        end_time: 结束时间（ISO格式，可选）
        agent_type: 代理类型过滤

    Returns:
        问答统计数据
    """
    try:
        db = get_query_log_db()

        # 如果没有指定时间范围，默认最近7天
        if not start_time:
            start_time = (datetime.now() - timedelta(days=7)).isoformat()

        # 获取统计
        stats = db.get_statistics(start_time=start_time, end_time=end_time, agent_type=agent_type)

        return stats

    except Exception as e:
        logger.error(f"Failed to get QA statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qa/timeseries")
async def get_qa_timeseries(
    metric: str = Query("response_time", description="Metric name: response_time, search_time, llm_time"),
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    interval: str = Query("hour", description="Time interval: hour, day, week"),
    agent_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    获取问答指标时间序列数据

    Args:
        metric: 指标名称 (response_time, search_time, llm_time)
        start_time: 开始时间
        end_time: 结束时间
        interval: 时间间隔 (hour, day, week)
        agent_type: 代理类型过滤

    Returns:
        时间序列数据
    """
    try:
        db = get_query_log_db()

        # 如果没有指定时间范围，默认最近7天
        if not start_time:
            start_time = (datetime.now() - timedelta(days=7)).isoformat()

        time_series = db.get_time_series(
            metric=metric, start_time=start_time, end_time=end_time, interval=interval, agent_type=agent_type
        )

        return time_series

    except Exception as e:
        logger.error(f"Failed to get QA time series: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overview")
async def get_system_overview() -> Dict[str, Any]:
    """
    获取系统总览统计

    Returns:
        系统总览数据
    """
    try:
        build_db = get_build_history_db()
        query_db = get_query_log_db()

        # 最近7天的数据
        start_time = (datetime.now() - timedelta(days=7)).isoformat()

        # 构建统计
        build_stats = build_db.get_statistics()

        # 问答统计
        qa_stats = query_db.get_statistics(start_time=start_time)

        return {
            "build": {
                "total_builds": build_stats.get("total_builds", 0),
                "success_rate": build_stats.get("success_rate", 0),
                "avg_duration": build_stats.get("avg_duration_minutes", 0),
            },
            "qa": {
                "total_queries": qa_stats.get("total_queries", 0),
                "avg_response_time": qa_stats.get("avg_response_time", 0),
                "cache_hit_rate": qa_stats.get("cache_hit_rate", 0),
                "positive_feedback_rate": qa_stats.get("positive_feedback_rate", 0),
            },
            "time_range": {"start": start_time, "end": datetime.now().isoformat()},
        }

    except Exception as e:
        logger.error(f"Failed to get system overview: {e}")
        raise HTTPException(status_code=500, detail=str(e))
