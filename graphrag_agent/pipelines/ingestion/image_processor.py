"""
图像处理器 - OCR支持

使用 PaddleOCR 提取图像中的文字内容。
"""

import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class ImageProcessor:
    """图像处理器，使用OCR提取图片中的文字"""

    def __init__(self, use_gpu: bool = False, lang: str = "ch"):
        """
        初始化图像处理器

        Args:
            use_gpu: 是否使用GPU加速
            lang: 语言类型，'ch'为中文,'en'为英文,'chinese_cht'为繁体中文
        """
        self.use_gpu = use_gpu
        self.lang = lang
        self._ocr = None
        self._initialized = False

    def _init_ocr(self):
        """延迟初始化OCR引擎（避免在不需要时加载模型）"""
        if self._initialized:
            return

        try:
            from paddleocr import PaddleOCR

            logger.info(f"Initializing PaddleOCR with language: {self.lang}, GPU: {self.use_gpu}")

            self._ocr = PaddleOCR(
                use_angle_cls=True, lang=self.lang, use_gpu=self.use_gpu, show_log=False  # 禁用详细日志
            )

            self._initialized = True
            logger.info("PaddleOCR initialized successfully")

        except ImportError:
            logger.error("PaddleOCR not installed. Please install with: pip install paddleocr paddlepaddle")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize PaddleOCR: {e}")
            raise

    def process_image(self, image_path: str) -> Tuple[str, Optional[dict]]:
        """
        处理图像文件，提取文字内容

        Args:
            image_path: 图像文件路径

        Returns:
            Tuple[str, dict]: (提取的文字内容, OCR元数据)
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        # 延迟初始化OCR
        self._init_ocr()

        try:
            # 执行OCR识别
            result = self._ocr.ocr(image_path, cls=True)

            if not result or not result[0]:
                logger.warning(f"No text detected in image: {image_path}")
                return "", {"text_count": 0, "confidence": 0}

            # 提取所有文字和置信度
            text_blocks = []
            confidences = []

            for line in result[0]:
                if line and len(line) >= 2:
                    text = line[1][0]  # 文字内容
                    confidence = line[1][1]  # 置信度
                    text_blocks.append(text)
                    confidences.append(confidence)

            # 拼接文字
            extracted_text = "\n".join(text_blocks)

            # 计算平均置信度
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0

            metadata = {
                "text_count": len(text_blocks),
                "avg_confidence": round(avg_confidence, 3),
                "source_image": os.path.basename(image_path),
            }

            logger.info(
                f"OCR completed for {image_path}: {len(text_blocks)} lines, " f"confidence: {avg_confidence:.2f}"
            )

            return extracted_text, metadata

        except Exception as e:
            logger.error(f"OCR processing failed for {image_path}: {e}")
            return "", {"error": str(e)}

    def batch_process(self, image_paths: list) -> list:
        """
        批量处理多个图像

        Args:
            image_paths: 图像文件路径列表

        Returns:
            list: [(文件名, 文字内容, 元数据), ...]
        """
        results = []

        for image_path in image_paths:
            try:
                text, metadata = self.process_image(image_path)
                filename = os.path.basename(image_path)
                results.append((filename, text, metadata))
            except Exception as e:
                logger.error(f"Failed to process {image_path}: {e}")
                results.append((os.path.basename(image_path), "", {"error": str(e)}))

        return results

    @staticmethod
    def is_supported_format(file_path: str) -> bool:
        """
        检查文件是否为支持的图像格式

        Args:
            file_path: 文件路径

        Returns:
            bool: 是否支持
        """
        supported_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}
        _, ext = os.path.splitext(file_path.lower())
        return ext in supported_extensions
