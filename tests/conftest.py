"""
Pytest配置和共享fixtures
"""

import os
import sys
from pathlib import Path

import pytest

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def test_data_dir():
    """测试数据目录"""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def mock_neo4j_graph():
    """模拟的 Neo4j 图实例"""
    from unittest.mock import Mock

    mock_graph = Mock()
    mock_graph.add_graph_documents = Mock()
    mock_graph.query = Mock(return_value=[])
    return mock_graph


@pytest.fixture
def mock_llm():
    """模拟的 LLM 实例"""
    from unittest.mock import Mock

    mock = Mock()
    mock.invoke = Mock(return_value="Mocked LLM response")
    return mock


@pytest.fixture
def temp_cache_dir(tmp_path):
    """临时缓存目录"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return str(cache_dir)
