"""
统一构建锁管理器

用途：
- 提供统一的分布式锁接口，解决多模块（build.py, admin.py）锁隔离问题
- 支持多进程部署场景（Gunicorn workers）
- 基于 Redis 实现分布式锁，确保全局唯一性

架构：
- 优先使用 Redis 分布式锁（生产环境）
- 降级使用内存锁（开发环境，Redis 不可用时）

使用方法：
    from server.utils.build_lock import get_build_lock_manager

    lock_mgr = get_build_lock_manager()

    # 获取锁
    if lock_mgr.acquire(resource="graph_build", ttl=3600):
        try:
            # 执行构建任务
            ...
        finally:
            lock_mgr.release("graph_build")
    else:
        # 锁已被占用
        return {"error": "已有构建任务正在运行"}
"""

import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional

# 全局锁管理器实例
_lock_manager: Optional["BuildLockManager"] = None


class BuildLockManager:
    """
    统一构建锁管理器

    支持两种模式：
    1. Redis 模式（生产环境，多进程安全）
    2. 内存模式（开发环境，单进程）
    """

    def __init__(self, use_redis: bool = True):
        """
        初始化锁管理器

        Args:
            use_redis: 是否使用 Redis（默认 True，降级到内存锁）
        """
        self.use_redis = use_redis
        self.redis_client = None
        self.memory_locks = {}  # 内存锁备用
        self.memory_lock = asyncio.Lock()  # 保护 memory_locks 的锁

        if use_redis:
            try:
                from server.utils.redis_state import get_redis_state_manager

                self.redis_mgr = get_redis_state_manager()
                self.redis_client = self.redis_mgr.redis_client
                print("✅ BuildLockManager 使用 Redis 分布式锁")
            except Exception as e:
                print(f"⚠️ Redis 连接失败，降级到内存锁: {e}")
                self.use_redis = False
                print("✅ BuildLockManager 使用内存锁（仅限单进程）")
        else:
            print("✅ BuildLockManager 使用内存锁（开发模式）")

    def acquire(self, resource: str, ttl: int = 3600) -> bool:
        """
        获取构建锁（同步版本）

        Args:
            resource: 资源标识（如 "graph_build", "index_build"）
            ttl: 锁的有效期（秒），默认 1 小时

        Returns:
            bool: 是否成功获取锁
        """
        if self.use_redis and self.redis_client:
            # Redis 分布式锁
            try:
                from server.utils.redis_state import get_redis_state_manager

                redis_mgr = get_redis_state_manager()
                return redis_mgr.acquire_build_lock(resource, ttl)
            except Exception as e:
                print(f"⚠️ Redis 锁获取失败，降级到内存锁: {e}")
                return self._acquire_memory_lock(resource, ttl)
        else:
            # 内存锁（仅限单进程）
            return self._acquire_memory_lock(resource, ttl)

    async def acquire_async(self, resource: str, ttl: int = 3600) -> bool:
        """
        获取构建锁（异步版本）

        Args:
            resource: 资源标识
            ttl: 锁的有效期（秒）

        Returns:
            bool: 是否成功获取锁
        """
        if self.use_redis and self.redis_client:
            # Redis 分布式锁（在线程池中执行）
            try:
                return await asyncio.to_thread(self.acquire, resource, ttl)
            except Exception as e:
                print(f"⚠️ Redis 异步锁获取失败: {e}")
                return await self._acquire_memory_lock_async(resource, ttl)
        else:
            # 内存锁
            return await self._acquire_memory_lock_async(resource, ttl)

    def release(self, resource: str) -> bool:
        """
        释放构建锁（同步版本）

        Args:
            resource: 资源标识

        Returns:
            bool: 是否成功释放
        """
        if self.use_redis and self.redis_client:
            # Redis 分布式锁
            try:
                from server.utils.redis_state import get_redis_state_manager

                redis_mgr = get_redis_state_manager()
                return redis_mgr.release_build_lock(resource)
            except Exception as e:
                print(f"⚠️ Redis 锁释放失败: {e}")
                return self._release_memory_lock(resource)
        else:
            # 内存锁
            return self._release_memory_lock(resource)

    async def release_async(self, resource: str) -> bool:
        """
        释放构建锁（异步版本）

        Args:
            resource: 资源标识

        Returns:
            bool: 是否成功释放
        """
        if self.use_redis and self.redis_client:
            # Redis 分布式锁
            try:
                return await asyncio.to_thread(self.release, resource)
            except Exception as e:
                print(f"⚠️ Redis 异步锁释放失败: {e}")
                return await self._release_memory_lock_async(resource)
        else:
            # 内存锁
            return await self._release_memory_lock_async(resource)

    def is_locked(self, resource: str) -> bool:
        """
        检查资源是否被锁定

        Args:
            resource: 资源标识

        Returns:
            bool: 是否被锁定
        """
        if self.use_redis and self.redis_client:
            # Redis 锁检查
            try:
                lock_key = f"build:lock:{resource}"
                return self.redis_client.exists(lock_key) > 0
            except:
                return self._is_memory_locked(resource)
        else:
            # 内存锁检查
            return self._is_memory_locked(resource)

    # ========== 内存锁辅助方法 ==========

    def _acquire_memory_lock(self, resource: str, ttl: int) -> bool:
        """同步获取内存锁"""
        now = datetime.now()

        # 检查是否已过期
        if resource in self.memory_locks:
            expiry = self.memory_locks[resource]
            if now < expiry:
                return False  # 锁未过期，获取失败
            else:
                # 锁已过期，清理
                del self.memory_locks[resource]

        # 设置锁
        self.memory_locks[resource] = now + timedelta(seconds=ttl)
        return True

    async def _acquire_memory_lock_async(self, resource: str, ttl: int) -> bool:
        """异步获取内存锁"""
        async with self.memory_lock:
            return self._acquire_memory_lock(resource, ttl)

    def _release_memory_lock(self, resource: str) -> bool:
        """同步释放内存锁"""
        if resource in self.memory_locks:
            del self.memory_locks[resource]
            return True
        return False

    async def _release_memory_lock_async(self, resource: str) -> bool:
        """异步释放内存锁"""
        async with self.memory_lock:
            return self._release_memory_lock(resource)

    def _is_memory_locked(self, resource: str) -> bool:
        """检查内存锁"""
        if resource not in self.memory_locks:
            return False

        # 检查是否过期
        now = datetime.now()
        expiry = self.memory_locks[resource]
        if now >= expiry:
            # 已过期，清理
            del self.memory_locks[resource]
            return False

        return True


def get_build_lock_manager(use_redis: Optional[bool] = None) -> BuildLockManager:
    """
    获取全局构建锁管理器单例

    Args:
        use_redis: 是否使用 Redis（None 则自动检测）

    Returns:
        BuildLockManager: 锁管理器实例
    """
    global _lock_manager

    if _lock_manager is None:
        # 自动检测 Redis 可用性
        if use_redis is None:
            # 检查环境变量
            redis_host = os.getenv("REDIS_HOST")
            use_redis = redis_host is not None

        _lock_manager = BuildLockManager(use_redis=use_redis)

    return _lock_manager


# 便捷函数
def acquire_build_lock(resource: str = "graph_build", ttl: int = 3600) -> bool:
    """
    便捷函数：获取构建锁

    Args:
        resource: 资源标识，默认 "graph_build"
        ttl: 锁的有效期（秒）

    Returns:
        bool: 是否成功获取锁
    """
    return get_build_lock_manager().acquire(resource, ttl)


def release_build_lock(resource: str = "graph_build") -> bool:
    """
    便捷函数：释放构建锁

    Args:
        resource: 资源标识

    Returns:
        bool: 是否成功释放
    """
    return get_build_lock_manager().release(resource)


def is_build_locked(resource: str = "graph_build") -> bool:
    """
    便捷函数：检查是否被锁定

    Args:
        resource: 资源标识

    Returns:
        bool: 是否被锁定
    """
    return get_build_lock_manager().is_locked(resource)
