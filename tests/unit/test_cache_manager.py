"""
CacheManager 单元测试
"""

import threading
import time

import pytest

from graphrag_agent.cache_manager import CacheManager
from graphrag_agent.cache_manager.models import CacheItem


@pytest.mark.unit
class TestCacheManager:
    """CacheManager 核心功能测试"""

    @pytest.fixture
    def cache_manager(self, temp_cache_dir):
        """测试用的缓存管理器（内存模式）"""
        return CacheManager(
            memory_only=True,
            thread_safe=True,
            enable_vector_similarity=False,  # 禁用向量相似性以加快测试
        )

    def test_cache_set_and_get(self, cache_manager):
        """测试基本的设置和获取"""
        query = "测试查询"
        result = "测试结果"

        cache_manager.set(query, result)
        cached = cache_manager.get(query)

        assert cached == result

    def test_cache_miss(self, cache_manager):
        """测试缓存未命中"""
        result = cache_manager.get("不存在的查询")
        assert result is None

    def test_cache_ttl_expiration(self, cache_manager):
        """测试 TTL 过期功能"""
        query = "过期测试"
        result = "结果"

        # 设置缓存
        cache_manager.set(query, result)

        # 手动设置过期时间为 1 秒
        key = cache_manager._get_consistent_key(query)
        cached_data = cache_manager.storage.get(key)
        item = CacheItem.from_any(cached_data)
        item.set_ttl(1)  # 1秒后过期
        cache_manager.storage.set(key, item.to_dict())

        # 立即获取应该成功
        assert cache_manager.get(query) == result

        # 等待过期
        time.sleep(1.1)

        # 过期后应该返回 None
        assert cache_manager.get(query) is None

    def test_thread_safe_metrics(self, cache_manager):
        """测试线程安全的性能指标"""

        def increment_queries():
            for _ in range(100):
                cache_manager.get("test_query")

        # 启动10个线程同时访问
        threads = [threading.Thread(target=increment_queries) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        metrics = cache_manager.get_metrics()
        # 10个线程 * 100次查询 = 1000次
        assert metrics["total_queries"] == 1000
        # 都应该是 miss（因为没有设置过缓存）
        assert metrics["misses"] == 1000

    def test_cache_quality_marking(self, cache_manager):
        """测试缓存质量标记"""
        query = "质量测试"
        result = "结果"

        cache_manager.set(query, result)

        # 标记为高质量
        success = cache_manager.mark_quality(query, is_positive=True)
        assert success is True

        # 获取并验证质量分数
        key = cache_manager._get_consistent_key(query)
        cached_data = cache_manager.storage.get(key)
        item = CacheItem.from_any(cached_data)

        assert item.is_high_quality() is True
        assert item.metadata["user_verified"] is True
        assert item.metadata["fast_path_eligible"] is True

    def test_cache_delete(self, cache_manager):
        """测试缓存删除"""
        query = "删除测试"
        result = "结果"

        cache_manager.set(query, result)
        assert cache_manager.get(query) == result

        # 删除缓存
        deleted = cache_manager.delete(query)
        assert deleted is True

        # 再次获取应该失败
        assert cache_manager.get(query) is None

    def test_cache_clear(self, cache_manager):
        """测试清空所有缓存"""
        # 设置多个缓存项
        for i in range(5):
            cache_manager.set(f"query_{i}", f"result_{i}")

        # 验证都已缓存
        assert cache_manager.get("query_0") == "result_0"
        assert cache_manager.get("query_4") == "result_4"

        # 清空缓存
        cache_manager.clear()

        # 验证都已清除
        for i in range(5):
            assert cache_manager.get(f"query_{i}") is None

    def test_get_metrics(self, cache_manager):
        """测试性能指标获取"""
        # 执行一些操作
        cache_manager.set("q1", "r1")
        cache_manager.get("q1")  # hit
        cache_manager.get("q2")  # miss

        metrics = cache_manager.get_metrics()

        assert metrics["total_queries"] == 2
        assert metrics["exact_hits"] == 1
        assert metrics["misses"] == 1
        assert metrics["exact_hit_rate"] == 0.5
        assert metrics["miss_rate"] == 0.5


@pytest.mark.unit
class TestCacheItem:
    """CacheItem 单元测试"""

    def test_cache_item_creation(self):
        """测试缓存项创建"""
        content = "测试内容"
        item = CacheItem(content)

        assert item.get_content() == content
        assert "created_at" in item.metadata
        assert item.metadata["quality_score"] == 0

    def test_ttl_setting(self):
        """测试 TTL 设置"""
        item = CacheItem("content")
        item.set_ttl(10)  # 10秒

        assert item.metadata["expires_at"] is not None
        assert not item.is_expired()

        # 设置为0秒（立即过期）
        item.set_ttl(0)
        time.sleep(0.1)
        assert item.is_expired()

    def test_quality_marking(self):
        """测试质量标记"""
        item = CacheItem("content")

        assert not item.is_high_quality()

        # 标记为正面
        item.mark_quality(is_positive=True)
        assert item.is_high_quality()
        assert item.metadata["quality_score"] == 1

        # 多次标记
        item.mark_quality(is_positive=True)
        item.mark_quality(is_positive=True)
        assert item.metadata["quality_score"] == 3

        # 标记为负面
        item.mark_quality(is_positive=False)
        assert item.metadata["quality_score"] == 1  # 3 - 2

    def test_access_stats(self):
        """测试访问统计"""
        item = CacheItem("content")

        assert item.metadata["access_count"] == 0
        assert item.metadata["last_accessed"] is None

        item.update_access_stats()
        assert item.metadata["access_count"] == 1
        assert item.metadata["last_accessed"] is not None

        item.update_access_stats()
        assert item.metadata["access_count"] == 2

    def test_serialization(self):
        """测试序列化和反序列化"""
        original = CacheItem("测试内容", {"custom_field": "value"})

        # 转换为字典
        data_dict = original.to_dict()
        assert "content" in data_dict
        assert "metadata" in data_dict

        # 从字典恢复
        restored = CacheItem.from_dict(data_dict)
        assert restored.get_content() == original.get_content()
        assert restored.metadata["custom_field"] == "value"

        # JSON 序列化
        json_str = original.to_json()
        assert json_str is not None

        restored_from_json = CacheItem.from_json(json_str)
        assert restored_from_json.get_content() == original.get_content()
