import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from graphrag_agent.config.settings import CHUNK_SIZE, FILES_DIR, OVERLAP
from graphrag_agent.pipelines.ingestion.adaptive_chunker import AdaptiveChunker, create_adaptive_chunker
from graphrag_agent.pipelines.ingestion.file_reader import FileReader
from graphrag_agent.pipelines.ingestion.specialized_chunkers import (
    GraphChunker,
    RAGChunker,
    create_graph_chunker,
    create_rag_chunker,
)
from graphrag_agent.pipelines.ingestion.text_chunker import ChineseTextChunker

# 配置日志
logger = logging.getLogger(__name__)


@dataclass
class ProcessingSummary:
    """文档处理摘要统计"""

    total_files: int = 0
    success_count: int = 0
    failed_count: int = 0
    total_chunks: int = 0
    avg_chunk_size: float = 0.0
    min_chunk_size: int = 0
    max_chunk_size: int = 0
    total_content_length: int = 0
    avg_file_length: float = 0.0
    language_distribution: Dict[str, int] = field(default_factory=dict)
    structure_distribution: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def add_warning(self, message: str):
        """添加警告信息"""
        self.warnings.append(message)
        logger.warning(message)


class DocumentProcessor:
    """
    文档处理器，用于整合文件读取、文本分块和向量操作等功能

    工程级优化（解决实体爆炸问题）：
    - 支持双 Chunker 策略：Graph 构建用大 chunk，RAG 检索用小 chunk
    - 默认使用旧 Chunker（兼容性），推荐使用专用 Chunker
    """

    def __init__(
        self,
        directory_path: str,
        chunk_size: int = CHUNK_SIZE,
        overlap: int = OVERLAP,
        chunker_mode: Literal["default", "graph", "rag", "adaptive"] = "default",
        enable_adaptive_chunking: bool = False,
        enable_structure_detection: bool = True,
        enable_language_detection: bool = True,
    ):
        """
        初始化文档处理器

        Args:
            directory_path: 文件目录路径
            chunk_size: 分块大小（仅当 chunker_mode='default' 时使用）
            overlap: 分块重叠大小（仅当 chunker_mode='default' 时使用）
            chunker_mode: Chunker 模式
                - 'default': 使用旧的 ChineseTextChunker（兼容性）
                - 'graph': 使用 GraphChunker（大 chunk，用于实体抽取）
                - 'rag': 使用 RAGChunker（小 chunk，用于向量检索）
                - 'adaptive': 使用 AdaptiveChunker（自适应切分）
            enable_adaptive_chunking: 是否启用自适应切分（覆盖 chunker_mode）
            enable_structure_detection: 是否启用结构检测（Markdown/HTML）
            enable_language_detection: 是否启用语言检测

        推荐配置：
            - Graph 构建：chunker_mode='adaptive', enable_adaptive_chunking=True
            - RAG 检索：chunker_mode='rag'
        """
        self.directory_path = directory_path
        self.file_reader = FileReader(directory_path)
        self.chunker_mode = chunker_mode
        self.enable_adaptive_chunking = enable_adaptive_chunking
        self.use_adaptive = False

        # 优先使用自适应分块器
        if enable_adaptive_chunking or chunker_mode == "adaptive":
            # 根据模式选择自适应分块器的基础模式
            base_mode = (
                "graph" if chunker_mode in ["adaptive", "graph"] else "rag" if chunker_mode == "rag" else "default"
            )
            self.chunker = create_adaptive_chunker(
                mode=base_mode,
                enable_structure_detection=enable_structure_detection,
                enable_language_detection=enable_language_detection,
            )
            self.use_adaptive = True
            logger.info(
                f"🎯 使用 AdaptiveChunker: mode={base_mode}, structure={enable_structure_detection}, language={enable_language_detection}"
            )
        elif chunker_mode == "graph":
            self.chunker = create_graph_chunker()  # 生产级配置 (900, 50)
            logger.info(f"📊 使用 GraphChunker: chunk_size=900, overlap=50 (生产级验证配置)")
        elif chunker_mode == "rag":
            self.chunker = create_rag_chunker()  # 小 chunk (400, 80)
            logger.info(f"🔍 使用 RAGChunker: chunk_size=400, overlap=80")
        else:
            # 默认模式：使用旧 Chunker（兼容性）
            self.chunker = ChineseTextChunker(chunk_size, overlap)
            logger.info(f"⚠️  使用默认 Chunker: chunk_size={chunk_size}, overlap={overlap}")
            logger.info(f"   推荐使用 chunker_mode='adaptive' 以获得更好的性能")

    def process_directory(
        self, file_extensions: Optional[List[str]] = None, recursive: bool = True, return_summary: bool = True
    ) -> Tuple[List[Dict[str, Any]], Optional[ProcessingSummary]]:
        """
        处理目录中的所有支持文件（带统计信息）

        Args:
            file_extensions: 指定要处理的文件扩展名，如不指定则处理所有支持的类型
            recursive: 是否递归处理子目录，默认为True
            return_summary: 是否返回处理摘要统计

        Returns:
            (results, summary): 处理结果列表和摘要统计（如果 return_summary=True）
        """
        # 读取文件
        file_contents = self.file_reader.read_files(file_extensions, recursive=recursive)

        # 初始化摘要统计
        summary = ProcessingSummary(total_files=len(file_contents))

        # 打印调试信息
        logger.info(f"DocumentProcessor找到的文件数量: {len(file_contents)}")
        if len(file_contents) > 0:
            logger.debug(f"文件类型: {[os.path.splitext(f[0])[1] for f in file_contents]}")

        # 处理每个文件
        results = []
        all_chunk_sizes = []

        for filepath, content in file_contents:
            file_ext = os.path.splitext(filepath)[1].lower()

            # 创建文件处理结果字典
            file_result = {
                "filepath": filepath,  # 相对路径
                "filename": os.path.basename(filepath),  # 仅文件名
                "extension": file_ext,
                "content": content,
                "content_length": len(content),
                "chunks": None,
            }

            # 对文本内容进行分块
            try:
                if self.use_adaptive:
                    # 使用自适应分块器（返回 chunks 和 stats）
                    chunks, chunk_stats = self.chunker.chunk_text(content, file_path=filepath)
                    file_result["chunks"] = chunks
                    file_result["chunk_count"] = len(chunks)
                    file_result["chunk_stats"] = chunk_stats

                    # 更新摘要统计
                    summary.total_chunks += chunk_stats["chunk_count"]
                    language = chunk_stats.get("language", "unknown")
                    structure = chunk_stats.get("structure_type", "plain")
                    summary.language_distribution[language] = summary.language_distribution.get(language, 0) + 1
                    summary.structure_distribution[structure] = summary.structure_distribution.get(structure, 0) + 1

                    # 收集块大小统计
                    if chunks:
                        chunk_sizes = [len(chunk) for chunk in chunks]
                        all_chunk_sizes.extend(chunk_sizes)
                        file_result["chunk_lengths"] = chunk_sizes
                        file_result["average_chunk_length"] = sum(chunk_sizes) / len(chunk_sizes)

                else:
                    # 使用传统分块器
                    chunks = self.chunker.chunk_text(content)
                    file_result["chunks"] = chunks
                    file_result["chunk_count"] = len(chunks)

                    # 更新摘要统计
                    summary.total_chunks += len(chunks)

                    # 计算每个块的长度
                    if chunks:
                        chunk_lengths = [len("".join(chunk)) for chunk in chunks]
                        all_chunk_sizes.extend(chunk_lengths)
                        file_result["chunk_lengths"] = chunk_lengths
                        file_result["average_chunk_length"] = sum(chunk_lengths) / len(chunk_lengths)

                summary.success_count += 1
                summary.total_content_length += len(content)

            except Exception as e:
                file_result["chunk_error"] = str(e)
                logger.error(f"分块错误 ({filepath}): {str(e)}", exc_info=True)
                summary.failed_count += 1
                summary.add_warning(f"文件 {filepath} 分块失败: {e}")

            results.append(file_result)

        # 计算摘要统计
        if all_chunk_sizes:
            summary.avg_chunk_size = sum(all_chunk_sizes) / len(all_chunk_sizes)
            summary.min_chunk_size = min(all_chunk_sizes)
            summary.max_chunk_size = max(all_chunk_sizes)

        if summary.success_count > 0:
            summary.avg_file_length = summary.total_content_length / summary.success_count

        # 检查并添加警告
        if summary.avg_chunk_size > 1200:
            summary.add_warning(
                f"平均块大小 ({summary.avg_chunk_size:.0f}) 过大，可能导致LLM处理困难。"
                f"建议使用 chunker_mode='rag' 或调小 chunk_size。"
            )

        if summary.min_chunk_size < 50:
            summary.add_warning(
                f"最小块大小 ({summary.min_chunk_size}) 过小，可能产生大量无意义的碎片块。"
                f"建议启用自适应分块 (enable_adaptive_chunking=True)。"
            )

        # 打印摘要
        logger.info(f"\n📊 处理摘要:")
        logger.info(f"  - 总文件数: {summary.total_files}")
        logger.info(f"  - 成功: {summary.success_count}, 失败: {summary.failed_count}")
        logger.info(f"  - 总块数: {summary.total_chunks}")
        logger.info(f"  - 平均块大小: {summary.avg_chunk_size:.1f} tokens")
        logger.info(f"  - 块大小范围: [{summary.min_chunk_size}, {summary.max_chunk_size}]")

        if self.use_adaptive and summary.language_distribution:
            logger.info(f"  - 语言分布: {summary.language_distribution}")
            logger.info(f"  - 结构分布: {summary.structure_distribution}")

        if summary.warnings:
            logger.warning(f"  ⚠️  {len(summary.warnings)} 个警告:")
            for warning in summary.warnings:
                logger.warning(f"    - {warning}")

        if return_summary:
            return results, summary
        else:
            return results, None

    def get_file_stats(self, file_extensions: Optional[List[str]] = None, recursive: bool = True) -> Dict[str, Any]:
        """
        获取目录中文件的统计信息

        Args:
            file_extensions: 指定要统计的文件扩展名，如不指定则处理所有支持的类型
            recursive: 是否递归统计子目录，默认为True

        Returns:
            Dict: 文件统计信息
        """
        # 读取文件
        file_contents = self.file_reader.read_files(file_extensions, recursive=recursive)

        # 统计每种扩展名的文件数量
        extension_counts = {}
        total_content_length = 0

        # 统计子目录数量
        directories = set()

        for filepath, content in file_contents:
            ext = os.path.splitext(filepath)[1].lower()
            extension_counts[ext] = extension_counts.get(ext, 0) + 1

            # 记录文件所在的子目录
            dirpath = os.path.dirname(filepath)
            if dirpath:  # 非空表示在子目录中
                directories.add(dirpath)

            if content is not None:
                total_content_length += len(content)
            else:
                print(f"警告: 文件 {filepath} 的内容为None")

        return {
            "total_files": len(file_contents),
            "extension_counts": extension_counts,
            "total_content_length": total_content_length,
            "average_file_length": total_content_length / len(file_contents) if file_contents else 0,
            "directories": list(directories),
            "directory_count": len(directories),
        }

    def get_extension_type(self, extension: str) -> str:
        """
        获取文件扩展名对应的文档类型

        Args:
            extension: 文件扩展名（包括'.'，如'.pdf'）

        Returns:
            str: 文档类型描述
        """
        extension_types = {
            ".txt": "文本文件",
            ".pdf": "PDF文档",
            ".md": "Markdown文档",
            ".doc": "Word文档",
            ".docx": "Word文档",
            ".csv": "CSV数据文件",
            ".json": "JSON数据文件",
            ".yaml": "YAML配置文件",
            ".yml": "YAML配置文件",
        }

        return extension_types.get(extension.lower(), "未知类型")


if __name__ == "__main__":
    # 创建文档处理器
    processor = DocumentProcessor(FILES_DIR)

    # 列出目录中的所有文件
    print(f"目录 {FILES_DIR} 及其子目录中的所有文件:")
    all_files = processor.file_reader.list_all_files(recursive=True)
    for filepath in all_files:
        print(f"  {filepath}")

    # 获取文件统计信息
    stats = processor.get_file_stats(recursive=True)
    print("目录文件统计:")
    print(f"总文件数: {stats['total_files']}")
    print(f"子目录数: {stats['directory_count']}")
    if stats["directory_count"] > 0:
        print("子目录列表:")
        for directory in stats["directories"]:
            print(f"  {directory}")

    print("文件类型分布:")
    for ext, count in stats["extension_counts"].items():
        print(f"  {ext} ({processor.get_extension_type(ext)}): {count}文件")
    print(f"总文本长度: {stats['total_content_length']}字符")
    print(f"平均文件长度: {stats['average_file_length']:.2f}字符")

    # 处理所有文件
    print("\n开始处理所有文件...")
    results = processor.process_directory(recursive=True)

    # 打印处理结果摘要
    for result in results:
        print(f"\n文件: {result['filepath']}")
        print(f"类型: {processor.get_extension_type(result['extension'])}")
        print(f"内容长度: {result['content_length']}字符")

        if result.get("chunks"):
            print(f"分块数量: {result['chunk_count']}")
            print(f"平均分块长度: {result['average_chunk_length']:.2f}字符")
        else:
            print(f"分块失败: {result.get('chunk_error', '未知错误')}")
