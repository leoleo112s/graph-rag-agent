"""
L0 快速摄取管道 - 文本分块与向量化

用户上传文件后，10秒内完成：
1. 文件读取与文本提取
2. 文本分块 (Chunking)
3. 向量化 (Embedding)
4. 写入向量数据库

目标：让用户立即使用 Naive RAG 搜索
"""
import time
import os
import uuid
from pathlib import Path
from typing import List, Dict, Any
from rich.console import Console

from graphrag_agent.pipelines.ingestion.document_processor import DocumentProcessor
from graphrag_agent.graph.indexing.embedding_manager import EmbeddingManager
from graphrag_agent.config.settings import FILES_DIR, BATCH_SIZE, MAX_WORKERS, CHUNK_SIZE, OVERLAP


class FastIngestionPipeline:
    """
    L0 快速摄取管道
    """

    def __init__(self, files_dir: str = FILES_DIR):
        """
        初始化快速摄取管道
        """
        self.console = Console()
        self.files_dir = files_dir

        # =========================================================
        # ✅ 修复 1: 严格按照 DocumentProcessor 源码初始化
        # =========================================================
        self.console.print(f"[DEBUG] 初始化 DocumentProcessor, 目录: {files_dir}")
        self.doc_processor = DocumentProcessor(
            directory_path=files_dir,  # 必填位置参数 1
            chunk_size=CHUNK_SIZE,     # 选填参数
            overlap=OVERLAP,           # 选填参数
            chunker_mode="default"     # L0 快速模式使用默认/RAG分块即可
        )

        self.embedding_manager = EmbeddingManager(
            batch_size=BATCH_SIZE,
            max_workers=MAX_WORKERS
        )

    def process_single_file(self, file_path: str, force: bool = False) -> Dict:
        """快速处理单个文件"""
        start_time = time.time()
        self.console.print(f"[bold cyan][L0] 快速处理文件: {file_path}[/bold cyan]")

        try:
            target_filename = os.path.basename(file_path)

            # 跳过隐藏文件或系统元数据文件（例如 .DS_Store）
            if target_filename.startswith('.'):
                self.console.print(
                    f"[yellow]跳过不支持的文件: {target_filename}[/yellow]"
                )
                return {
                    "status": "skipped",
                    "file_path": file_path,
                    "reason": "unsupported hidden or system file",
                    "duration": time.time() - start_time,
                }

            # 步骤 1: 文本提取与分块
            self.console.print("[cyan]  → 步骤 1/2: 文本提取与分块...[/cyan]")
            chunk_start = time.time()
            chunks = self._extract_and_chunk(file_path, target_filename)

            chunk_duration = time.time() - chunk_start
            self.console.print(f"[green]  ✓ 生成 {len(chunks)} 个文本块 ({chunk_duration:.2f}s)[/green]")

            # 步骤 2: 向量化
            self.console.print("[cyan]  → 步骤 2/2: 向量化与写入...[/cyan]")
            embed_start = time.time()

            vectorized_count = self._vectorize_and_store(chunks, file_path)

            embed_duration = time.time() - embed_start
            self.console.print(f"[green]  ✓ 向量化 {vectorized_count} 个块 ({embed_duration:.2f}s)[/green]")

            total_duration = time.time() - start_time
            self.console.print(f"[bold green]✅ L0 处理完成，总耗时: {total_duration:.2f}s[/bold green]")

            return {
                "status": "success",
                "file_path": file_path,
                "chunks_created": len(chunks),
                "chunks_vectorized": vectorized_count,
                "duration": total_duration
            }

        except Exception as e:
            error_msg = str(e)
            self.console.print(f"[red]❌ L0 处理失败: {error_msg}[/red]")
            return {
                "status": "error",
                "file_path": file_path,
                "error": error_msg,
                "duration": time.time() - start_time
            }

    def process_batch_files(self, file_paths: List[str]) -> List[Dict]:
        """批量快速处理多个文件"""
        self.console.print(f"[bold cyan][L0] 批量处理 {len(file_paths)} 个文件[/bold cyan]")
        results = []
        for file_path in file_paths:
            result = self.process_single_file(file_path)
            results.append(result)
        return results

    def _extract_and_chunk(self, file_path: str, target_filename: str) -> List[Dict]:
        """
        提取文本并分块
        
        注意：DocumentProcessor 源码显示它只支持 process_directory，且返回 tuple。
        我们需要适配这个接口。
        """
        try:
            # =========================================================
            # ✅ 修复 2: 仅处理目标文件，避免重复处理目录下的其他文件
            # DocumentProcessor.process_file 返回 (results_list, summary_object)
            # =========================================================
            results, _ = self.doc_processor.process_file(
                file_path=file_path,
                return_summary=False,
            )

            if not results:
                raise FileNotFoundError(f"DocumentProcessor 未能处理文件: {file_path}")

            target_file_result = results[0]

            raw_chunks = target_file_result.get("chunks", [])
            if raw_chunks is None:
                raw_chunks = []

            # =========================================================
            # ✅ 修复 3: 数据格式转换
            # DocumentProcessor 返回的是 List[str]，我们需要转为 List[Dict]
            # 以便后续向量化步骤使用
            # =========================================================
            formatted_chunks = []
            for idx, text_content in enumerate(raw_chunks):
                # 如果是自适应分块，raw_chunks 可能是字典；如果是默认分块，是字符串或字符列表
                chunk_text = text_content
                if isinstance(text_content, dict):
                    chunk_text = text_content.get("content", "")
                elif isinstance(text_content, list):
                    # 默认分块器返回的是字符列表，需要拼接成字符串
                    if all(isinstance(x, str) for x in text_content):
                        chunk_text = "".join(text_content)
                    else:
                        chunk_text = " ".join(str(x) for x in text_content)

                chunk_id = str(uuid.uuid4())
                formatted_chunks.append({
                    "text": chunk_text,
                    "chunk_id": chunk_id,
                    "id": chunk_id,
                    "file_name": target_filename,
                    "file_path": file_path,
                    "index": idx,
                    "metadata": {
                        "source": file_path,
                        "chunk_index": idx
                    }
                })

            return formatted_chunks

        except Exception as e:
            self.console.print(f"[red]文本提取失败: {e}[/red]")
            raise

    def _vectorize_and_store(self, chunks: List[Dict], file_path: str) -> int:
        """向量化并存储"""
        if not chunks:
            return 0
        try:
            # 将分块写入 Neo4j，确保后续向量化有对应节点
            self._upsert_chunks(chunks)

            chunk_ids = [chunk.get("chunk_id") for chunk in chunks if chunk.get("chunk_id")]

            # 调用 EmbeddingManager，仅使用 chunk_id 列表以匹配预期接口
            updated_count = self.embedding_manager.update_chunk_embeddings(chunk_ids)
            
            return updated_count if updated_count is not None else len(chunks)
        except TypeError:
            # 兼容性处理：如果 update_chunk_embeddings 不接受参数
            return self.embedding_manager.update_chunk_embeddings()
        except Exception as e:
            self.console.print(f"[red]向量化失败: {e}[/red]")
            raise

    def check_file_ready_for_search(self, file_path: str) -> bool:
        """
        检查文件是否已经可以搜索（Chunk已向量化）

        Args:
            file_path: 文件路径

        Returns:
            bool: 是否可搜索
        """
        # 查询 Neo4j，检查文件对应的 Chunk 是否都有 embedding
        # 这需要一个查询方法

        # 临时实现：通过 embedding_manager 检查
        try:
            chunks = self.embedding_manager.get_chunks_needing_update()

            # 过滤出当前文件的chunks
            file_chunks_needing_update = [
                c for c in chunks
                if c.get("file_path") == file_path or c.get("file_name") == Path(file_path).name
            ]

            # 如果没有需要更新的chunk，说明都已向量化
            return len(file_chunks_needing_update) == 0

        except Exception as e:
            self.console.print(f"[yellow]检查文件状态失败: {e}[/yellow]")
            return False

    def _upsert_chunks(self, chunks: List[Dict]) -> None:
        """确保分块节点存在并需要向量化"""
        query = """
        UNWIND $chunks AS chunk
        MERGE (d:`__Document__` {fileName: chunk.file_name})
          ON CREATE SET d.id = coalesce(chunk.file_name, chunk.file_path),
                        d.uri = chunk.file_path,
                        d.created_at = datetime()
          ON MATCH SET d.last_updated = datetime()
        MERGE (c:`__Chunk__` {id: chunk.chunk_id})
          SET c.text = chunk.text,
              c.file_name = chunk.file_name,
              c.fileName = chunk.file_name,
              c.file_path = chunk.file_path,
              c.position = chunk.index,
              c.chunk_index = chunk.index,
              c.needs_reembedding = true,
              c.last_updated = datetime()
        MERGE (c)-[:PART_OF]->(d)
        RETURN count(c) AS touched
        """

        try:
            self.embedding_manager.graph.query(query, params={"chunks": chunks})
        except Exception as exc:
            self.console.print(f"[yellow]写入分块节点时出错: {exc}[/yellow]")

    def get_processing_stats(self) -> Dict:
        """
        获取处理统计

        Returns:
            Dict: 统计信息
        """
        # 查询数据库获取统计信息
        # 例如：总chunk数、已向量化数、待处理数
        try:
            all_chunks = self.embedding_manager.get_chunks_needing_update()

            return {
                "total_chunks_needing_embedding": len(all_chunks),
                "status": "ready" if len(all_chunks) == 0 else "processing"
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }


# 便捷函数
def quick_ingest_file(file_path: str) -> Dict:
    """
    快速摄取单个文件（便捷函数）

    Args:
        file_path: 文件路径

    Returns:
        Dict: 处理结果
    """
    pipeline = FastIngestionPipeline()
    return pipeline.process_single_file(file_path)


def quick_ingest_directory(directory: str) -> List[Dict]:
    """
    快速摄取整个目录（便捷函数）

    Args:
        directory: 目录路径

    Returns:
        List[Dict]: 处理结果列表
    """
    import os

    # 获取目录下所有文件
    file_paths = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            # 过滤支持的文件类型
            if file.endswith(('.txt', '.pdf', '.md', '.docx', '.doc', '.csv', '.json', '.yaml')):
                file_paths.append(os.path.join(root, file))

    # 批量处理
    pipeline = FastIngestionPipeline()
    return pipeline.process_batch_files(file_paths)
