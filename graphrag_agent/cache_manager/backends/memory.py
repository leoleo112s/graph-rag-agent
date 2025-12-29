import time
from typing import Any, Optional, Tuple

from .base import CacheStorageBackend


class MemoryCacheBackend(CacheStorageBackend):
    """
    内存缓存后端实现

    ✅ 改进：支持 TTL（Time To Live）过期策略 + LRU 淘汰策略

    特性：
    - TTL 过期：每个缓存项可设置过期时间
    - LRU 淘汰：缓存满时淘汰最久未使用的项
    - 惰性删除：在 get() 时检查过期并删除
    - 主动清理：定期清理过期项（可选）
    """

    def __init__(self, max_size: int = 1000, default_ttl: int = 3600):
        """
        初始化内存缓存后端

        参数:
            max_size: 缓存最大项数（默认1000）
            default_ttl: 默认过期时间（秒，默认3600=1小时）
        """
        self.cache = {}  # 存储: {key: (value, expiration_time)}
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.access_times = {}  # 用于LRU淘汰策略

    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存项

        ✅ 改进：检查 TTL 过期时间，过期则删除并返回 None

        参数:
            key: 缓存键

        返回:
            Optional[Any]: 缓存项值，不存在或已过期则返回None
        """
        item = self.cache.get(key)
        if item is None:
            return None

        value, expiration_time = item

        # ✅ TTL 过期检查（惰性删除）
        if time.time() > expiration_time:
            # 过期，删除缓存项
            del self.cache[key]
            if key in self.access_times:
                del self.access_times[key]
            return None

        # 更新访问时间（LRU策略）
        self.access_times[key] = time.time()
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        设置缓存项

        ✅ 改进：支持 TTL 参数，存储过期时间

        参数:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），None 则使用 default_ttl
        """
        # 计算过期时间
        ttl = ttl if ttl is not None else self.default_ttl
        expiration_time = time.time() + ttl

        # 如果缓存已满，删除最久未使用的项
        if len(self.cache) >= self.max_size and key not in self.cache:
            self._evict_lru()

        # 存储 (value, expiration_time) 元组
        self.cache[key] = (value, expiration_time)
        self.access_times[key] = time.time()

    def delete(self, key: str) -> bool:
        """
        删除缓存项

        参数:
            key: 缓存键

        返回:
            bool: 是否成功删除
        """
        if key in self.cache:
            del self.cache[key]
            if key in self.access_times:
                del self.access_times[key]
            return True
        return False

    def clear(self) -> None:
        """清空缓存"""
        self.cache.clear()
        self.access_times.clear()  # 确保同时清空访问时间字典

    def _evict_lru(self) -> None:
        """
        淘汰最久未使用的缓存项（LRU 策略）
        """
        if not self.access_times:
            return

        # 找出最旧的项
        oldest_key = min(self.access_times.items(), key=lambda x: x[1])[0]
        self.delete(oldest_key)  # 使用delete方法确保同时清理access_times

    def cleanup_expired(self) -> int:
        """
        清理所有过期项（主动清理）

        ✅ 新增：定期调用此方法可减少内存占用

        返回:
            int: 清理的过期项数量
        """
        current_time = time.time()
        expired_keys = []

        # 找出所有过期的键
        for key, (value, expiration_time) in self.cache.items():
            if current_time > expiration_time:
                expired_keys.append(key)

        # 删除过期项
        for key in expired_keys:
            self.delete(key)

        return len(expired_keys)

    def cleanup_unused(self) -> None:
        """
        清理 access_times 中未使用的键
        """
        # 找出那些在access_times中存在但在cache中不存在的键
        unused_keys = [k for k in self.access_times if k not in self.cache]
        for key in unused_keys:
            del self.access_times[key]

    def get_stats(self) -> dict:
        """
        获取缓存统计信息

        ✅ 新增：用于监控缓存状态

        返回:
            dict: 统计信息
        """
        current_time = time.time()
        expired_count = sum(1 for (value, exp_time) in self.cache.values() if current_time > exp_time)

        return {
            "total_items": len(self.cache),
            "max_size": self.max_size,
            "expired_items": expired_count,
            "active_items": len(self.cache) - expired_count,
            "utilization": len(self.cache) / self.max_size if self.max_size > 0 else 0,
        }
