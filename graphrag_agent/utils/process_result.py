"""
并行处理结果模型

提供标准化的并行处理返回结构，支持成功/失败状态跟踪和异常信息。
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ProcessResult:
    """
    并行处理的结果封装

    Attributes:
        success: 处理是否成功
        data: 处理结果数据（成功时有效）
        error: 异常对象（失败时有效）
        index: 原始输入列表中的索引位置
        error_type: 错误类型（用于分类：transient/database/unknown）
    """
    success: bool
    data: Any = None
    error: Optional[Exception] = None
    index: int = -1
    error_type: str = "unknown"  # transient | database | unknown

    @classmethod
    def success_result(cls, data: Any, index: int = -1) -> "ProcessResult":
        """创建成功结果"""
        return cls(success=True, data=data, index=index)

    @classmethod
    def failure_result(
        cls,
        error: Exception,
        index: int = -1,
        error_type: str = "unknown"
    ) -> "ProcessResult":
        """创建失败结果"""
        return cls(
            success=False,
            error=error,
            index=index,
            error_type=error_type
        )
