"""
Celery 配置文件

用途：
- 配置 Celery 应用（任务队列）
- 配置 Redis 作为 Broker 和 Result Backend
- 配置任务路由、重试策略、超时等

使用方法：
    # 启动 Celery Worker
    celery -A server.celery_app worker --loglevel=info

    # 启动 Flower (Web 监控界面)
    celery -A server.celery_app flower --port=5555
"""

import os
from celery import Celery
from kombu import Exchange, Queue

# ============================================================================
# Redis 配置
# ============================================================================

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

# 构建 Redis URL
if REDIS_PASSWORD:
    BROKER_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
else:
    BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

RESULT_BACKEND = BROKER_URL


# ============================================================================
# Celery 应用配置
# ============================================================================

app = Celery(
    "graphrag_tasks",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["server.tasks.build_tasks"]  # 自动发现任务模块
)

# Celery 配置
app.conf.update(
    # 任务结果过期时间（秒）- 1天
    result_expires=86400,

    # 任务序列化格式（推荐 json，避免 pickle 安全风险）
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,

    # 任务结果存储在 Redis 中（便于查询任务状态）
    result_backend_transport_options={
        "master_name": "mymaster",  # 如果使用 Redis Sentinel
    },

    # 任务优先级（允许设置优先级队列）
    task_acks_late=True,  # 任务执行完成后再 ACK
    worker_prefetch_multiplier=1,  # Worker 一次只拉取一个任务

    # 任务超时（防止任务卡死）
    task_soft_time_limit=3600,  # 1 小时软限制（会抛出异常）
    task_time_limit=3900,  # 1 小时 5 分钟硬限制（强制终止）

    # 任务重试配置
    task_autoretry_for=(Exception,),  # 哪些异常触发重试
    task_retry_kwargs={"max_retries": 3, "countdown": 60},  # 最多重试3次，间隔60秒

    # Worker 配置
    worker_max_tasks_per_child=50,  # Worker 执行50个任务后重启（防止内存泄漏）
    worker_disable_rate_limits=False,  # 启用速率限制

    # 日志格式
    worker_log_format="[%(asctime)s: %(levelname)s/%(processName)s] %(message)s",
    worker_task_log_format="[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s",
)


# ============================================================================
# 任务路由配置（可选）
# ============================================================================

# 定义交换机和队列
app.conf.task_queues = (
    # 默认队列（普通任务）
    Queue("default", Exchange("default"), routing_key="default"),

    # 高优先级队列（紧急任务）
    Queue("high_priority", Exchange("high_priority"), routing_key="high_priority"),

    # 低优先级队列（批量任务）
    Queue("low_priority", Exchange("low_priority"), routing_key="low_priority"),

    # 构建任务专用队列（GraphRAG 构建）
    Queue("build", Exchange("build"), routing_key="build"),
)

# 任务路由规则
app.conf.task_routes = {
    # 构建任务 -> build 队列
    "server.tasks.build_tasks.build_graph_task": {"queue": "build"},
    "server.tasks.build_tasks.incremental_build_task": {"queue": "build"},

    # 其他任务 -> 默认队列
    "*": {"queue": "default"},
}


# ============================================================================
# 定时任务配置（可选）
# ============================================================================

from celery.schedules import crontab

app.conf.beat_schedule = {
    # 每天凌晨 2 点清理过期任务结果
    "cleanup-expired-results": {
        "task": "server.tasks.maintenance_tasks.cleanup_expired_results",
        "schedule": crontab(hour=2, minute=0),
    },

    # 每小时检查图谱一致性（可选）
    "check-graph-consistency": {
        "task": "server.tasks.maintenance_tasks.check_graph_consistency",
        "schedule": crontab(minute=0),
    },
}


# ============================================================================
# 任务钩子（可选）
# ============================================================================

@app.task(bind=True)
def debug_task(self):
    """调试任务，用于测试 Celery 是否正常工作"""
    print(f"Request: {self.request!r}")
    return "Celery is working!"
