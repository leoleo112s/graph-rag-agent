"""
日志配置工具模块

提供标准化的日志初始化功能，支持文件日志轮转和格式化输出。
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from graphrag_agent.config.settings import LOG_BACKUP_COUNT, LOG_FILE, LOG_FORMAT, LOG_LEVEL, LOG_MAX_SIZE_MB


def init_logging(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
    log_format: Optional[str] = None,
    app_name: str = "graphrag",
):
    """
    初始化日志系统

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件路径，None 则不写入文件
        log_format: 日志格式 (text 或 json)
        app_name: 应用名称，用于日志标识
    """
    # 使用配置文件的默认值
    level = level or LOG_LEVEL
    log_file = log_file or LOG_FILE
    log_format = log_format or LOG_FORMAT

    # 解析日志级别
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # 配置日志格式
    if log_format == "json":
        # JSON 格式（便于日志聚合工具解析）
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
            '"name": "%(name)s", "file": "%(filename)s", "line": %(lineno)d, '
            '"message": "%(message)s"}',
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    else:
        # 文本格式（易读）
        formatter = logging.Formatter(
            f"%(asctime)s [{app_name}] [%(levelname)s] %(name)s:%(lineno)d - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

    # 配置处理器
    handlers = []

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    # 文件输出（带轮转）
    if log_file:
        try:
            # 确保日志目录存在
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            # 创建轮转文件处理器
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=LOG_MAX_SIZE_MB * 1024 * 1024,  # 转换为字节
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            handlers.append(file_handler)
        except Exception as e:
            # 如果文件日志创建失败，只输出到控制台
            print(f"Warning: 无法创建日志文件 {log_file}: {e}", file=sys.stderr)

    # 配置根日志器
    logging.basicConfig(level=numeric_level, handlers=handlers, force=True)  # 强制重新配置（覆盖之前的配置）

    # 降低第三方库的日志级别（减少噪音）
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    # 记录初始化完成
    logger = logging.getLogger(__name__)
    logger.info(
        f"日志系统初始化完成: level={level}, format={log_format}, " f"file={log_file if log_file else 'console-only'}"
    )


def get_logger(name: str) -> logging.Logger:
    """
    获取日志器实例

    Args:
        name: 日志器名称，通常使用 __name__

    Returns:
        配置好的日志器实例
    """
    return logging.getLogger(name)
