import codecs
import os
import sys
import logging
import importlib.util
from typing import List, Tuple, Dict, Optional
import PyPDF2
from docx import Document
import csv
import json
import yaml
import logging
try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

from graphrag_agent.config.settings import FILES_DIR

# 配置日志
logger = logging.getLogger(__name__)


class FileReadError(Exception):
    """文件读取失败异常"""
    def __init__(self, message: str, file_path: str = None, original_error: Exception = None):
        self.file_path = file_path
        self.original_error = original_error
        super().__init__(message)


class FileReader:
    """
    文件读取器，支持多种文件格式：
    - TXT (文本文件)
    - PDF (PDF文档)
    - MD (Markdown文件)
    - DOCX (Word文档)
    - DOC (旧版Word文档)
    - CSV (CSV文件)
    - JSON (JSON文件)
    - YAML/YML (YAML文件)
    - PNG/JPG/JPEG (图像文件 - 需要OCR)
    - MP3/WAV/M4A (音频文件 - 需要ASR)
    """

    def __init__(self, directory_path: str, enable_ocr: bool = False, enable_asr: bool = False):
        """
        初始化文件读取器

        Args:
            directory_path: 文件目录路径
            enable_ocr: 是否启用OCR图像识别
            enable_asr: 是否启用ASR语音识别
        """
        self.directory_path = directory_path
        self.enable_ocr = enable_ocr
        self.enable_asr = enable_asr
        self._image_processor = None
        self._audio_processor = None
        
    def read_files(self, file_extensions: Optional[List[str]] = None, recursive: bool = True) -> List[Tuple[str, str]]:
        """
        读取指定扩展名的文件
        
        Args:
            file_extensions: 文件扩展名列表，如 ['.txt', '.pdf']，如不指定则读取所有支持的格式
            recursive: 是否递归读取子目录，默认为True
            
        Returns:
            List[Tuple[str, str]]: 文件名和内容的元组列表
        """
        supported_extensions = {
            '.txt': self._read_txt,
            '.pdf': self._read_pdf,
            '.md': self._read_markdown,
            '.docx': self._read_docx,
            '.doc': self._read_doc,
            '.csv': self._read_csv,
            '.json': self._read_json,
            '.yaml': self._read_yaml,
            '.yml': self._read_yaml,
            # 图像文件 (需要OCR)
            '.png': self._read_image,
            '.jpg': self._read_image,
            '.jpeg': self._read_image,
            '.bmp': self._read_image,
            '.tiff': self._read_image,
            '.tif': self._read_image,
            # 音频文件 (需要ASR)
            '.mp3': self._read_audio,
            '.wav': self._read_audio,
            '.m4a': self._read_audio,
            '.mp4': self._read_audio,  # 音频格式MP4
            '.ogg': self._read_audio,
            '.flac': self._read_audio,
        }
        
        # 如未指定扩展名，则使用所有支持的扩展名
        if file_extensions is None:
            file_extensions = list(supported_extensions.keys())

        results = []
        failed_files = []  # 记录失败的文件
        try:
            if recursive:
                # 递归读取所有文件
                results, failed_files = self._read_files_recursive(self.directory_path, file_extensions, supported_extensions)
                logger.info(f"递归读取目录完成，成功读取 {len(results)} 个文件，失败 {len(failed_files)} 个文件")
            else:
                # 仅读取当前目录的文件
                all_filenames = os.listdir(self.directory_path)
                logger.info(f"当前目录中共有 {len(all_filenames)} 个文件")

                results, failed_files = self._process_files_in_dir(self.directory_path, all_filenames, file_extensions, supported_extensions)
                logger.info(f"成功读取 {len(results)} 个文件，失败 {len(failed_files)} 个文件")
        except Exception as e:
            logger.error(f"列出目录 {self.directory_path} 中的文件时出错: {str(e)}", exc_info=True)

        # 记录失败的文件到日志
        if failed_files:
            logger.warning(f"以下 {len(failed_files)} 个文件读取失败，已跳过:")
            for failed_file, error in failed_files:
                logger.warning(f"  ❌ {failed_file}: {error}")

        return results
    
    def _read_files_recursive(self, root_dir: str, file_extensions: List[str], supported_extensions: Dict) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        """
        递归读取目录及其子目录中的文件

        Args:
            root_dir: 当前处理的目录路径
            file_extensions: 要处理的文件扩展名列表
            supported_extensions: 支持的文件扩展名及对应处理函数

        Returns:
            Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
                - 成功读取的文件列表 (文件名, 内容)
                - 失败的文件列表 (文件名, 错误信息)
        """
        results = []
        failed_files = []

        try:
            # 遍历目录内容
            for item in os.listdir(root_dir):
                item_path = os.path.join(root_dir, item)

                # 如果是目录，递归处理
                if os.path.isdir(item_path):
                    logger.debug(f"递归进入子目录: {item_path}")
                    sub_results, sub_failed = self._read_files_recursive(item_path, file_extensions, supported_extensions)
                    results.extend(sub_results)
                    failed_files.extend(sub_failed)

                # 如果是文件，处理文件
                elif os.path.isfile(item_path):
                    file_ext = os.path.splitext(item)[1].lower()

                    if file_ext in file_extensions:
                        # 获取相对于根目录的路径
                        rel_path = os.path.relpath(item_path, self.directory_path)

                        logger.debug(f"处理文件: {rel_path} (类型: {file_ext})")

                        # 使用对应的读取方法处理文件
                        if file_ext in supported_extensions:
                            try:
                                content = supported_extensions[file_ext](item_path)
                                # 存储相对路径而不是仅文件名，以便区分不同目录中的同名文件
                                results.append((rel_path, content))
                                logger.debug(f"✅ 成功读取文件: {rel_path}, 内容长度: {len(content)}")
                            except FileReadError as e:
                                # 捕获自定义异常，记录失败
                                error_msg = str(e.original_error) if e.original_error else str(e)
                                failed_files.append((rel_path, error_msg))
                                logger.warning(f"❌ 读取文件失败 [跳过]: {rel_path}, 原因: {error_msg}")
                            except Exception as e:
                                # 捕获其他未预期的异常
                                failed_files.append((rel_path, str(e)))
                                logger.error(f"❌ 读取文件时发生未预期错误 [跳过]: {rel_path}, 原因: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"列出目录 {root_dir} 中的文件时出错: {str(e)}", exc_info=True)

        return results, failed_files
    
    def _process_files_in_dir(self, directory: str, filenames: List[str], file_extensions: List[str],
                              supported_extensions: Dict) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        """
        处理指定目录中的文件（不递归）

        Args:
            directory: 目录路径
            filenames: 文件名列表
            file_extensions: 要处理的文件扩展名列表
            supported_extensions: 支持的文件扩展名及对应处理函数

        Returns:
            Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
                - 成功读取的文件列表 (文件名, 内容)
                - 失败的文件列表 (文件名, 错误信息)
        """
        results = []
        failed_files = []

        for filename in filenames:
            file_ext = os.path.splitext(filename)[1].lower()

            if file_ext in file_extensions:
                file_path = os.path.join(directory, filename)
                logger.debug(f"处理文件: {filename} (类型: {file_ext})")

                # 使用对应的读取方法处理文件
                if file_ext in supported_extensions:
                    try:
                        content = supported_extensions[file_ext](file_path)
                        results.append((filename, content))
                        logger.debug(f"✅ 成功读取文件: {filename}, 内容长度: {len(content)}")
                    except FileReadError as e:
                        error_msg = str(e.original_error) if e.original_error else str(e)
                        failed_files.append((filename, error_msg))
                        logger.warning(f"❌ 读取文件失败 [跳过]: {filename}, 原因: {error_msg}")
                    except Exception as e:
                        failed_files.append((filename, str(e)))
                        logger.error(f"❌ 读取文件时发生未预期错误 [跳过]: {filename}, 原因: {e}", exc_info=True)

        return results, failed_files
    
    def _read_txt(self, file_path: str) -> str:
        """读取TXT文件"""
        try:
            with codecs.open(file_path, 'r', encoding='utf-8', errors='replace') as file:
                content = file.read()
            return content
        except Exception as e:
            logger.debug(f"UTF-8 编码读取失败，尝试其他编码: {os.path.basename(file_path)}")
            # 尝试使用其他编码
            try:
                with open(file_path, 'rb') as f:
                    raw_data = f.read(10240)  # 读取前10KB
                    try:
                        import chardet
                        result = chardet.detect(raw_data)
                        encoding = result['encoding'] if result['encoding'] else 'gbk'
                    except:
                        encoding = 'gbk'  # 如果chardet不可用，默认使用gbk

                with codecs.open(file_path, 'r', encoding=encoding, errors='replace') as file:
                    content = file.read()
                logger.debug(f"使用 {encoding} 编码成功读取文件")
                return content
            except Exception as e2:
                # 所有编码尝试失败，抛出异常
                raise FileReadError(
                    f"无法读取TXT文件（尝试了UTF-8和{encoding}编码）",
                    file_path=file_path,
                    original_error=e2
                )
            
    def _read_pdf(self, file_path: str) -> str:
        """读取PDF文件"""
        try:
            text = ""
            failed_pages = []
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                total_pages = len(pdf_reader.pages)

                for page_num in range(total_pages):
                    try:
                        page = pdf_reader.pages[page_num]
                        page_text = page.extract_text() or ""
                        text += page_text + "\n\n"
                    except Exception as e:
                        failed_pages.append(page_num + 1)
                        logger.warning(f"PDF第 {page_num+1} 页读取失败: {e}")

            # 如果所有页都失败，抛出异常
            if len(failed_pages) == total_pages:
                raise FileReadError(
                    f"PDF文件所有 {total_pages} 页均无法读取",
                    file_path=file_path
                )

            # 如果部分页失败，记录警告但返回成功读取的内容
            if failed_pages:
                logger.warning(f"PDF部分页读取失败: 第 {failed_pages} 页 (共{total_pages}页)")

            return text
        except FileReadError:
            raise  # 重新抛出自定义异常
        except Exception as e:
            raise FileReadError(
                f"无法打开或读取PDF文件",
                file_path=file_path,
                original_error=e
            )
    
    def _read_markdown(self, file_path: str) -> str:
        """读取Markdown文件"""
        try:
            with codecs.open(file_path, 'r', encoding='utf-8', errors='replace') as file:
                md_content = file.read()
                return md_content
        except Exception as e:
            raise FileReadError(
                f"无法读取Markdown文件",
                file_path=file_path,
                original_error=e
            )
    
    def _read_docx(self, file_path: str) -> str:
        """读取Word文档(.docx)"""
        try:
            doc = Document(file_path)
            full_text = []
            for para in doc.paragraphs:
                full_text.append(para.text)
            return '\n'.join(full_text)
        except Exception as e:
            raise FileReadError(
                f"无法读取Word文档(.docx)",
                file_path=file_path,
                original_error=e
            )
            
    def _read_doc(self, file_path: str) -> str:
        """
        读取旧版Word文档(.doc)
        使用平台检测优化导入，失败时抛出异常
        """
        content = ""
        tried_methods = []

        # 方法1: Windows平台尝试使用win32com
        if sys.platform == "win32":
            # 检查win32com是否可用
            if importlib.util.find_spec("win32com") is not None:
                try:
                    import win32com.client

                    logger.debug(f"尝试使用win32com读取.doc文件: {os.path.basename(file_path)}")
                    word = win32com.client.Dispatch("Word.Application")
                    word.Visible = False

                    doc_abs_path = os.path.abspath(file_path)
                    doc = word.Documents.Open(doc_abs_path)
                    content = doc.Content.Text
                    doc.Close()
                    word.Quit()

                    if content and content.strip():
                        logger.debug(f"使用win32com成功读取.doc文件")
                        return content
                    tried_methods.append("win32com (无内容)")
                except Exception as e:
                    tried_methods.append(f"win32com ({e})")
                    logger.debug(f"使用win32com读取.doc失败: {str(e)}")
            else:
                tried_methods.append("win32com (未安装)")
        else:
            logger.debug(f"非Windows平台 ({sys.platform})，跳过win32com")

        # 方法2: 尝试使用textract (跨平台)
        if importlib.util.find_spec("textract") is not None:
            try:
                import textract
                logger.debug(f"尝试使用textract读取.doc文件: {os.path.basename(file_path)}")
                content = textract.process(file_path).decode('utf-8')

                if content and content.strip():
                    logger.debug(f"使用textract成功读取.doc文件")
                    return content
                tried_methods.append("textract (无内容)")
            except Exception as e:
                tried_methods.append(f"textract ({e})")
                logger.debug(f"使用textract读取.doc失败: {str(e)}")
        else:
            tried_methods.append("textract (未安装)")

        # 方法3: 尝试使用python-docx (不完全兼容.doc，但有时可以部分读取)
        try:
            from docx import Document
            logger.debug(f"尝试使用python-docx读取.doc文件: {os.path.basename(file_path)}")
            doc = Document(file_path)
            full_text = []
            for para in doc.paragraphs:
                full_text.append(para.text)
            content = '\n'.join(full_text)

            if content and content.strip():
                logger.debug(f"使用python-docx部分读取.doc文件成功")
                return content
            tried_methods.append("python-docx (无内容)")
        except Exception as e:
            tried_methods.append(f"python-docx ({e})")
            logger.debug(f"尝试使用python-docx读取.doc失败: {str(e)}")

        # 所有方法都失败，抛出异常
        error_msg = (
            f"无法读取.doc文件，所有解析方法均失败。\n"
            f"尝试的方法: {', '.join(tried_methods)}\n"
            f"建议: 1) 安装相关依赖 (pip install textract 或 pypiwin32)\n"
            f"      2) 或将文件转换为.docx格式"
        )
        raise FileReadError(
            error_msg,
            file_path=file_path
        )
    
    def _read_csv(self, file_path: str) -> str:
        """
        读取CSV文件并转换为文本

        注意：此方法将CSV转为纯文本，暂不支持结构化数据处理
        """
        try:
            text = []
            with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
                csv_reader = csv.reader(file)
                for row in csv_reader:
                    text.append(','.join(row))
            return '\n'.join(text)
        except Exception as e:
            logger.debug(f"UTF-8 编码读取CSV失败，尝试其他编码: {os.path.basename(file_path)}")
            # 尝试其他编码
            try:
                with open(file_path, 'rb') as f:
                    try:
                        import chardet
                        raw_data = f.read(10240)
                        result = chardet.detect(raw_data)
                        encoding = result['encoding'] if result['encoding'] else 'gbk'
                    except:
                        encoding = 'gbk'  # 如果chardet不可用，默认使用gbk

                text = []
                with open(file_path, 'r', encoding=encoding, errors='replace') as file:
                    csv_reader = csv.reader(file)
                    for row in csv_reader:
                        text.append(','.join(row))
                logger.debug(f"使用 {encoding} 编码成功读取CSV文件")
                return '\n'.join(text)
            except Exception as e2:
                raise FileReadError(
                    f"无法读取CSV文件（尝试了UTF-8和{encoding}编码）",
                    file_path=file_path,
                    original_error=e2
                )
    
    def read_csv_as_dicts(self, file_path: str) -> List[Dict]:
        """
        读取CSV文件并返回字典列表
        
        Returns:
            List[Dict]: CSV数据的字典列表，每一行为一个字典
        """
        try:
            results = []
            with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
                csv_reader = csv.DictReader(file)
                for row in csv_reader:
                    results.append(dict(row))
            return results
        except Exception as e:
            print(f"读取CSV文件为字典列表时出错: {str(e)}")
            return []
    
    def _read_json(self, file_path: str) -> str:
        """读取JSON文件并返回文本格式"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
                # 加载为对象然后再转为格式化的字符串，以便更好地处理和显示
                data = json.load(file)
                return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception as e:
            raise FileReadError(
                f"无法读取JSON文件",
                file_path=file_path,
                original_error=e
            )
    
    def read_json_as_dict(self, file_path: str) -> Dict:
        """
        读取JSON文件并返回字典/列表对象
        
        Returns:
            Dict/List: JSON数据对象
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
                return json.load(file)
        except Exception as e:
            print(f"读取JSON文件为字典时出错: {str(e)}")
            return {}
    
    def _read_yaml(self, file_path: str) -> str:
        """读取YAML文件并返回文本格式"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
                data = yaml.load(file, Loader=Loader)
                # 先转为JSON字符串以获得更易读的格式
                return yaml.dump(data, allow_unicode=True, default_flow_style=False)
        except Exception as e:
            print(f"读取YAML文件 {os.path.basename(file_path)} 失败: {str(e)}")
            return f"[无法读取YAML文件内容: {str(e)}]"

    def _read_image(self, file_path: str) -> str:
        """使用OCR读取图像文件并返回提取的文字"""
        if not self.enable_ocr:
            logger.warning(f"OCR is disabled. Skipping image file: {file_path}")
            return f"[OCR未启用，跳过图像文件: {os.path.basename(file_path)}]"

        try:
            # 延迟导入和初始化
            if self._image_processor is None:
                from graphrag_agent.pipelines.ingestion.image_processor import ImageProcessor
                self._image_processor = ImageProcessor(use_gpu=False, lang="ch")
                logger.info("ImageProcessor initialized")

            text, metadata = self._image_processor.process_image(file_path)

            if not text:
                logger.warning(f"No text extracted from image: {file_path}")
                return "[图像中未检测到文字]"

            # 添加元数据到文本
            header = f"[图像OCR结果 - 置信度: {metadata.get('avg_confidence', 0):.2f}]\n"
            return header + text

        except ImportError as e:
            logger.error(f"OCR dependencies not installed: {e}")
            return f"[OCR依赖未安装: {e}]"
        except Exception as e:
            logger.error(f"读取图像文件 {os.path.basename(file_path)} 失败: {e}")
            return f"[无法读取图像文件: {e}]"

    def _read_audio(self, file_path: str) -> str:
        """使用ASR读取音频文件并返回转录的文字"""
        if not self.enable_asr:
            logger.warning(f"ASR is disabled. Skipping audio file: {file_path}")
            return f"[ASR未启用，跳过音频文件: {os.path.basename(file_path)}]"

        try:
            # 延迟导入和初始化
            if self._audio_processor is None:
                from graphrag_agent.pipelines.ingestion.audio_processor import AudioProcessor
                self._audio_processor = AudioProcessor(model_size="base", device="cpu")
                logger.info("AudioProcessor initialized")

            text, metadata = self._audio_processor.process_audio(file_path)

            if not text:
                logger.warning(f"No speech detected in audio: {file_path}")
                return "[音频中未检测到语音]"

            # 添加元数据到文本
            header = f"[音频ASR结果 - 语言: {metadata.get('detected_language', 'unknown')}]\n"
            return header + text

        except ImportError as e:
            logger.error(f"ASR dependencies not installed: {e}")
            return f"[ASR依赖未安装: {e}]"
        except Exception as e:
            logger.error(f"读取音频文件 {os.path.basename(file_path)} 失败: {e}")
            return f"[无法读取音频文件: {e}]"

    def read_yaml_as_dict(self, file_path: str) -> Dict:
        """
        读取YAML文件并返回字典对象
        
        Returns:
            Dict: YAML数据对象
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
                return yaml.load(file, Loader=Loader)
        except Exception as e:
            print(f"读取YAML文件为字典时出错: {str(e)}")
            return {}
    
    def read_txt_files(self) -> List[Tuple[str, str]]:
        """读取所有txt文件"""
        return self.read_files(['.txt'])
    
    def list_all_files(self, recursive: bool = True) -> List[str]:
        """
        列出目录中的所有文件
        
        Args:
            recursive: 是否递归列出子目录中的文件，默认为True
            
        Returns:
            List[str]: 文件路径列表（相对于根目录）
        """
        files = []
        
        try:
            if recursive:
                # 递归遍历所有子目录
                for root, _, filenames in os.walk(self.directory_path):
                    for filename in filenames:
                        # 获取相对于根目录的路径
                        rel_path = os.path.relpath(os.path.join(root, filename), self.directory_path)
                        files.append(rel_path)
            else:
                # 只列出当前目录下的文件
                files = os.listdir(self.directory_path)
        except Exception as e:
            print(f"列出目录文件时出错: {str(e)}")
            
        return files


# 测试代码
if __name__ == '__main__':
    print(f"FILES_DIR: {FILES_DIR}")
    reader = FileReader(FILES_DIR)
    
    # 列出目录中的所有文件
    all_filenames = reader.list_all_files()
    print(f"目录中共有 {len(all_filenames)} 个文件:")
    for filename in all_filenames:
        print(f"  {filename}")
    
    # 测试读取所有支持的文件
    all_files = reader.read_files()
    print(f"成功读取 {len(all_files)} 个文件")
    
    # 显示每种类型文件的数量
    file_types = {}
    for file_name, _ in all_files:
        ext = os.path.splitext(file_name)[1].lower()
        file_types[ext] = file_types.get(ext, 0) + 1
    
    print("Files by type:")
    for ext, count in file_types.items():
        print(f"  {ext}: {count}")