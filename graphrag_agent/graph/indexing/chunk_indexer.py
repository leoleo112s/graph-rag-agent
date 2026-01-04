import concurrent.futures
import logging
import time
from typing import Any, Dict, List, Optional

from langchain_community.vectorstores import Neo4jVector

from graphrag_agent.config.settings import (
    CHUNK_BATCH_SIZE,
    CHUNK_VECTOR_INDEX,
    CLEAN_LEGACY_INDEXES,
    EMBEDDING_DIM,
)
from graphrag_agent.config.settings import MAX_WORKERS as DEFAULT_MAX_WORKERS
from graphrag_agent.config.settings import (
    VECTOR_SIMILARITY_FUNCTION,
)
from graphrag_agent.graph.core import BaseIndexer, connection_manager, retry
from graphrag_agent.models.get_models import get_embeddings_model

# 配置日志
logger = logging.getLogger(__name__)


class ChunkIndexManager(BaseIndexer):
    """
    Chunk索引管理器，负责在Neo4j数据库中创建和管理文本块的向量索引。
    处理__Chunk__节点的embedding向量计算和索引创建，支持后续基于向量相似度的RAG查询。
    """

    def __init__(self, refresh_schema: bool = True, batch_size: int = 100, max_workers: int = 4):
        """
        初始化Chunk索引管理器

        Args:
            refresh_schema: 是否刷新Neo4j图数据库的schema
            batch_size: 批处理大小
            max_workers: 并行工作线程数
        """
        batch_size = batch_size or CHUNK_BATCH_SIZE
        max_workers = max_workers or DEFAULT_MAX_WORKERS

        super().__init__(batch_size, max_workers)

        # 初始化图数据库连接
        self.graph = connection_manager.get_connection()

        # 初始化嵌入模型
        self.embeddings = get_embeddings_model()

        # 创建必要的索引
        self._create_indexes()

    def _create_indexes(self) -> None:
        """创建必要的索引以优化查询性能"""
        index_queries = [
            "CREATE INDEX IF NOT EXISTS FOR (c:`__Chunk__`) ON (c.id)",
            "CREATE INDEX IF NOT EXISTS FOR (c:`__Chunk__`) ON (c.fileName)",
            "CREATE INDEX IF NOT EXISTS FOR (c:`__Chunk__`) ON (c.position)",
        ]

        connection_manager.create_multiple_indexes(index_queries)

    def clear_existing_index(self) -> None:
        """清除已存在的普通索引"""
        connection_manager.drop_index(CHUNK_VECTOR_INDEX)
        if CLEAN_LEGACY_INDEXES:
            # 兼容历史命名，防止旧索引残留
            connection_manager.drop_index("chunk_embedding")

    def create_vector_index(self, node_label: str = "__Chunk__", embedding_property: str = "embedding") -> None:
        """
        显式创建 Neo4j Vector Index（工程级实践）

        Args:
            node_label: 节点标签
            embedding_property: embedding属性名
        """
        query = f"""
        CREATE VECTOR INDEX {CHUNK_VECTOR_INDEX} IF NOT EXISTS
        FOR (c:`{node_label}`)
        ON (c.{embedding_property})
        OPTIONS {{
          indexConfig: {{
            `vector.dimensions`: {EMBEDDING_DIM},
            `vector.similarity_function`: '{VECTOR_SIMILARITY_FUNCTION}'
          }}
        }}
        """
        try:
            self.graph.query(query)
            logger.info(f"✅ Vector index created/verified: {CHUNK_VECTOR_INDEX}")
        except Exception as e:
            # 索引可能已存在，这不是错误
            if "already exists" in str(e).lower() or "equivalent" in str(e).lower():
                logger.info(f"✅ Vector index already exists: {CHUNK_VECTOR_INDEX}")
            else:
                logger.warning(f"⚠️ Vector index creation warning: {e}")
                raise

    def create_chunk_index(
        self, node_label: str = "__Chunk__", text_property: str = "text", embedding_property: str = "embedding"
    ) -> bool:
        """
        为文本块节点生成embeddings并创建 Neo4j Vector Index（工程级实践）

        流程：
        1. 计算 embeddings
        2. 显式创建 vector index

        Args:
            node_label: 文本块节点的标签
            text_property: 用于计算embedding的文本属性
            embedding_property: 存储embedding的属性名

        Returns:
            bool: 是否成功创建索引
        """
        start_time = time.time()

        # 先清除已有的旧索引
        self.clear_existing_index()

        # 获取所有需要处理的文本块节点
        chunks = self.graph.query(
            f"""
            MATCH (c:`{node_label}`)
            WHERE c.{text_property} IS NOT NULL AND c.{embedding_property} IS NULL
            RETURN id(c) AS neo4j_id, c.id AS chunk_id
            """
        )

        if not chunks:
            logger.info("没有找到需要处理的文本块节点（可能已存在 embeddings）")
            # 即使没有新的节点，也确保 vector index 存在
            try:
                self.create_vector_index(node_label, embedding_property)
                logger.info("✅ Vector index 已就绪（无新节点需要处理）")
                return True
            except Exception as e:
                logger.error(f"❌ Vector index 创建失败: {e}", exc_info=True)
                return False

        logger.info(f"开始为 {len(chunks)} 个文本块生成 embeddings")

        # 步骤 1: 批量计算并更新 embeddings
        self._process_embeddings_in_batches(chunks, node_label, text_property, embedding_property)

        # 步骤 2: 显式创建 Neo4j Vector Index（关键！）
        try:
            self.create_vector_index(node_label, embedding_property)

            end_time = time.time()
            logger.info(f"\n✅ 索引创建成功，总耗时: {end_time - start_time:.2f}秒")
            logger.info(f"   其中: embedding计算: {self.embedding_time:.2f}秒, 数据库操作: {self.db_time:.2f}秒")

            return True
        except Exception as e:
            logger.error(f"❌ Vector index 创建失败: {e}", exc_info=True)
            return False

    def _process_embeddings_in_batches(
        self, chunks: List[Dict[str, Any]], node_label: str, text_property: str, embedding_property: str
    ) -> None:
        """
        批量处理文本块embedding的生成

        Args:
            chunks: 文本块列表
            node_label: 节点标签
            text_property: 文本属性
            embedding_property: embedding属性名
        """
        # 获取最优批处理大小
        chunk_count = len(chunks)
        optimal_batch_size = self.get_optimal_batch_size(chunk_count)

        def process_batch(batch, batch_index):
            # 获取批次内所有文本块的文本
            chunk_texts = self._get_chunk_texts_batch(batch, text_property)

            # 计算embeddings
            embedding_start = time.time()
            embeddings = self._compute_embeddings_batch(chunk_texts)
            embedding_end = time.time()
            self.embedding_time += embedding_end - embedding_start

            # 更新数据库
            db_start = time.time()
            self._update_embeddings_batch(batch, embeddings, embedding_property)
            db_end = time.time()
            self.db_time += db_end - db_start

        # 使用通用批处理方法
        self.batch_process_with_progress(chunks, process_batch, optimal_batch_size, "处理文本块embedding")

    @retry(times=3, delay=1.0)
    def _safe_embed_query(self, text: str) -> List[float]:
        """
        安全的单文本 embedding 计算（带重试）

        Args:
            text: 输入文本

        Returns:
            List[float]: embedding 向量
        """
        return self.embeddings.embed_query(text)

    def _get_embedding_dimension(self) -> int:
        """
        获取 embedding 维度（优先使用配置，fallback 到自动探测）

        Returns:
            int: embedding 维度
        """
        # 优先使用全局配置
        if EMBEDDING_DIM and EMBEDDING_DIM > 0:
            return EMBEDDING_DIM

        # Fallback: 从 embeddings 对象获取
        if hasattr(self.embeddings, "embedding_size"):
            return self.embeddings.embedding_size

        # 最后 fallback: 通用默认值（仅警告）
        logger.warning("无法获取 embedding 维度配置，使用默认值 1536。建议在 settings.py 中配置 EMBEDDING_DIM")
        return 1536

    def _compute_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        计算一批文本的embedding向量（并发安全 + 顺序保证）

        Args:
            texts: 文本列表

        Returns:
            List[List[float]]: embedding向量列表（顺序与输入严格对应）
        """
        # 获取 embedding 维度（用于降级逻辑）
        target_dim = self._get_embedding_dimension()

        # 预创建嵌入任务（确保非空文本）
        embedding_tasks = []
        for text in texts:
            safe_text = text if text and text.strip() else "empty chunk"
            embedding_tasks.append(safe_text)

        # 🔥 预分配结果列表（关键：确保顺序对齐）
        embeddings = [None] * len(embedding_tasks)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 分析批处理的最佳大小
            embed_batch_size = min(32, len(embedding_tasks))

            # 批量执行嵌入任务
            for batch_start in range(0, len(embedding_tasks), embed_batch_size):
                batch_end = min(batch_start + embed_batch_size, len(embedding_tasks))
                sub_batch = embedding_tasks[batch_start:batch_end]

                try:
                    # 策略 1: 尝试使用批量嵌入方法（最快）
                    if hasattr(self.embeddings, "embed_documents"):
                        sub_batch_embeddings = self.embeddings.embed_documents(sub_batch)
                        # 填充到正确位置
                        for offset, emb in enumerate(sub_batch_embeddings):
                            embeddings[batch_start + offset] = emb
                    else:
                        # 策略 2: 并发单个嵌入（需要保证顺序）
                        # 🔥 使用 future_to_index 确保顺序对齐
                        future_to_index = {
                            executor.submit(self._safe_embed_query, text): batch_start + i
                            for i, text in enumerate(sub_batch)
                        }

                        for future in concurrent.futures.as_completed(future_to_index):
                            global_idx = future_to_index[future]
                            try:
                                # ✅ 按索引填充，而非追加
                                embeddings[global_idx] = future.result()
                            except Exception as e:
                                logger.error(
                                    f"嵌入计算最终失败 (索引: {global_idx}, 文本: {embedding_tasks[global_idx][:30]}...): {e}",
                                    exc_info=True,
                                )
                                # 降级处理：填充零向量
                                embeddings[global_idx] = [0.0] * target_dim

                except Exception as e:
                    logger.error(f"批量嵌入处理失败 (批次起始: {batch_start}): {e}", exc_info=True)
                    # 回退策略：逐个尝试（不使用并发）
                    for offset, text in enumerate(sub_batch):
                        global_idx = batch_start + offset
                        try:
                            embeddings[global_idx] = self._safe_embed_query(text)
                        except Exception as e2:
                            logger.error(
                                f"单个嵌入计算失败 (索引: {global_idx}, 文本: {text[:30]}...): {e2}", exc_info=True
                            )
                            # 降级处理：填充零向量
                            embeddings[global_idx] = [0.0] * target_dim

        # 🔥 验证完整性：确保没有 None 值
        none_indices = [i for i, emb in enumerate(embeddings) if emb is None]
        if none_indices:
            logger.error(f"严重错误：存在 {len(none_indices)} 个未填充的 embedding 槽位 (索引: {none_indices[:10]})")
            # 修复：填充零向量
            for idx in none_indices:
                embeddings[idx] = [0.0] * target_dim

        return embeddings

    def _get_chunk_texts_batch(self, chunks: List[Dict[str, Any]], text_property: str) -> List[str]:
        """
        获取批量文本块的文本内容

        Args:
            chunks: 文本块列表
            text_property: 文本属性

        Returns:
            List[str]: 文本块文本列表
        """
        # 构建查询参数
        chunk_ids = [chunk["neo4j_id"] for chunk in chunks]

        # 使用高效的文本提取查询
        query = f"""
        UNWIND $chunk_ids AS id
        MATCH (c) WHERE id(c) = id
        RETURN id, c.{text_property} AS chunk_text
        """

        results = self.graph.query(query, params={"chunk_ids": chunk_ids})

        # 提取文本内容
        chunk_texts = []
        for row in results:
            text = row.get("chunk_text", "")
            # 确保文本不为空
            if not text:
                text = f"chunk_{row['id']}"

            chunk_texts.append(text)

        return chunk_texts

    def _update_embeddings_batch(
        self, chunks: List[Dict[str, Any]], embeddings: List[List[float]], embedding_property: str
    ) -> None:
        """
        批量更新文本块embeddings

        Args:
            chunks: 文本块列表
            embeddings: 对应的embedding列表
            embedding_property: embedding属性名
        """
        # 构建更新数据
        update_data = []
        for i, chunk in enumerate(chunks):
            if i < len(embeddings) and embeddings[i] is not None:
                update_data.append({"id": chunk["neo4j_id"], "embedding": embeddings[i]})

        # 批量更新
        if update_data:
            try:
                query = f"""
                UNWIND $updates AS update
                MATCH (c) WHERE id(c) = update.id
                SET c.{embedding_property} = update.embedding
                """
                self.graph.query(query, params={"updates": update_data})
            except Exception as e:
                logger.error(f"批量更新embeddings失败: {e}", exc_info=True)
                # 回退到单个更新模式
                for update in update_data:
                    try:
                        single_query = f"""
                        MATCH (c) WHERE id(c) = $id
                        SET c.{embedding_property} = $embedding
                        """
                        self.graph.query(single_query, params={"id": update["id"], "embedding": update["embedding"]})
                    except Exception as e2:
                        logger.error(f"单个embedding更新失败 (ID: {update['id']}): {e2}", exc_info=True)
