"""
音频处理器 - ASR支持

使用 OpenAI Whisper 将音频转换为文字。
"""

import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class AudioProcessor:
    """音频处理器，使用ASR (Automatic Speech Recognition) 转录音频"""

    def __init__(self, model_size: str = "base", device: str = "cpu"):
        """
        初始化音频处理器

        Args:
            model_size: Whisper模型大小 (tiny, base, small, medium, large)
                - tiny: ~39M, 最快但准确度最低
                - base: ~74M, 平衡速度和准确度 (推荐)
                - small: ~244M, 较好准确度
                - medium: ~769M, 更好准确度
                - large: ~1550M, 最佳准确度但最慢
            device: 设备类型 (cpu/cuda)
        """
        self.model_size = model_size
        self.device = device
        self._model = None
        self._initialized = False

    def _init_whisper(self):
        """延迟初始化Whisper模型"""
        if self._initialized:
            return

        try:
            import whisper

            logger.info(f"Loading Whisper model: {self.model_size} on {self.device}")

            self._model = whisper.load_model(self.model_size, device=self.device)

            self._initialized = True
            logger.info("Whisper model loaded successfully")

        except ImportError:
            logger.error("Whisper not installed. Please install with: pip install openai-whisper")
            raise
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            raise

    def process_audio(
        self, audio_path: str, language: Optional[str] = None, task: str = "transcribe"
    ) -> Tuple[str, Optional[dict]]:
        """
        处理音频文件，转录为文字

        Args:
            audio_path: 音频文件路径
            language: 语言代码 (如 'zh', 'en')，None则自动检测
            task: 任务类型 ('transcribe' 转录, 'translate' 翻译成英文)

        Returns:
            Tuple[str, dict]: (转录文字, 元数据)
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # 延迟初始化Whisper
        self._init_whisper()

        try:
            # 执行转录
            logger.info(f"Transcribing {audio_path}...")

            result = self._model.transcribe(audio_path, language=language, task=task, verbose=False)

            text = result.get("text", "").strip()
            detected_language = result.get("language", "unknown")

            # 提取时间戳信息（segments）
            segments = result.get("segments", [])
            segment_count = len(segments)

            metadata = {
                "detected_language": detected_language,
                "segment_count": segment_count,
                "duration_seconds": segments[-1]["end"] if segments else 0,
                "source_audio": os.path.basename(audio_path),
                "model_size": self.model_size,
            }

            logger.info(f"ASR completed for {audio_path}: " f"{len(text)} characters, language: {detected_language}")

            return text, metadata

        except Exception as e:
            logger.error(f"ASR processing failed for {audio_path}: {e}")
            return "", {"error": str(e)}

    def batch_process(self, audio_paths: list, language: Optional[str] = None) -> list:
        """
        批量处理多个音频文件

        Args:
            audio_paths: 音频文件路径列表
            language: 语言代码

        Returns:
            list: [(文件名, 转录文字, 元数据), ...]
        """
        results = []

        for audio_path in audio_paths:
            try:
                text, metadata = self.process_audio(audio_path, language=language)
                filename = os.path.basename(audio_path)
                results.append((filename, text, metadata))
            except Exception as e:
                logger.error(f"Failed to process {audio_path}: {e}")
                results.append((os.path.basename(audio_path), "", {"error": str(e)}))

        return results

    @staticmethod
    def is_supported_format(file_path: str) -> bool:
        """
        检查文件是否为支持的音频格式

        Whisper支持的格式: mp3, mp4, mpeg, mpga, m4a, wav, webm

        Args:
            file_path: 文件路径

        Returns:
            bool: 是否支持
        """
        supported_extensions = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg", ".flac"}
        _, ext = os.path.splitext(file_path.lower())
        return ext in supported_extensions
