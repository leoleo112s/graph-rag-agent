"""
结构化日志工具 (Structured Logging Utility)

用途：
- 替代项目中的 print() 和 console.print()
- 提供统一的日志格式（包含时间戳、日志级别、request_id 等上下文）
- 支持 JSON 格式输出，便于 ELK 等日志系统采集
- 支持文件轮转，避免日志文件过大

使用方法：
    from server.utils.logger import get_logger

    logger = get_logger(__name__)
    logger.info("用户登录成功", extra={"user_id": "123", "ip": "192.168.1.1"})
    logger.error("数据库连接失败", extra={"error_code": 5202})
"""

import logging
import json
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any
from datetime import datetime
import traceback


class JSONFormatter(logging.Formatter):
    """
    JSON 格式化器

    将日志输出为 JSON 格式，便于机器解析和 ELK 采集
    """

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为 JSON"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 添加额外的上下文字段（request_id, user_id 等）
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "session_id"):
            log_data["session_id"] = record.session_id

        # 添加其他 extra 字段
        for key, value in record.__dict__.items():
            if key not in [
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "pathname", "process", "processName", "relativeCreated",
                "thread", "threadName", "exc_info", "exc_text", "stack_info",
                "request_id", "user_id", "session_id"
            ]:
                log_data[key] = value

        # 如果有异常信息，添加堆栈追踪
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": "".join(traceback.format_exception(*record.exc_info))
            }

        return json.dumps(log_data, ensure_ascii=False)


class ColoredConsoleFormatter(logging.Formatter):
    """
    彩色控制台格式化器

    在开发环境提供可读性更好的日志输出
    """

    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[35m',   # 紫色
        'RESET': '\033[0m'
    }

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为彩色文本"""
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset = self.COLORS['RESET']

        # 基础信息
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
        level = f"{color}{record.levelname:8s}{reset}"
        message = record.getMessage()

        # 构建日志行
        log_line = f"{timestamp} | {level} | {record.name:30s} | {message}"

        # 添加 request_id（如果存在）
        if hasattr(record, "request_id"):
            log_line += f" | request_id={record.request_id}"

        # 添加异常信息
        if record.exc_info:
            log_line += "\n" + "".join(traceback.format_exception(*record.exc_info))

        return log_line


class StructuredLogger:
    """
    结构化日志器

    提供便捷的日志记录方法，自动添加上下文信息
    """

    def __init__(self, logger: logging.Logger):
        self._logger = logger
        self._context: Dict[str, Any] = {}

    def set_context(self, **kwargs):
        """
        设置上下文信息

        Args:
            **kwargs: 上下文键值对（request_id, user_id, session_id 等）

        Example:
            logger.set_context(request_id="abc123", user_id="user_456")
        """
        self._context.update(kwargs)

    def clear_context(self):
        """清除上下文信息"""
        self._context.clear()

    def _log(self, level: int, msg: str, **kwargs):
        """内部日志方法，自动添加上下文"""
        extra = {**self._context, **kwargs}
        self._logger.log(level, msg, extra=extra)

    def debug(self, msg: str, **kwargs):
        """记录 DEBUG 级别日志"""
        self._log(logging.DEBUG, msg, **kwargs)

    def info(self, msg: str, **kwargs):
        """记录 INFO 级别日志"""
        self._log(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        """记录 WARNING 级别日志"""
        self._log(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, exc_info=None, **kwargs):
        """记录 ERROR 级别日志"""
        self._logger.error(msg, exc_info=exc_info, extra={**self._context, **kwargs})

    def critical(self, msg: str, exc_info=None, **kwargs):
        """记录 CRITICAL 级别日志"""
        self._logger.critical(msg, exc_info=exc_info, extra={**self._context, **kwargs})


# ============================================================================
# 日志配置
# ============================================================================

def setup_logging(
    log_level: str = "INFO",
    log_dir: Optional[Path] = None,
    use_json: bool = False,
    max_bytes: int = 100 * 1024 * 1024,  # 100 MB
    backup_count: int = 5
):
    """
    配置全局日志系统

    Args:
        log_level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
        log_dir: 日志文件目录（None 表示不写文件）
        use_json: 是否使用 JSON 格式（生产环境推荐）
        max_bytes: 单个日志文件最大字节数
        backup_count: 保留的日志文件备份数量

    Example:
        # 开发环境
        setup_logging(log_level="DEBUG", use_json=False)

        # 生产环境
        setup_logging(
            log_level="INFO",
            log_dir=Path("logs"),
            use_json=True,
            max_bytes=500 * 1024 * 1024  # 500 MB
        )
    """
    # 设置根日志级别
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # 清除已有的 handlers
    root_logger.handlers.clear()

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    if use_json:
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(ColoredConsoleFormatter())
    root_logger.addHandler(console_handler)

    # 文件输出（如果指定）
    if log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # 应用日志（JSON 格式）
        app_log_file = log_dir / "app.log"
        app_handler = RotatingFileHandler(
            app_log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        app_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(app_handler)

        # 错误日志（单独文件，方便快速定位）
        error_log_file = log_dir / "error.log"
        error_handler = RotatingFileHandler(
            error_log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(error_handler)


def get_logger(name: str) -> StructuredLogger:
    """
    获取结构化日志器

    Args:
        name: 日志器名称（通常使用 __name__）

    Returns:
        StructuredLogger 实例

    Example:
        logger = get_logger(__name__)
        logger.info("服务启动", port=8000)
        logger.error("连接失败", exc_info=True, db_host="localhost")
    """
    return StructuredLogger(logging.getLogger(name))


# ============================================================================
# 日志上下文管理器
# ============================================================================

class LogContext:
    """
    日志上下文管理器

    用于在特定代码块中自动添加上下文信息

    Example:
        with LogContext(request_id="abc123", user_id="user_456"):
            logger.info("处理请求")  # 自动包含 request_id 和 user_id
    """

    def __init__(self, **context):
        self.context = context
        self.logger = get_logger(__name__)

    def __enter__(self):
        self.logger.set_context(**self.context)
        return self.logger

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logger.clear_context()
