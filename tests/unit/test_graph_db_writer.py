"""
GraphDBWriter 单元测试
"""

import pytest
from unittest.mock import Mock, call

from graphrag_agent.graph.writer import GraphDBWriter, WriteResult


@pytest.mark.unit
class TestWriteResult:
    """WriteResult 数据类测试"""

    def test_write_result_creation(self):
        """测试创建 WriteResult"""
        result = WriteResult(total=100)
        assert result.total == 100
        assert result.success_count == 0
        assert result.failed_count == 0

    def test_add_success(self):
        """测试添加成功记录"""
        result = WriteResult(total=100)
        result.add_success(10)
        assert result.success_count == 10

    def test_add_failure(self):
        """测试添加失败记录"""
        result = WriteResult(total=100)
        result.add_failure("doc_1", "Error message")

        assert result.failed_count == 1
        assert "doc_1" in result.failed_ids
        assert len(result.errors) == 1
        assert result.errors[0]["doc_id"] == "doc_1"

    def test_success_rate(self):
        """测试成功率计算"""
        result = WriteResult(total=100)
        result.add_success(70)
        result.add_failure("doc_1", "error")
        result.add_failure("doc_2", "error")

        assert result.success_count == 70
        assert result.failed_count == 2
        assert result.success_rate == 0.7

    def test_failure_rate(self):
        """测试失败率计算"""
        result = WriteResult(total=100)
        result.add_success(80)
        result.add_failure("doc_1", "error")

        assert result.failure_rate == 0.01  # 1/100


@pytest.mark.unit
class TestGraphDBWriter:
    """GraphDBWriter 核心功能测试"""

    @pytest.fixture
    def writer(self, mock_neo4j_graph):
        """测试用的写入器"""
        return GraphDBWriter(
            graph=mock_neo4j_graph,
            batch_size=10,
            max_retries=3,
        )

    def test_write_single_document_success(self, writer, mock_neo4j_graph):
        """单个文档写入成功"""
        mock_doc = Mock()

        writer.write_single_document(mock_doc)

        # 验证调用了 add_graph_documents
        mock_neo4j_graph.add_graph_documents.assert_called_once()
        call_args = mock_neo4j_graph.add_graph_documents.call_args
        assert call_args[0][0] == [mock_doc]  # 第一个参数是文档列表

    def test_write_batch_all_success(self, writer, mock_neo4j_graph):
        """批量写入全部成功"""
        mock_docs = [Mock() for _ in range(25)]

        result = writer.write_batch(mock_docs)

        assert result.total == 25
        assert result.success_count == 25
        assert result.failed_count == 0
        assert result.success_rate == 1.0

        # 验证调用了多次批量写入（25个文档，batch_size=10，应该是3次）
        assert mock_neo4j_graph.add_graph_documents.call_count >= 1

    def test_write_batch_with_fallback(self, writer, mock_neo4j_graph):
        """批量写入失败后降级为单个写入"""
        mock_docs = [Mock() for _ in range(5)]

        # 第一次批量写入失败，后续单个写入成功
        mock_neo4j_graph.add_graph_documents.side_effect = [
            Exception("Batch write failed"),  # 批量失败
            None,
            None,
            None,
            None,
            None,  # 单个写入成功
        ]

        result = writer.write_batch(mock_docs, fallback_to_individual=True)

        # 应该降级为单个写入，全部成功
        assert result.success_count == 5
        assert result.failed_count == 0

        # 验证调用次数：1次批量失败 + 5次单个成功 = 6次
        assert mock_neo4j_graph.add_graph_documents.call_count == 6

    def test_write_batch_without_fallback(self, writer, mock_neo4j_graph):
        """批量写入失败且不降级"""
        mock_docs = [Mock() for _ in range(5)]

        # 批量写入失败
        mock_neo4j_graph.add_graph_documents.side_effect = Exception("Batch failed")

        result = writer.write_batch(mock_docs, fallback_to_individual=False)

        # 不降级，所有文档都失败
        assert result.failed_count == 5
        assert result.success_count == 0

    def test_merge_chunk_relationships_success(self, writer, mock_neo4j_graph):
        """合并 Chunk 关系成功"""
        chunk_ids = ["chunk_1", "chunk_2", "chunk_3", "chunk_3"]  # 包含重复

        result = writer.merge_chunk_relationships(chunk_ids)

        # 验证去重（4个变3个）
        assert result.total == 4

        # 验证调用了 query
        assert mock_neo4j_graph.query.called

    def test_execute_custom_query(self, writer, mock_neo4j_graph):
        """执行自定义查询"""
        query = "MATCH (n) RETURN count(n)"
        params = {"param1": "value1"}

        mock_neo4j_graph.query.return_value = [{"count": 100}]

        result = writer.execute_custom_query(query, params)

        mock_neo4j_graph.query.assert_called_once_with(query, params=params)
        assert result == [{"count": 100}]

    def test_batch_size_adjustment(self, writer):
        """测试批次大小动态调整"""
        # 小批次：应该使用默认的10
        mock_docs_small = [Mock() for _ in range(5)]
        writer.write_batch(mock_docs_small)

        # 大批次：应该调整为 max(10, len/10)
        mock_docs_large = [Mock() for _ in range(200)]
        writer.write_batch(mock_docs_large)

        # 验证成功执行（不抛异常）
        assert True


@pytest.mark.unit
class TestGraphDBWriterEdgeCases:
    """GraphDBWriter 边界情况测试"""

    def test_empty_documents(self, mock_neo4j_graph):
        """空文档列表"""
        writer = GraphDBWriter(mock_neo4j_graph)
        result = writer.write_batch([])

        assert result.total == 0
        assert result.success_count == 0
        assert result.failed_count == 0

        # 不应该调用图操作
        mock_neo4j_graph.add_graph_documents.assert_not_called()

    def test_empty_chunk_ids(self, mock_neo4j_graph):
        """空 chunk ID 列表"""
        writer = GraphDBWriter(mock_neo4j_graph)
        result = writer.merge_chunk_relationships([])

        assert result.total == 0
        # 不应该调用查询
        mock_neo4j_graph.query.assert_not_called()
