from fastapi import APIRouter

from . import (
    admin,
    build,
    cache_metrics,
    chat,
    feedback,
    feedback_admin,
    graph,
    graph_visualization,
    knowledge_graph,
    models,
    source,
    stats,
    status,
    templates,
)

# 创建总路由器
api_router = APIRouter()

# 包含各个子路由器
api_router.include_router(chat.router, tags=["聊天"])
api_router.include_router(feedback.router, tags=["反馈"])
api_router.include_router(feedback_admin.router, tags=["反馈管理"])
api_router.include_router(knowledge_graph.router, tags=["知识图谱"])
api_router.include_router(source.router, tags=["源内容"])
api_router.include_router(admin.router, tags=["管理"])
api_router.include_router(build.router, tags=["图谱构建"])
api_router.include_router(graph.router, tags=["图谱探索"])
api_router.include_router(graph_visualization.router, tags=["图谱可视化"])
api_router.include_router(cache_metrics.router, tags=["缓存监控"])
api_router.include_router(status.router, tags=["系统状态"])
api_router.include_router(stats.router, tags=["统计监控"])
api_router.include_router(templates.router, tags=["模板市场"])
api_router.include_router(models.router, tags=["模型管理"])

__all__ = ["api_router"]
