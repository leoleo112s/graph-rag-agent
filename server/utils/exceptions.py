"""
自定义异常类 (Custom Exception Classes)

用途：
- 定义业务异常，区分系统异常和业务异常
- 统一异常处理逻辑
- 提供详细的错误信息和错误码

使用方法：
    from server.utils.exceptions import BusinessException, ResourceNotFoundError
    from server.models.schemas import ErrorCode

    # 抛出业务异常
    raise ResourceNotFoundError("实体不存在", entity_id="entity_123")

    # 在 router 中直接抛出，全局异常处理器会捕获
    if not entity:
        raise ResourceNotFoundError(f"实体 {entity_id} 不存在")
"""

from typing import Any, Dict, Optional

from server.models.schemas import ErrorCode


class BusinessException(Exception):
    """
    业务异常基类

    业务异常不同于系统异常（如 ValueError, ConnectionError）：
    - 业务异常是预期的、可恢复的（如"资源未找到"）
    - 系统异常是非预期的、需要修复的（如"数据库连接失败"）

    Attributes:
        code: 业务错误码（来自 ErrorCode 类）
        message: 错误消息
        details: 额外的错误详情（可选）
    """

    def __init__(self, message: str, code: int = ErrorCode.SERVER_ERROR, details: Optional[Dict[str, Any]] = None):
        """
        初始化业务异常

        Args:
            message: 错误消息
            code: 错误码（默认 500）
            details: 额外的错误详情字典
        """
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 API 响应）"""
        result = {"code": self.code, "message": self.message}
        if self.details:
            result["details"] = self.details
        return result


# ============================================================================
# 客户端错误异常 (4xx)
# ============================================================================


class ValidationError(BusinessException):
    """参数验证错误"""

    def __init__(self, message: str, **details):
        super().__init__(message=message, code=ErrorCode.PARAM_ERROR, details=details)


class UnauthorizedError(BusinessException):
    """未授权错误"""

    def __init__(self, message: str = "未授权访问", **details):
        super().__init__(message=message, code=ErrorCode.UNAUTHORIZED, details=details)


class ResourceNotFoundError(BusinessException):
    """资源未找到错误"""

    def __init__(self, message: str, **details):
        super().__init__(message=message, code=ErrorCode.NOT_FOUND, details=details)


class ResourceConflictError(BusinessException):
    """资源冲突错误（如重复创建）"""

    def __init__(self, message: str, **details):
        super().__init__(message=message, code=ErrorCode.CONFLICT, details=details)


# ============================================================================
# LLM 相关错误 (51xx)
# ============================================================================


class LLMError(BusinessException):
    """LLM 通用错误"""

    def __init__(self, message: str, **details):
        super().__init__(message=message, code=ErrorCode.LLM_ERROR, details=details)


class LLMTimeoutError(BusinessException):
    """LLM 请求超时"""

    def __init__(self, message: str = "LLM 请求超时，请稍后重试", **details):
        super().__init__(message=message, code=ErrorCode.LLM_TIMEOUT, details=details)


class LLMTokenLimitError(BusinessException):
    """LLM Token 超限"""

    def __init__(self, message: str = "输入内容过长，请缩短后重试", **details):
        super().__init__(message=message, code=ErrorCode.LLM_TOKEN_LIMIT, details=details)


class LLMParseError(BusinessException):
    """LLM 输出解析失败"""

    def __init__(self, message: str = "LLM 输出格式错误，解析失败", **details):
        super().__init__(message=message, code=ErrorCode.LLM_PARSE_ERROR, details=details)


# ============================================================================
# 数据库相关错误 (52xx)
# ============================================================================


class DatabaseError(BusinessException):
    """数据库通用错误"""

    def __init__(self, message: str, **details):
        super().__init__(message=message, code=ErrorCode.DB_ERROR, details=details)


class DatabaseConnectionError(BusinessException):
    """数据库连接失败"""

    def __init__(self, message: str = "数据库连接失败，请稍后重试", **details):
        super().__init__(message=message, code=ErrorCode.DB_CONNECTION_ERROR, details=details)


class DatabaseQueryError(BusinessException):
    """数据库查询失败"""

    def __init__(self, message: str, **details):
        super().__init__(message=message, code=ErrorCode.DB_QUERY_ERROR, details=details)


# ============================================================================
# 缓存相关错误 (53xx)
# ============================================================================


class CacheError(BusinessException):
    """缓存通用错误"""

    def __init__(self, message: str, **details):
        super().__init__(message=message, code=ErrorCode.CACHE_ERROR, details=details)


# ============================================================================
# 文件系统相关错误 (54xx)
# ============================================================================


class FileError(BusinessException):
    """文件系统通用错误"""

    def __init__(self, message: str, **details):
        super().__init__(message=message, code=ErrorCode.FILE_ERROR, details=details)


class FileNotFoundError(BusinessException):
    """文件未找到"""

    def __init__(self, message: str, **details):
        super().__init__(message=message, code=ErrorCode.FILE_NOT_FOUND, details=details)


class FileReadError(BusinessException):
    """文件读取失败"""

    def __init__(self, message: str, **details):
        super().__init__(message=message, code=ErrorCode.FILE_READ_ERROR, details=details)


# ============================================================================
# 实体抽取相关错误 (55xx)
# ============================================================================


class ExtractionError(BusinessException):
    """实体抽取通用错误"""

    def __init__(self, message: str, **details):
        super().__init__(message=message, code=ErrorCode.EXTRACTION_ERROR, details=details)


class ExtractionTimeoutError(BusinessException):
    """实体抽取超时"""

    def __init__(self, message: str = "实体抽取超时，请稍后重试", **details):
        super().__init__(message=message, code=ErrorCode.EXTRACTION_TIMEOUT, details=details)


class ExtractionEmptyError(BusinessException):
    """未抽取到任何实体"""

    def __init__(self, message: str = "未抽取到任何实体或关系", **details):
        super().__init__(message=message, code=ErrorCode.EXTRACTION_EMPTY, details=details)
