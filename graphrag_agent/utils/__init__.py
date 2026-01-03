"""工具模块"""

from .retry import async_retry_with_backoff, retry_with_backoff

# 可选导入（如果依赖包未安装不会失败）
try:
    from .monitoring import (
        add_breadcrumb,
        capture_exception,
        capture_message,
        init_sentry,
        set_user_context,
    )

    __all__ = [
        "retry_with_backoff",
        "async_retry_with_backoff",
        "init_sentry",
        "capture_exception",
        "capture_message",
        "set_user_context",
        "add_breadcrumb",
    ]
except ImportError:
    __all__ = ["retry_with_backoff", "async_retry_with_backoff"]

try:
    from .metrics import (
        get_metrics,
        record_cache_hit,
        record_cache_operation,
        record_llm_call,
        record_neo4j_write,
        record_query,
    )

    __all__ += [
        "get_metrics",
        "record_cache_hit",
        "record_cache_operation",
        "record_query",
        "record_neo4j_write",
        "record_llm_call",
    ]
except ImportError:
    pass
