"""
Prometheus 指标模块

提供应用性能指标收集和暴露。
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 延迟导入 prometheus_client（可选依赖）
try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest, REGISTRY

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning(
        "prometheus_client not installed. Install with: pip install prometheus-client\n"
        "Prometheus metrics will be disabled."
    )


# =========================
# 缓存相关指标
# =========================

if PROMETHEUS_AVAILABLE:
    # 缓存命中计数器
    cache_hits_total = Counter(
        "cache_hits_total",
        "Total number of cache hits",
        ["cache_type"],  # exact, vector, miss
    )

    # 缓存操作耗时
    cache_operation_duration = Histogram(
        "cache_operation_duration_seconds",
        "Cache operation duration in seconds",
        ["operation"],  # get, set, delete
        buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
    )

    # 缓存大小
    cache_size_items = Gauge(
        "cache_size_items",
        "Current number of items in cache",
        ["cache_type"],  # memory, disk
    )

    # =========================
    # 查询相关指标
    # =========================

    # 查询处理耗时
    query_duration_seconds = Histogram(
        "query_duration_seconds",
        "Query processing duration in seconds",
        ["agent_type"],  # naive, graph, hybrid, deep_research
        buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
    )

    # 查询计数
    query_total = Counter(
        "query_total",
        "Total number of queries processed",
        ["agent_type", "status"],  # status: success, error
    )

    # 当前活跃查询数
    active_queries = Gauge(
        "active_queries",
        "Number of currently active queries",
        ["agent_type"],
    )

    # =========================
    # 图数据库相关指标
    # =========================

    # Neo4j 写入操作
    neo4j_write_operations_total = Counter(
        "neo4j_write_operations_total",
        "Total number of Neo4j write operations",
        ["operation_type", "status"],  # operation_type: single, batch; status: success, failure
    )

    # Neo4j 写入耗时
    neo4j_write_duration_seconds = Histogram(
        "neo4j_write_duration_seconds",
        "Neo4j write operation duration",
        ["operation_type"],
        buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
    )

    # Neo4j 活跃连接数
    neo4j_connections_active = Gauge(
        "neo4j_connections_active",
        "Number of active Neo4j connections",
    )

    # Neo4j 批次写入失败率
    neo4j_batch_failure_rate = Gauge(
        "neo4j_batch_failure_rate",
        "Neo4j batch write failure rate (0.0-1.0)",
    )

    # =========================
    # LLM 调用相关指标
    # =========================

    # LLM 调用计数
    llm_calls_total = Counter(
        "llm_calls_total",
        "Total number of LLM API calls",
        ["model", "status"],  # status: success, error, timeout
    )

    # LLM 调用耗时
    llm_call_duration_seconds = Histogram(
        "llm_call_duration_seconds",
        "LLM API call duration",
        ["model"],
        buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0],
    )

    # LLM token 使用量
    llm_tokens_used = Counter(
        "llm_tokens_used_total",
        "Total tokens consumed by LLM",
        ["model", "token_type"],  # token_type: prompt, completion
    )


# =========================
# 辅助函数
# =========================


def record_cache_hit(cache_type: str):
    """记录缓存命中"""
    if PROMETHEUS_AVAILABLE:
        cache_hits_total.labels(cache_type=cache_type).inc()


def record_cache_operation(operation: str, duration: float):
    """记录缓存操作"""
    if PROMETHEUS_AVAILABLE:
        cache_operation_duration.labels(operation=operation).observe(duration)


def set_cache_size(cache_type: str, size: int):
    """设置缓存大小"""
    if PROMETHEUS_AVAILABLE:
        cache_size_items.labels(cache_type=cache_type).set(size)


def record_query(agent_type: str, duration: float, status: str = "success"):
    """记录查询"""
    if PROMETHEUS_AVAILABLE:
        query_duration_seconds.labels(agent_type=agent_type).observe(duration)
        query_total.labels(agent_type=agent_type, status=status).inc()


def increment_active_queries(agent_type: str, delta: int = 1):
    """增加活跃查询数"""
    if PROMETHEUS_AVAILABLE:
        active_queries.labels(agent_type=agent_type).inc(delta)


def decrement_active_queries(agent_type: str, delta: int = 1):
    """减少活跃查询数"""
    if PROMETHEUS_AVAILABLE:
        active_queries.labels(agent_type=agent_type).dec(delta)


def record_neo4j_write(operation_type: str, duration: float, status: str = "success"):
    """记录 Neo4j 写入操作"""
    if PROMETHEUS_AVAILABLE:
        neo4j_write_operations_total.labels(operation_type=operation_type, status=status).inc()
        neo4j_write_duration_seconds.labels(operation_type=operation_type).observe(duration)


def set_neo4j_connections(count: int):
    """设置 Neo4j 连接数"""
    if PROMETHEUS_AVAILABLE:
        neo4j_connections_active.set(count)


def set_neo4j_batch_failure_rate(rate: float):
    """设置 Neo4j 批次失败率"""
    if PROMETHEUS_AVAILABLE:
        neo4j_batch_failure_rate.set(rate)


def record_llm_call(model: str, duration: float, status: str = "success"):
    """记录 LLM 调用"""
    if PROMETHEUS_AVAILABLE:
        llm_calls_total.labels(model=model, status=status).inc()
        llm_call_duration_seconds.labels(model=model).observe(duration)


def record_llm_tokens(model: str, prompt_tokens: int, completion_tokens: int):
    """记录 LLM token 使用"""
    if PROMETHEUS_AVAILABLE:
        llm_tokens_used.labels(model=model, token_type="prompt").inc(prompt_tokens)
        llm_tokens_used.labels(model=model, token_type="completion").inc(completion_tokens)


def get_metrics() -> bytes:
    """
    获取 Prometheus 格式的指标数据

    Returns:
        bytes: Prometheus 文本格式的指标

    Example:
        >>> # 在 FastAPI 中暴露 /metrics 端点
        >>> from fastapi import Response
        >>> from graphrag_agent.utils.metrics import get_metrics
        >>>
        >>> @app.get("/metrics")
        >>> def metrics():
        ...     return Response(content=get_metrics(), media_type="text/plain")
    """
    if not PROMETHEUS_AVAILABLE:
        return b"# Prometheus client not available\n"

    return generate_latest(REGISTRY)


# =========================
# 上下文管理器（用于自动计时）
# =========================


class MetricsTimer:
    """指标计时器上下文管理器"""

    def __init__(self, metric_func, *args, **kwargs):
        """
        Args:
            metric_func: 指标记录函数（如 record_query）
            *args, **kwargs: 传递给指标函数的参数
        """
        self.metric_func = metric_func
        self.args = args
        self.kwargs = kwargs
        self.start_time = None

    def __enter__(self):
        import time

        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        import time

        duration = time.time() - self.start_time

        # 如果发生异常，标记为错误
        if exc_type is not None:
            self.kwargs["status"] = "error"

        self.metric_func(*self.args, duration=duration, **self.kwargs)
        return False  # 不抑制异常


# =========================
# 使用示例
# =========================


def example_usage():
    """使用示例"""

    # 1. 记录缓存操作
    record_cache_hit("exact")
    record_cache_hit("vector")
    record_cache_operation("get", 0.005)

    # 2. 记录查询（使用上下文管理器）
    with MetricsTimer(record_query, "naive_rag"):
        # 执行查询
        pass

    # 3. 记录 Neo4j 写入
    record_neo4j_write("batch", 1.2, status="success")

    # 4. 记录 LLM 调用
    record_llm_call("gpt-4o", 2.5, status="success")
    record_llm_tokens("gpt-4o", prompt_tokens=100, completion_tokens=50)

    # 5. 获取指标（用于 /metrics 端点）
    metrics_data = get_metrics()
    print(metrics_data.decode("utf-8"))
