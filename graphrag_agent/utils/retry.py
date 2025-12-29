"""
重试装饰器模块

提供统一的重试和指数退避策略，用于处理临时性失败。
"""

import time
import logging
from typing import Callable, TypeVar, Tuple, Type
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_with_backoff(
    max_retries: int = 3,
    backoff_factor: float = 0.5,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Callable[[Exception, int], None] = None,
):
    """
    重试装饰器，支持指数退避

    在遇到临时性错误时自动重试，每次重试之间的等待时间呈指数增长。

    Args:
        max_retries: 最大重试次数（默认3次）
        backoff_factor: 退避因子，等待时间 = backoff_factor * (2 ** retry_count)（默认0.5）
        exceptions: 需要重试的异常类型元组（默认所有异常）
        on_retry: 重试时的回调函数，接收 (exception, retry_count) 参数

    Returns:
        装饰器函数

    Example:
        >>> @retry_with_backoff(max_retries=3, backoff_factor=1.0)
        ... def unstable_api_call():
        ...     # 可能失败的操作
        ...     return api.call()

        >>> @retry_with_backoff(
        ...     max_retries=5,
        ...     exceptions=(ConnectionError, TimeoutError),
        ...     on_retry=lambda e, count: print(f"Retry {count}: {e}")
        ... )
        ... def network_request():
        ...     return requests.get("https://api.example.com")
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries - 1:
                        # 最后一次重试失败，记录错误并抛出
                        logger.error(
                            f"{func.__name__} failed after {max_retries} retries: {e}",
                            exc_info=True,
                        )
                        raise

                    # 计算等待时间（指数退避）
                    wait_time = backoff_factor * (2**attempt)

                    # 记录警告
                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1}/{max_retries} failed, "
                        f"retrying in {wait_time:.2f}s: {e}"
                    )

                    # 调用重试回调
                    if on_retry:
                        try:
                            on_retry(e, attempt + 1)
                        except Exception as callback_error:
                            logger.error(f"Error in retry callback: {callback_error}")

                    # 等待后重试
                    time.sleep(wait_time)

            # 不应该到达这里，但为了类型检查完整性
            if last_exception:
                raise last_exception

        return wrapper

    return decorator


def async_retry_with_backoff(
    max_retries: int = 3,
    backoff_factor: float = 0.5,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Callable[[Exception, int], None] = None,
):
    """
    异步重试装饰器，支持指数退避

    用法与 retry_with_backoff 相同，但支持异步函数。

    Args:
        max_retries: 最大重试次数
        backoff_factor: 退避因子
        exceptions: 需要重试的异常类型元组
        on_retry: 重试时的回调函数

    Example:
        >>> @async_retry_with_backoff(max_retries=3)
        ... async def async_api_call():
        ...     async with aiohttp.ClientSession() as session:
        ...         return await session.get("https://api.example.com")
    """
    import asyncio

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries - 1:
                        logger.error(
                            f"{func.__name__} failed after {max_retries} retries: {e}",
                            exc_info=True,
                        )
                        raise

                    wait_time = backoff_factor * (2**attempt)

                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1}/{max_retries} failed, "
                        f"retrying in {wait_time:.2f}s: {e}"
                    )

                    if on_retry:
                        try:
                            on_retry(e, attempt + 1)
                        except Exception as callback_error:
                            logger.error(f"Error in retry callback: {callback_error}")

                    await asyncio.sleep(wait_time)

            if last_exception:
                raise last_exception

        return wrapper

    return decorator
