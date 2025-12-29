"""
错误监控和追踪模块

提供 Sentry 集成，带有数据脱敏功能。
"""

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def init_sentry(
    dsn: Optional[str] = None,
    environment: Optional[str] = None,
    traces_sample_rate: float = 0.1,
    enable_logging: bool = True,
):
    """
    初始化 Sentry 错误追踪

    Args:
        dsn: Sentry DSN（如果为 None，从环境变量读取）
        environment: 环境名称（development, staging, production）
        traces_sample_rate: 性能追踪采样率（0.0-1.0，默认10%以降低成本）
        enable_logging: 是否集成日志系统

    Example:
        >>> # 在应用启动时调用
        >>> from graphrag_agent.utils.monitoring import init_sentry
        >>> init_sentry()
    """
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        logger.warning(
            "sentry-sdk not installed. Install with: pip install sentry-sdk\n"
            "Sentry monitoring will be disabled."
        )
        return

    # 从环境变量获取配置
    sentry_dsn = dsn or os.getenv("SENTRY_DSN")
    if not sentry_dsn:
        logger.info("SENTRY_DSN not configured, Sentry monitoring disabled")
        return

    env = environment or os.getenv("ENV", "development")

    # 配置日志集成
    integrations = []
    if enable_logging:
        integrations.append(
            LoggingIntegration(
                level=logging.INFO,  # 捕获 INFO 级别以上的日志
                event_level=logging.ERROR,  # 只将 ERROR 发送到 Sentry
            )
        )

    # 初始化 Sentry
    sentry_sdk.init(
        dsn=sentry_dsn,
        environment=env,
        traces_sample_rate=traces_sample_rate,
        before_send=_before_send_handler,
        integrations=integrations,
        # 发送默认的 PII（个人可识别信息）
        send_default_pii=False,
        # 附加诊断信息
        attach_stacktrace=True,
    )

    logger.info(f"Sentry initialized for environment: {env}")


def _before_send_handler(event: Dict[str, Any], hint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Sentry 事件发送前的处理钩子（数据脱敏）

    Args:
        event: Sentry 事件数据
        hint: 提示信息（包含原始异常）

    Returns:
        处理后的事件，或 None（丢弃事件）
    """
    # 移除敏感的 HTTP 头
    if "request" in event:
        headers = event["request"].get("headers", {})

        # 移除认证信息
        sensitive_headers = ["Authorization", "Cookie", "X-API-Key", "X-Auth-Token"]
        for header in sensitive_headers:
            headers.pop(header, None)

        # 脱敏环境变量（如果有）
        if "env" in event["request"]:
            env = event["request"]["env"]
            for key in list(env.keys()):
                if any(keyword in key.upper() for keyword in ["KEY", "SECRET", "TOKEN", "PASSWORD"]):
                    env[key] = "***REDACTED***"

    # 脱敏用户输入和查询
    if "extra" in event:
        extra = event["extra"]
        sensitive_fields = ["query", "user_input", "question", "password", "api_key"]

        for field in sensitive_fields:
            if field in extra:
                value = extra[field]
                if isinstance(value, str) and len(value) > 50:
                    # 只保留前50个字符
                    extra[field] = value[:50] + "...[TRUNCATED]"
                elif field in ["password", "api_key"]:
                    # 完全隐藏密钥
                    extra[field] = "***REDACTED***"

    # 脱敏异常消息中的敏感信息
    if "exception" in event:
        values = event["exception"].get("values", [])
        for exc_value in values:
            if "value" in exc_value:
                message = exc_value["value"]
                # 移除可能包含的 API 密钥模式（sk-xxx）
                if "sk-" in message:
                    exc_value["value"] = message.replace("sk-", "sk-***")

    return event


def capture_exception(exception: Exception, extra: Optional[Dict[str, Any]] = None):
    """
    捕获异常并发送到 Sentry

    Args:
        exception: 异常对象
        extra: 附加的上下文信息

    Example:
        >>> try:
        ...     risky_operation()
        ... except Exception as e:
        ...     capture_exception(e, extra={"query": user_query})
        ...     raise
    """
    try:
        import sentry_sdk

        if extra:
            with sentry_sdk.push_scope() as scope:
                for key, value in extra.items():
                    scope.set_extra(key, value)
                sentry_sdk.capture_exception(exception)
        else:
            sentry_sdk.capture_exception(exception)

    except ImportError:
        # sentry_sdk 未安装，静默失败
        pass


def capture_message(message: str, level: str = "info", extra: Optional[Dict[str, Any]] = None):
    """
    捕获自定义消息并发送到 Sentry

    Args:
        message: 消息内容
        level: 日志级别（debug, info, warning, error, fatal）
        extra: 附加的上下文信息

    Example:
        >>> capture_message("User completed onboarding", level="info", extra={"user_id": 123})
    """
    try:
        import sentry_sdk

        if extra:
            with sentry_sdk.push_scope() as scope:
                for key, value in extra.items():
                    scope.set_extra(key, value)
                sentry_sdk.capture_message(message, level=level)
        else:
            sentry_sdk.capture_message(message, level=level)

    except ImportError:
        pass


def set_user_context(user_id: Optional[str] = None, username: Optional[str] = None, **kwargs):
    """
    设置用户上下文信息

    Args:
        user_id: 用户 ID
        username: 用户名
        **kwargs: 其他用户属性

    Example:
        >>> set_user_context(user_id="12345", username="alice", plan="premium")
    """
    try:
        import sentry_sdk

        user_data = {}
        if user_id:
            user_data["id"] = user_id
        if username:
            user_data["username"] = username
        user_data.update(kwargs)

        sentry_sdk.set_user(user_data)

    except ImportError:
        pass


def add_breadcrumb(message: str, category: str = "default", level: str = "info", data: Optional[Dict] = None):
    """
    添加面包屑（用于追踪事件序列）

    Args:
        message: 面包屑消息
        category: 分类（如 "query", "cache", "database"）
        level: 级别
        data: 附加数据

    Example:
        >>> add_breadcrumb("User submitted query", category="query", data={"query_length": 50})
    """
    try:
        import sentry_sdk

        sentry_sdk.add_breadcrumb(message=message, category=category, level=level, data=data or {})

    except ImportError:
        pass
