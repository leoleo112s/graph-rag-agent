"""
重试装饰器单元测试
"""

import pytest

from graphrag_agent.utils.retry import async_retry_with_backoff, retry_with_backoff


@pytest.mark.unit
class TestRetryDecorator:
    """重试装饰器功能测试"""

    def test_success_on_first_attempt(self):
        """第一次尝试就成功"""
        call_count = 0

        @retry_with_backoff(max_retries=3, backoff_factor=0.01)
        def always_success():
            nonlocal call_count
            call_count += 1
            return "success"

        result = always_success()
        assert result == "success"
        assert call_count == 1

    def test_success_after_failures(self):
        """重试后成功"""
        call_count = 0

        @retry_with_backoff(max_retries=3, backoff_factor=0.01)
        def fail_twice_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary error")
            return "success"

        result = fail_twice_then_success()
        assert result == "success"
        assert call_count == 3

    def test_retry_exhausted(self):
        """重试次数用尽后抛出异常"""
        call_count = 0

        @retry_with_backoff(max_retries=3, backoff_factor=0.01)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("Permanent error")

        with pytest.raises(ValueError, match="Permanent error"):
            always_fail()

        # 应该尝试3次
        assert call_count == 3

    def test_custom_exceptions(self):
        """只重试特定异常类型"""
        call_count = 0

        @retry_with_backoff(max_retries=3, backoff_factor=0.01, exceptions=(ValueError,))
        def raise_wrong_exception():
            nonlocal call_count
            call_count += 1
            raise TypeError("Not retryable")

        # 遇到非指定异常应立即失败
        with pytest.raises(TypeError):
            raise_wrong_exception()

        assert call_count == 1  # 只尝试一次

    def test_on_retry_callback(self):
        """测试重试回调"""
        retry_events = []

        def on_retry(exception, retry_count):
            retry_events.append((str(exception), retry_count))

        call_count = 0

        @retry_with_backoff(max_retries=3, backoff_factor=0.01, on_retry=on_retry)
        def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError(f"Attempt {call_count}")
            return "success"

        result = fail_twice()
        assert result == "success"
        assert len(retry_events) == 2  # 失败两次才成功
        assert retry_events[0][1] == 1  # 第一次重试
        assert retry_events[1][1] == 2  # 第二次重试

    def test_backoff_timing(self):
        """测试指数退避时间（简单验证）"""
        import time

        call_times = []

        @retry_with_backoff(max_retries=3, backoff_factor=0.1)
        def fail_with_timing():
            call_times.append(time.time())
            if len(call_times) < 3:
                raise ValueError("Retry")
            return "success"

        fail_with_timing()

        # 验证至少有三次调用
        assert len(call_times) == 3

        # 验证有等待时间（第二次调用应该比第一次晚）
        assert call_times[1] > call_times[0]
        assert call_times[2] > call_times[1]


@pytest.mark.unit
@pytest.mark.asyncio
class TestAsyncRetryDecorator:
    """异步重试装饰器测试"""

    async def test_async_success_on_first_attempt(self):
        """异步：第一次尝试就成功"""
        call_count = 0

        @async_retry_with_backoff(max_retries=3, backoff_factor=0.01)
        async def async_always_success():
            nonlocal call_count
            call_count += 1
            return "async_success"

        result = await async_always_success()
        assert result == "async_success"
        assert call_count == 1

    async def test_async_success_after_failures(self):
        """异步：重试后成功"""
        call_count = 0

        @async_retry_with_backoff(max_retries=3, backoff_factor=0.01)
        async def async_fail_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Temporary async error")
            return "async_success"

        result = await async_fail_then_success()
        assert result == "async_success"
        assert call_count == 2

    async def test_async_retry_exhausted(self):
        """异步：重试次数用尽"""
        call_count = 0

        @async_retry_with_backoff(max_retries=3, backoff_factor=0.01)
        async def async_always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("Permanent async error")

        with pytest.raises(ValueError, match="Permanent async error"):
            await async_always_fail()

        assert call_count == 3
