"""
Redis 状态存储工具

用途：
- 替代内存单例 (ProgressManager/ProgressBroadcaster)
- 支持多 Worker 进程状态同步
- 提供 TTL 自动清理
- 支持 Pub/Sub 实时通知

使用方法：
    from server.utils.redis_state import RedisStateManager

    # 初始化
    state_mgr = RedisStateManager()

    # 更新进度
    state_mgr.set_build_progress("task_id_123", {
        "percent": 50,
        "stage": "entity_extraction",
        "details": "正在抽取实体..."
    })

    # 获取进度
    progress = state_mgr.get_build_progress("task_id_123")

    # 订阅进度更新（用于 WebSocket）
    async for message in state_mgr.subscribe_progress("task_id_123"):
        await websocket.send_json(message)
"""

import os
import json
import redis
import asyncio
from typing import Dict, Any, Optional, AsyncIterator
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


class RedisStateManager:
    """
    Redis 状态管理器

    功能：
    - 进度状态存储（替代内存单例）
    - Pub/Sub 实时通知
    - TTL 自动过期
    - 原子操作保证一致性
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        db: Optional[int] = None,
        password: Optional[str] = None,
    ):
        """
        初始化 Redis 连接

        Args:
            host: Redis 主机地址（默认从环境变量读取）
            port: Redis 端口（默认从环境变量读取）
            db: Redis 数据库编号（默认从环境变量读取）
            password: Redis 密码（默认从环境变量读取）
        """
        self.host = host or os.getenv("REDIS_HOST", "localhost")
        self.port = port or int(os.getenv("REDIS_PORT", 6379))
        self.db = db or int(os.getenv("REDIS_DB", 0))
        self.password = password or os.getenv("REDIS_PASSWORD", None)

        # 同步 Redis 客户端（用于状态存储）
        self.redis_client = redis.Redis(
            host=self.host,
            port=self.port,
            db=self.db,
            password=self.password,
            decode_responses=True,  # 自动解码为字符串
            socket_timeout=5,
            socket_connect_timeout=5,
        )

        # 测试连接
        try:
            self.redis_client.ping()
            logger.info(f"Redis 连接成功: {self.host}:{self.port}")
        except redis.ConnectionError as e:
            logger.error(f"Redis 连接失败: {e}")
            raise

    # ========================================================================
    # 进度状态管理
    # ========================================================================

    def set_build_progress(
        self,
        task_id: str,
        progress: Dict[str, Any],
        ttl: int = 86400,  # 默认保留 1 天
    ) -> bool:
        """
        设置构建进度

        Args:
            task_id: 任务 ID
            progress: 进度数据（字典）
            ttl: 过期时间（秒）

        Returns:
            是否设置成功
        """
        key = f"build:progress:{task_id}"
        try:
            # 存储 JSON 数据
            self.redis_client.setex(
                key,
                ttl,
                json.dumps(progress, ensure_ascii=False)
            )

            # 发布通知（用于 Pub/Sub）
            self.redis_client.publish(
                f"build:progress:channel:{task_id}",
                json.dumps(progress, ensure_ascii=False)
            )

            logger.debug(f"进度更新: {task_id} -> {progress.get('percent', 0)}%")
            return True

        except Exception as e:
            logger.error(f"设置进度失败: {e}")
            return False

    def get_build_progress(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取构建进度

        Args:
            task_id: 任务 ID

        Returns:
            进度数据（字典），如果不存在返回 None
        """
        key = f"build:progress:{task_id}"
        try:
            data = self.redis_client.get(key)
            if data:
                return json.loads(data)
            return None

        except Exception as e:
            logger.error(f"获取进度失败: {e}")
            return None

    def delete_build_progress(self, task_id: str) -> bool:
        """
        删除构建进度

        Args:
            task_id: 任务 ID

        Returns:
            是否删除成功
        """
        key = f"build:progress:{task_id}"
        try:
            self.redis_client.delete(key)
            return True
        except Exception as e:
            logger.error(f"删除进度失败: {e}")
            return False

    # ========================================================================
    # Pub/Sub 订阅（用于 WebSocket 推送）
    # ========================================================================

    async def subscribe_progress(
        self,
        task_id: str,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        订阅构建进度更新（异步生成器）

        Args:
            task_id: 任务 ID
            timeout: 超时时间（秒），None 表示永不超时

        Yields:
            进度数据（字典）

        Example:
            async for progress in state_mgr.subscribe_progress("task_123"):
                await websocket.send_json(progress)
        """
        # 创建异步 Redis 客户端（用于 Pub/Sub）
        import redis.asyncio as aioredis

        redis_async = await aioredis.from_url(
            f"redis://{self.host}:{self.port}/{self.db}",
            password=self.password,
            decode_responses=True,
        )

        pubsub = redis_async.pubsub()
        channel = f"build:progress:channel:{task_id}"

        try:
            await pubsub.subscribe(channel)
            logger.info(f"订阅进度频道: {channel}")

            # 首先发送当前状态（如果存在）
            current_progress = self.get_build_progress(task_id)
            if current_progress:
                yield current_progress

            # 监听新消息
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        yield data

                        # 如果进度为 100%，可以自动退出
                        if data.get("percent") >= 100:
                            logger.info(f"任务完成，取消订阅: {task_id}")
                            break

                    except json.JSONDecodeError:
                        logger.warning(f"无效的 JSON 消息: {message['data']}")

        except asyncio.TimeoutError:
            logger.info(f"订阅超时: {task_id}")

        finally:
            await pubsub.unsubscribe(channel)
            await redis_async.close()
            logger.info(f"取消订阅: {channel}")

    # ========================================================================
    # 任务状态管理
    # ========================================================================

    def set_task_status(
        self,
        task_id: str,
        status: str,  # pending, running, success, failed
        result: Optional[Any] = None,
        error: Optional[str] = None,
        ttl: int = 86400,
    ) -> bool:
        """
        设置任务状态

        Args:
            task_id: 任务 ID
            status: 任务状态
            result: 任务结果（可选）
            error: 错误信息（可选）
            ttl: 过期时间（秒）

        Returns:
            是否设置成功
        """
        key = f"build:task_status:{task_id}"
        data = {
            "status": status,
            "result": result,
            "error": error,
        }

        try:
            self.redis_client.setex(
                key,
                ttl,
                json.dumps(data, ensure_ascii=False, default=str)
            )
            return True
        except Exception as e:
            logger.error(f"设置任务状态失败: {e}")
            return False

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务状态

        Args:
            task_id: 任务 ID

        Returns:
            任务状态数据，如果不存在返回 None
        """
        key = f"build:task_status:{task_id}"
        try:
            data = self.redis_client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"获取任务状态失败: {e}")
            return None

    # ========================================================================
    # 分布式锁（防止重复构建）
    # ========================================================================

    def acquire_build_lock(self, resource: str, ttl: int = 3600) -> bool:
        """
        获取构建锁（防止并发构建）

        Args:
            resource: 资源名称（如 "full_build", "incremental_build"）
            ttl: 锁超时时间（秒）

        Returns:
            是否获取成功
        """
        key = f"build:lock:{resource}"
        return self.redis_client.set(key, "locked", ex=ttl, nx=True) is not None

    def release_build_lock(self, resource: str) -> bool:
        """
        释放构建锁

        Args:
            resource: 资源名称

        Returns:
            是否释放成功
        """
        key = f"build:lock:{resource}"
        return self.redis_client.delete(key) > 0


# ============================================================================
# 全局单例（向后兼容，但实际状态存储在 Redis 中）
# ============================================================================

_state_manager = None


def get_state_manager() -> RedisStateManager:
    """
    获取全局 Redis 状态管理器（单例）

    Returns:
        RedisStateManager 实例
    """
    global _state_manager
    if _state_manager is None:
        _state_manager = RedisStateManager()
    return _state_manager
