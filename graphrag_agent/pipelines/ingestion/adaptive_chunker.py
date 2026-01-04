"""
自适应文本分块器 (Adaptive Text Chunker)

解决问题：
1. 基于内容结构的自适应切分（Markdown标题、HTML标签等）
2. 动态调整块大小（合并小块、拆分大块）
3. 多语言支持（中文/英文自动检测）
4. 统计信息收集（用于上层策略调整）

架构设计：
- StructuredChunker: 基于 Markdown/HTML 结构切分
- AdaptiveChunker: 动态调整块大小
- LanguageDetector: 语言检测与切分器选择
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from graphrag_agent.pipelines.ingestion.specialized_chunkers import GraphChunker, RAGChunker
from graphrag_agent.pipelines.ingestion.text_chunker import ChineseTextChunker

logger = logging.getLogger(__name__)


class LanguageDetector:
    """语言检测器"""

    @staticmethod
    def detect_language(text: str) -> str:
        """
        检测文本主要语言

        Args:
            text: 输入文本

        Returns:
            'zh' (中文) 或 'en' (英文) 或 'mixed' (混合)
        """
        if not text or len(text) < 10:
            return "en"

        # 统计中文字符数量
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        total_chars = len(text.strip())

        if total_chars == 0:
            return "en"

        chinese_ratio = chinese_chars / total_chars

        # 判断语言
        if chinese_ratio > 0.3:
            return "zh"  # 中文
        elif chinese_ratio > 0.1:
            return "mixed"  # 混合
        else:
            return "en"  # 英文

    @staticmethod
    def estimate_token_count(text: str, language: str) -> int:
        """
        估算文本的 token 数量

        Args:
            text: 输入文本
            language: 语言类型

        Returns:
            估算的 token 数量
        """
        if language == "zh" or language == "mixed":
            # 中文：1个字符约等于1个token
            return len(text)
        else:
            # 英文：平均4个字符约等于1个token
            return len(text) // 4


class StructuredChunker:
    """基于内容结构的分块器"""

    def __init__(self, min_chunk_size: int = 100, max_chunk_size: int = 1500):
        """
        初始化结构化分块器

        Args:
            min_chunk_size: 最小块大小（字符）
            max_chunk_size: 最大块大小（字符）
        """
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size

    def detect_structure_type(self, text: str) -> str:
        """
        检测文本结构类型

        Args:
            text: 输入文本

        Returns:
            'markdown', 'html', 或 'plain'
        """
        # 检测 Markdown 标题
        if re.search(r"^#{1,6}\s+.+$", text, re.MULTILINE):
            return "markdown"

        # 检测 HTML 标签
        if re.search(r"<[^>]+>", text):
            return "html"

        return "plain"

    def split_by_markdown_headers(self, text: str) -> List[Dict[str, Any]]:
        """
        按 Markdown 标题切分文本

        Args:
            text: Markdown 文本

        Returns:
            切分后的段落列表，每个段落包含标题层级和内容
        """
        sections = []
        current_section = {"level": 0, "title": "", "content": ""}

        lines = text.split("\n")
        for line in lines:
            # 检测标题
            header_match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if header_match:
                # 保存当前section
                if current_section["content"].strip():
                    sections.append(current_section.copy())

                # 开始新section
                level = len(header_match.group(1))
                title = header_match.group(2).strip()
                current_section = {"level": level, "title": title, "content": ""}
            else:
                current_section["content"] += line + "\n"

        # 添加最后一个section
        if current_section["content"].strip():
            sections.append(current_section)

        return sections

    def merge_small_sections(self, sections: List[Dict[str, Any]]) -> List[str]:
        """
        合并过小的 section

        Args:
            sections: 段落列表

        Returns:
            合并后的文本块列表
        """
        merged_chunks = []
        current_chunk = ""
        current_title = ""

        for section in sections:
            title = section.get("title", "")
            content = section.get("content", "")
            full_text = f"## {title}\n{content}" if title else content

            # 如果当前chunk为空，直接添加
            if not current_chunk:
                current_chunk = full_text
                current_title = title
                continue

            # 检查是否需要合并
            combined_length = len(current_chunk) + len(full_text)

            if combined_length < self.min_chunk_size:
                # 合并到当前chunk
                current_chunk += "\n\n" + full_text
            elif len(current_chunk) < self.min_chunk_size:
                # 当前chunk太小，必须合并
                current_chunk += "\n\n" + full_text
                merged_chunks.append(current_chunk)
                current_chunk = ""
            else:
                # 当前chunk足够大，保存并开始新chunk
                merged_chunks.append(current_chunk)
                current_chunk = full_text

        # 添加最后一个chunk
        if current_chunk.strip():
            merged_chunks.append(current_chunk)

        return merged_chunks

    def split_large_chunks(self, chunks: List[str]) -> List[str]:
        """
        拆分过大的块

        Args:
            chunks: 文本块列表

        Returns:
            拆分后的文本块列表
        """
        result = []
        for chunk in chunks:
            if len(chunk) <= self.max_chunk_size:
                result.append(chunk)
            else:
                # 按段落拆分
                paragraphs = chunk.split("\n\n")
                current_split = ""

                for para in paragraphs:
                    if len(current_split) + len(para) + 2 > self.max_chunk_size:
                        if current_split:
                            result.append(current_split)
                        current_split = para
                    else:
                        if current_split:
                            current_split += "\n\n" + para
                        else:
                            current_split = para

                if current_split:
                    result.append(current_split)

        return result

    def chunk_text(self, text: str) -> List[str]:
        """
        基于结构切分文本

        Args:
            text: 输入文本

        Returns:
            切分后的文本块列表
        """
        structure_type = self.detect_structure_type(text)
        logger.debug(f"检测到文本结构类型: {structure_type}")

        if structure_type == "markdown":
            # Markdown 结构化切分
            sections = self.split_by_markdown_headers(text)
            chunks = self.merge_small_sections(sections)
            chunks = self.split_large_chunks(chunks)
            logger.debug(f"Markdown结构化切分: {len(sections)} sections → {len(chunks)} chunks")
            return chunks
        else:
            # 纯文本切分（按段落）
            paragraphs = text.split("\n\n")
            chunks = []
            current_chunk = ""

            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue

                if len(current_chunk) + len(para) + 2 > self.max_chunk_size:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = para
                else:
                    if current_chunk:
                        current_chunk += "\n\n" + para
                    else:
                        current_chunk = para

            if current_chunk:
                chunks.append(current_chunk)

            return chunks


class AdaptiveChunker:
    """自适应分块器 - 整合多种策略"""

    def __init__(
        self,
        mode: str = "default",  # 'default', 'graph', 'rag'
        min_chunk_size: int = 100,
        max_chunk_size: int = 1500,
        enable_structure_detection: bool = True,
        enable_language_detection: bool = True,
    ):
        """
        初始化自适应分块器

        Args:
            mode: 分块模式 ('default', 'graph', 'rag')
            min_chunk_size: 最小块大小（字符）
            max_chunk_size: 最大块大小（字符）
            enable_structure_detection: 是否启用结构检测
            enable_language_detection: 是否启用语言检测
        """
        self.mode = mode
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.enable_structure_detection = enable_structure_detection
        self.enable_language_detection = enable_language_detection

        # 初始化各类切分器
        self.structured_chunker = StructuredChunker(min_chunk_size=min_chunk_size, max_chunk_size=max_chunk_size)
        self.language_detector = LanguageDetector()

        # 初始化专用切分器
        if mode == "graph":
            self.graph_chunker = GraphChunker(chunk_size=900, overlap=50)
        elif mode == "rag":
            self.rag_chunker = RAGChunker(chunk_size=400, overlap=80)
        else:
            self.default_chunker = ChineseTextChunker(chunk_size=500, overlap=100)

        logger.info(
            f"初始化 AdaptiveChunker: mode={mode}, structure={enable_structure_detection}, language={enable_language_detection}"
        )

    def chunk_text(self, text: str, file_path: Optional[str] = None) -> Tuple[List[List[str]], Dict[str, Any]]:
        """
        自适应文本切分（主入口）

        Args:
            text: 输入文本
            file_path: 文件路径（用于日志）

        Returns:
            (chunks, stats): 切分后的块列表和统计信息
        """
        stats = {
            "original_length": len(text),
            "language": "unknown",
            "structure_type": "plain",
            "chunk_count": 0,
            "avg_chunk_size": 0,
            "min_chunk_size": 0,
            "max_chunk_size": 0,
            "strategy_used": self.mode,
        }

        # 1. 语言检测
        if self.enable_language_detection:
            language = self.language_detector.detect_language(text)
            stats["language"] = language
            logger.debug(f"语言检测结果: {language}")
        else:
            language = "zh"  # 默认中文

        # 2. 结构检测与切分
        if self.enable_structure_detection:
            structure_type = self.structured_chunker.detect_structure_type(text)
            stats["structure_type"] = structure_type

            if structure_type in ["markdown", "html"]:
                # 使用结构化切分
                string_chunks = self.structured_chunker.chunk_text(text)
                logger.debug(f"使用结构化切分: {len(string_chunks)} chunks")

                # 转换为 token 列表格式（与现有系统兼容）
                if self.mode == "graph":
                    token_chunks = [self.graph_chunker._safe_tokenize(chunk) for chunk in string_chunks]
                elif self.mode == "rag":
                    token_chunks = [self.rag_chunker._safe_tokenize(chunk) for chunk in string_chunks]
                else:
                    token_chunks = [self.default_chunker._safe_tokenize(chunk) for chunk in string_chunks]

                # 合并过小的块
                token_chunks = self._merge_small_token_chunks(token_chunks)

                # 更新统计信息
                stats["chunk_count"] = len(token_chunks)
                if token_chunks:
                    chunk_sizes = [len(chunk) for chunk in token_chunks]
                    stats["avg_chunk_size"] = sum(chunk_sizes) / len(chunk_sizes)
                    stats["min_chunk_size"] = min(chunk_sizes)
                    stats["max_chunk_size"] = max(chunk_sizes)

                return token_chunks, stats

        # 3. 使用传统切分器
        if self.mode == "graph":
            token_chunks = self.graph_chunker.chunk_text(text)
        elif self.mode == "rag":
            token_chunks = self.rag_chunker.chunk_text(text)
        else:
            token_chunks = self.default_chunker.chunk_text(text)

        # 4. 动态调整块大小
        token_chunks = self._merge_small_token_chunks(token_chunks)

        # 5. 更新统计信息
        stats["chunk_count"] = len(token_chunks)
        if token_chunks:
            chunk_sizes = [len(chunk) for chunk in token_chunks]
            stats["avg_chunk_size"] = sum(chunk_sizes) / len(chunk_sizes)
            stats["min_chunk_size"] = min(chunk_sizes)
            stats["max_chunk_size"] = max(chunk_sizes)

        return token_chunks, stats

    def _merge_small_token_chunks(self, chunks: List[List[str]]) -> List[List[str]]:
        """
        合并过小的 token 块

        Args:
            chunks: token 块列表

        Returns:
            合并后的 token 块列表
        """
        if not chunks:
            return chunks

        # 根据模式设置最小块大小
        if self.mode == "graph":
            min_tokens = 200  # Graph模式：至少200 tokens
        elif self.mode == "rag":
            min_tokens = 100  # RAG模式：至少100 tokens
        else:
            min_tokens = 50  # 默认模式：至少50 tokens

        merged = []
        current_chunk = []

        for chunk in chunks:
            if len(current_chunk) + len(chunk) < min_tokens:
                # 合并到当前块
                current_chunk.extend(chunk)
            else:
                # 保存当前块，开始新块
                if current_chunk:
                    merged.append(current_chunk)
                current_chunk = chunk

        # 添加最后一个块
        if current_chunk:
            # 如果最后一个块太小，合并到前一个块
            if len(current_chunk) < min_tokens and merged:
                merged[-1].extend(current_chunk)
            else:
                merged.append(current_chunk)

        logger.debug(f"合并小块: {len(chunks)} → {len(merged)} chunks")
        return merged


# 工厂函数
def create_adaptive_chunker(
    mode: str = "default", enable_structure_detection: bool = True, enable_language_detection: bool = True
) -> AdaptiveChunker:
    """
    创建自适应分块器实例

    Args:
        mode: 分块模式 ('default', 'graph', 'rag')
        enable_structure_detection: 是否启用结构检测
        enable_language_detection: 是否启用语言检测

    Returns:
        AdaptiveChunker 实例
    """
    return AdaptiveChunker(
        mode=mode,
        enable_structure_detection=enable_structure_detection,
        enable_language_detection=enable_language_detection,
    )


if __name__ == "__main__":
    # 测试代码
    markdown_text = """
# 国家奖学金管理办法

## 第一章 总则

国家奖学金是为了激励普通本科高校、高等职业学校和高等专科学校学生勤奋学习。

## 第二章 评选条件

申请国家奖学金的学生需要满足以下条件：

### 2.1 基本条件

学生必须热爱社会主义祖国，拥护中国共产党的领导。

### 2.2 学业要求

学习成绩优异，社会实践、创新能力、综合素质等方面特别突出。
"""

    chunker = create_adaptive_chunker(mode="graph", enable_structure_detection=True)
    chunks, stats = chunker.chunk_text(markdown_text)

    print(f"\n📊 切分统计:")
    print(f"  - 语言: {stats['language']}")
    print(f"  - 结构类型: {stats['structure_type']}")
    print(f"  - Chunk数量: {stats['chunk_count']}")
    print(f"  - 平均大小: {stats['avg_chunk_size']:.1f} tokens")
    print(f"  - 大小范围: [{stats['min_chunk_size']}, {stats['max_chunk_size']}]")
