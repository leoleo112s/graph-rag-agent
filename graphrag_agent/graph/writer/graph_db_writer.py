"""
GraphDB 写入器模块

专门负责将 GraphDocument 数据写入 Neo4j 数据库，与数据准备逻辑分离。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_community.graphs import Neo4jGraph
from langchain_community.graphs.graph_document import GraphDocument

from graphrag_agent.config.settings import BATCH_SIZE as DEFAULT_BATCH_SIZE
from graphrag_agent.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)


@dataclass
class WriteResult:
    """图数据库写入结果"""

    total: int = 0
    success_count: int = 0
    failed_count: int = 0
    failed_ids: List[str] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def add_success(self, count: int = 1):
        """添加成功记录"""
        self.success_count += count

    def add_failure(self, doc_id: str, error: str):
        """添加失败记录"""
        self.failed_count += 1
        self.failed_ids.append(doc_id)
        self.errors.append({"doc_id": doc_id, "error": error})

    @property
    def failure_rate(self) -> float:
        """计算失败率"""
        if self.total == 0:
            return 0.0
        return self.failed_count / self.total

    @property
    def success_rate(self) -> float:
        """计算成功率"""
        if self.total == 0:
            return 0.0
        return self.success_count / self.total

    def __str__(self) -> str:
        return (
            f"WriteResult(total={self.total}, success={self.success_count}, "
            f"failed={self.failed_count}, success_rate={self.success_rate:.2%})"
        )


class GraphDBWriter:
    """
    图数据库写入器

    专门负责将 GraphDocument 写入 Neo4j，提供：
    1. 批量写入（带自动重试）
    2. 事务管理
    3. 失败回退（批次失败时自动降级为逐个写入）
    4. 写入结果统计
    """

    def __init__(
        self,
        graph: Neo4jGraph,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_retries: int = 3,
        enable_base_entity_label: bool = True,
        include_source: bool = True,
    ):
        """
        初始化图数据库写入器

        Args:
            graph: Neo4j 图实例
            batch_size: 批次大小（默认使用配置值）
            max_retries: 最大重试次数（默认3次）
            enable_base_entity_label: 是否启用基础实体标签（默认True）
            include_source: 是否包含源文档信息（默认True）
        """
        self.graph = graph
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.enable_base_entity_label = enable_base_entity_label
        self.include_source = include_source

    @retry_with_backoff(max_retries=3, backoff_factor=0.5)
    def write_single_document(self, document: GraphDocument) -> None:
        """
        写入单个图文档（带重试）

        Args:
            document: 图文档

        Raises:
            Exception: 写入失败后抛出异常
        """
        self.graph.add_graph_documents(
            [document],
            baseEntityLabel=self.enable_base_entity_label,
            include_source=self.include_source,
        )

    def write_batch(
        self,
        documents: List[GraphDocument],
        fallback_to_individual: bool = True,
    ) -> WriteResult:
        """
        批量写入图文档

        Args:
            documents: 图文档列表
            fallback_to_individual: 批次失败时是否降级为逐个写入（默认True）

        Returns:
            WriteResult: 写入结果统计
        """
        result = WriteResult(total=len(documents))

        if not documents:
            logger.warning("No documents to write")
            return result

        # 动态调整批次大小
        optimal_batch_size = min(self.batch_size, max(10, len(documents) // 10))
        total_batches = (len(documents) + optimal_batch_size - 1) // optimal_batch_size

        logger.info(
            f"Starting batch write: {len(documents)} documents, "
            f"batch_size={optimal_batch_size}, total_batches={total_batches}"
        )

        # 批量写入
        for batch_idx in range(0, len(documents), optimal_batch_size):
            batch = documents[batch_idx : batch_idx + optimal_batch_size]
            batch_num = batch_idx // optimal_batch_size + 1

            try:
                # 尝试批量写入（使用事务）
                self._write_batch_with_retry(batch)
                result.add_success(len(batch))
                logger.info(f"Successfully wrote batch {batch_num}/{total_batches}")

            except Exception as e:
                logger.error(
                    f"Batch {batch_num}/{total_batches} failed: {e}",
                    exc_info=True,
                )

                if fallback_to_individual:
                    # 降级为逐个写入
                    logger.info(f"Falling back to individual writes for {len(batch)} documents")
                    self._write_batch_individually(batch, result)
                else:
                    # 不降级，直接记录失败
                    for idx, doc in enumerate(batch):
                        doc_id = f"batch_{batch_num}_doc_{idx}"
                        result.add_failure(doc_id, str(e))

        logger.info(f"Batch write completed: {result}")
        return result

    @retry_with_backoff(max_retries=3, backoff_factor=0.5)
    def _write_batch_with_retry(self, batch: List[GraphDocument]) -> None:
        """
        批量写入（带重试）

        Args:
            batch: 文档批次
        """
        self.graph.add_graph_documents(
            batch,
            baseEntityLabel=self.enable_base_entity_label,
            include_source=self.include_source,
        )

    def _write_batch_individually(self, batch: List[GraphDocument], result: WriteResult) -> None:
        """
        逐个写入批次中的文档（用于批次失败后的降级处理）

        Args:
            batch: 文档批次
            result: 结果对象（用于记录成功/失败）
        """
        for idx, doc in enumerate(batch):
            doc_id = f"doc_{idx}"
            try:
                self.write_single_document(doc)
                result.add_success()
                logger.debug(f"Successfully wrote individual document {idx + 1}/{len(batch)}")
            except Exception as e:
                result.add_failure(doc_id, str(e))
                logger.error(
                    f"Failed to write individual document {idx + 1}/{len(batch)}: {e}",
                    exc_info=True,
                )

    def merge_chunk_relationships(self, chunk_ids: List[str]) -> WriteResult:
        """
        合并 Chunk 节点与 Document 节点的关系

        Args:
            chunk_ids: 块ID列表

        Returns:
            WriteResult: 合并结果统计
        """
        result = WriteResult(total=len(chunk_ids))

        if not chunk_ids:
            logger.warning("No chunk IDs to merge")
            return result

        # 去重
        unique_chunk_ids = list(set(chunk_ids))
        logger.info(f"Merging {len(unique_chunk_ids)} unique chunks (from {len(chunk_ids)} total)")

        # 批量处理
        batch_size = 100
        for i in range(0, len(unique_chunk_ids), batch_size):
            batch = unique_chunk_ids[i : i + batch_size]

            try:
                self._merge_chunk_batch(batch)
                result.add_success(len(batch))
                logger.info(f"Merged chunk batch {i // batch_size + 1}")
            except Exception as e:
                for chunk_id in batch:
                    result.add_failure(chunk_id, str(e))
                logger.error(f"Failed to merge chunk batch: {e}", exc_info=True)

        logger.info(f"Chunk merge completed: {result}")
        return result

    @retry_with_backoff(max_retries=3, backoff_factor=0.5)
    def _merge_chunk_batch(self, chunk_ids: List[str]) -> None:
        """
        批量合并 Chunk 关系（带重试）

        Args:
            chunk_ids: 块ID列表
        """
        # Cypher 查询：将 Chunk 与其来源 Document 关联
        query = """
        UNWIND $chunk_ids AS chunk_id
        MATCH (c:__Chunk__ {id: chunk_id})
        MATCH (d:__Document__ {id: c.doc_id})
        MERGE (d)-[:HAS_CHUNK]->(c)
        """

        self.graph.query(query, params={"chunk_ids": chunk_ids})

    def execute_custom_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """
        执行自定义 Cypher 查询

        Args:
            query: Cypher 查询语句
            params: 查询参数

        Returns:
            查询结果
        """
        return self.graph.query(query, params=params or {})
