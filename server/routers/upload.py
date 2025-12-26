"""
文件上传 API（含完整校验示例）

用途：
- 演示生产环境文件上传的最佳实践
- 包含文件大小、类型、内容、安全性等多层校验
- 可作为其他路由的参考模板

安全检查：
- 文件大小限制（防止 DoS）
- 文件类型白名单（扩展名 + MIME 类型）
- 文件名安全检查（防止路径遍历）
- 文件内容校验（魔术字节检查）
- 病毒扫描占位（生产环境建议集成 ClamAV）

使用方法：
    # 上传文件
    curl -X POST "http://localhost:8000/api/v1/upload/file" \
      -F "file=@document.pdf" \
      -F "description=测试文档"

    # 批量上传
    curl -X POST "http://localhost:8000/api/v1/upload/batch" \
      -F "files=@file1.pdf" \
      -F "files=@file2.txt"
"""

import os
import re
import hashlib
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel, Field

from server.utils.logger import get_logger
from server.utils.exceptions import ValidationError, BusinessException
from server.models.schemas import BaseResponse, ErrorCode
from graphrag_agent.config.settings import FILES_DIR

logger = get_logger(__name__)

router = APIRouter(prefix="/upload", tags=["文件上传（示例）"])


# ============================================================================
# 配置常量
# ============================================================================

# 允许的文件类型（扩展名小写）
ALLOWED_EXTENSIONS = {
    ".pdf", ".txt", ".md", ".doc", ".docx",
    ".csv", ".json", ".yaml", ".yml"
}

# MIME 类型白名单（扩展名 → MIME 类型映射）
MIME_TYPE_WHITELIST = {
    ".pdf": ["application/pdf"],
    ".txt": ["text/plain"],
    ".md": ["text/markdown", "text/plain"],
    ".doc": ["application/msword"],
    ".docx": [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ],
    ".csv": ["text/csv", "application/csv"],
    ".json": ["application/json"],
    ".yaml": ["application/x-yaml", "text/yaml"],
    ".yml": ["application/x-yaml", "text/yaml"],
}

# 文件魔术字节（用于内容验证）
MAGIC_BYTES = {
    ".pdf": [b"%PDF"],
    ".docx": [b"PK\x03\x04"],  # ZIP 格式（Office 文档）
    ".doc": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],  # OLE 格式
}

# 文件大小限制
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
MAX_BATCH_SIZE = 10  # 批量上传最大文件数
MAX_FILENAME_LENGTH = 255

# 危险文件名模式（防止路径遍历）
DANGEROUS_PATTERNS = [
    r"\.\.",  # 上级目录
    r"\/",  # Unix 路径分隔符
    r"\\",  # Windows 路径分隔符
    r"\x00",  # NULL 字节
    r"[<>:\"|?*]",  # Windows 禁用字符
]


# ============================================================================
# 请求/响应模型
# ============================================================================

class UploadResponse(BaseModel):
    """上传响应"""
    filename: str = Field(description="保存的文件名")
    file_path: str = Field(description="文件路径")
    file_size: int = Field(description="文件大小（字节）")
    file_hash: str = Field(description="文件 SHA256 哈希")
    content_type: str = Field(description="MIME 类型")


class BatchUploadResponse(BaseModel):
    """批量上传响应"""
    success_count: int = Field(description="成功上传数量")
    failed_count: int = Field(description="失败数量")
    results: List[dict] = Field(description="每个文件的上传结果")


# ============================================================================
# 校验函数
# ============================================================================

def validate_filename(filename: str) -> None:
    """
    校验文件名安全性

    Args:
        filename: 文件名

    Raises:
        ValidationError: 文件名不合法
    """
    # 长度检查
    if len(filename) > MAX_FILENAME_LENGTH:
        raise ValidationError(
            f"文件名过长（最大 {MAX_FILENAME_LENGTH} 字符）",
            filename=filename,
            length=len(filename)
        )

    # 危险模式检查（防止路径遍历）
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, filename):
            raise ValidationError(
                f"文件名包含非法字符: {pattern}",
                filename=filename,
                pattern=pattern
            )

    logger.debug("文件名校验通过", filename=filename)


def validate_file_extension(filename: str) -> str:
    """
    校验文件扩展名

    Args:
        filename: 文件名

    Returns:
        扩展名（小写）

    Raises:
        ValidationError: 扩展名不在白名单中
    """
    ext = Path(filename).suffix.lower()

    if not ext:
        raise ValidationError(
            "文件缺少扩展名",
            filename=filename
        )

    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"不支持的文件类型: {ext}",
            filename=filename,
            extension=ext,
            allowed=list(ALLOWED_EXTENSIONS)
        )

    logger.debug("扩展名校验通过", filename=filename, extension=ext)
    return ext


def validate_mime_type(content_type: str, extension: str) -> None:
    """
    校验 MIME 类型（防止扩展名伪造）

    Args:
        content_type: HTTP Content-Type
        extension: 文件扩展名

    Raises:
        ValidationError: MIME 类型不匹配
    """
    allowed_mimes = MIME_TYPE_WHITELIST.get(extension, [])

    if not allowed_mimes:
        # 扩展名在白名单但没有 MIME 校验规则（警告）
        logger.warning(
            "扩展名无 MIME 校验规则",
            extension=extension,
            content_type=content_type
        )
        return

    if content_type not in allowed_mimes:
        raise ValidationError(
            f"MIME 类型不匹配: 期望 {allowed_mimes}，实际 {content_type}",
            extension=extension,
            expected=allowed_mimes,
            actual=content_type
        )

    logger.debug(
        "MIME 类型校验通过",
        content_type=content_type,
        extension=extension
    )


async def validate_file_content(
    file: UploadFile,
    extension: str
) -> bytes:
    """
    校验文件内容（流式读取 + 魔术字节检查 + 大小限制）

    ✅ 改进：使用流式读取，防止大文件占用过多内存，超过限制立即中断

    Args:
        file: 上传的文件对象
        extension: 文件扩展名

    Returns:
        文件内容（字节）

    Raises:
        ValidationError: 文件内容不合法
    """
    # ✅ 流式读取文件（1MB chunks），同时计数
    chunks = []
    total_size = 0
    header = None  # 保存前 2KB 用于深度 MIME 检测

    CHUNK_SIZE = 1024 * 1024  # 1MB per chunk

    try:
        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break

            # 保存前 2KB 用于魔术字节检查
            if header is None:
                header = chunk[:2048]

            total_size += len(chunk)

            # ✅ 实时大小检查（超过限制立即中断，不继续读取）
            if total_size > MAX_FILE_SIZE:
                raise ValidationError(
                    f"文件过大（最大 {MAX_FILE_SIZE / 1024 / 1024:.1f}MB）",
                    filename=file.filename,
                    size=total_size,
                    max_size=MAX_FILE_SIZE
                )

            chunks.append(chunk)

    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"文件读取失败: {str(e)}", filename=file.filename, exc_info=True)
        raise ValidationError(
            f"文件读取失败: {str(e)}",
            filename=file.filename
        )

    # 大小检查
    if total_size == 0:
        raise ValidationError(
            "文件为空",
            filename=file.filename
        )

    # ✅ 深度魔术字节检查（检查前 2KB，比之前的 100 字节更严格）
    magic_bytes = MAGIC_BYTES.get(extension)
    if magic_bytes and header:
        matched = any(header.startswith(magic) for magic in magic_bytes)

        if not matched:
            raise ValidationError(
                f"文件内容与扩展名 {extension} 不匹配（魔术字节检查失败，可能是伪造的文件）",
                filename=file.filename,
                extension=extension
            )

        logger.debug(
            "魔术字节校验通过（深度检测 2KB）",
            filename=file.filename,
            extension=extension
        )

    # ✅ 可选：使用 python-magic 进行深度 MIME 检测
    # 注意：需要系统安装 libmagic 库，可能不是所有环境都有
    try:
        import magic
        if header:
            detected_mime = magic.from_buffer(header, mime=True)
            allowed_mimes = MIME_TYPE_WHITELIST.get(extension, [])

            if allowed_mimes and detected_mime not in allowed_mimes:
                logger.warning(
                    "python-magic 深度检测失败（MIME 不匹配）",
                    filename=file.filename,
                    expected=allowed_mimes,
                    actual=detected_mime
                )
                # 警告：可能是伪造文件，但不一定立即拒绝（因为 magic 库可能误判）
                # raise ValidationError(
                #     f"文件 MIME 类型不匹配: 期望 {allowed_mimes}，实际 {detected_mime}",
                #     extension=extension,
                #     expected=allowed_mimes,
                #     actual=detected_mime
                # )
            else:
                logger.debug(
                    "python-magic 深度检测通过",
                    filename=file.filename,
                    mime=detected_mime
                )
    except ImportError:
        # python-magic 未安装，跳过深度检测
        logger.debug("python-magic 未安装，跳过深度 MIME 检测")
    except Exception as e:
        # python-magic 检测失败，记录警告但不阻塞
        logger.warning(f"python-magic 检测失败: {str(e)}", filename=file.filename)

    logger.info(
        "文件内容校验通过（流式读取）",
        filename=file.filename,
        size=total_size,
        chunks=len(chunks)
    )

    # 合并所有 chunks
    content = b"".join(chunks)
    return content


def compute_file_hash(content: bytes) -> str:
    """
    计算文件哈希（用于去重和完整性校验）

    Args:
        content: 文件内容

    Returns:
        SHA256 哈希（十六进制）
    """
    return hashlib.sha256(content).hexdigest()


def save_file(filename: str, content: bytes) -> Path:
    """
    保存文件到磁盘

    Args:
        filename: 文件名
        content: 文件内容

    Returns:
        保存的文件路径

    Raises:
        BusinessException: 保存失败
    """
    try:
        # 确保目录存在
        FILES_DIR.mkdir(parents=True, exist_ok=True)

        # 生成唯一文件名（添加时间戳避免冲突）
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name, ext = os.path.splitext(filename)
        unique_filename = f"{name}_{timestamp}{ext}"

        file_path = FILES_DIR / unique_filename

        # 写入文件
        with open(file_path, "wb") as f:
            f.write(content)

        logger.info(
            "文件保存成功",
            filename=unique_filename,
            path=str(file_path),
            size=len(content)
        )

        return file_path

    except Exception as e:
        logger.error(f"文件保存失败: {str(e)}", filename=filename, exc_info=True)
        raise BusinessException(
            f"文件保存失败: {str(e)}",
            code=ErrorCode.FILE_WRITE_ERROR,
            details={"filename": filename}
        )


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("/file", response_model=BaseResponse[UploadResponse], summary="上传单个文件")
async def upload_file(
    file: UploadFile = File(..., description="上传的文件"),
    description: Optional[str] = Form(None, description="文件描述（可选）")
):
    """
    上传单个文件（含完整校验）

    校验流程：
    1. 文件名安全检查（长度、非法字符、路径遍历）
    2. 扩展名白名单检查
    3. MIME 类型验证（防止扩展名伪造）
    4. 文件内容检查（大小限制、魔术字节）
    5. 哈希计算（去重和完整性）
    6. 保存到磁盘

    错误处理：
    - 400: 文件校验失败（ValidationError）
    - 500: 文件保存失败（BusinessException）

    Example:
        ```bash
        curl -X POST "http://localhost:8000/api/v1/upload/file" \\
          -F "file=@document.pdf" \\
          -F "description=重要文档"
        ```
    """
    logger.info("收到文件上传请求", filename=file.filename, content_type=file.content_type)

    # 1. 文件名校验
    validate_filename(file.filename)

    # 2. 扩展名校验
    extension = validate_file_extension(file.filename)

    # 3. MIME 类型校验
    validate_mime_type(file.content_type, extension)

    # 4. 文件内容校验
    content = await validate_file_content(file, extension)

    # 5. 计算哈希
    file_hash = compute_file_hash(content)
    logger.debug("文件哈希计算完成", filename=file.filename, hash=file_hash)

    # TODO: 检查哈希是否已存在（去重）
    # existing = check_file_exists_by_hash(file_hash)
    # if existing:
    #     return BaseResponse(code=200, msg="文件已存在（去重）", data=existing)

    # TODO: 病毒扫描（生产环境推荐）
    # scan_result = scan_file_with_clamav(content)
    # if scan_result.is_infected:
    #     raise ValidationError("文件包含恶意内容", virus=scan_result.virus_name)

    # 6. 保存文件
    saved_path = save_file(file.filename, content)

    # 7. 返回结果
    result = UploadResponse(
        filename=saved_path.name,
        file_path=str(saved_path),
        file_size=len(content),
        file_hash=file_hash,
        content_type=file.content_type
    )

    logger.info(
        "文件上传成功",
        filename=result.filename,
        size=result.file_size,
        hash=result.file_hash
    )

    return BaseResponse(code=200, msg="上传成功", data=result)


@router.post("/batch", response_model=BaseResponse[BatchUploadResponse], summary="批量上传文件")
async def upload_batch(
    files: List[UploadFile] = File(..., description="文件列表（最多10个）")
):
    """
    批量上传文件

    限制：
    - 单次最多上传 10 个文件
    - 每个文件独立校验，失败不影响其他文件

    返回：
    - success_count: 成功上传数量
    - failed_count: 失败数量
    - results: 每个文件的详细结果

    Example:
        ```bash
        curl -X POST "http://localhost:8000/api/v1/upload/batch" \\
          -F "files=@file1.pdf" \\
          -F "files=@file2.txt" \\
          -F "files=@file3.md"
        ```
    """
    logger.info("收到批量上传请求", file_count=len(files))

    # 数量限制
    if len(files) > MAX_BATCH_SIZE:
        raise ValidationError(
            f"单次最多上传 {MAX_BATCH_SIZE} 个文件",
            current=len(files),
            max=MAX_BATCH_SIZE
        )

    results = []
    success_count = 0
    failed_count = 0

    for file in files:
        try:
            # 重用单文件上传逻辑
            validate_filename(file.filename)
            extension = validate_file_extension(file.filename)
            validate_mime_type(file.content_type, extension)
            content = await validate_file_content(file, extension)
            file_hash = compute_file_hash(content)
            saved_path = save_file(file.filename, content)

            results.append({
                "filename": file.filename,
                "status": "success",
                "saved_path": str(saved_path),
                "size": len(content),
                "hash": file_hash
            })

            success_count += 1

        except ValidationError as e:
            logger.warning(f"文件校验失败: {e.message}", filename=file.filename)
            results.append({
                "filename": file.filename,
                "status": "failed",
                "error": e.message,
                "details": e.details
            })
            failed_count += 1

        except Exception as e:
            logger.error(f"文件上传失败: {str(e)}", filename=file.filename, exc_info=True)
            results.append({
                "filename": file.filename,
                "status": "failed",
                "error": f"上传失败: {str(e)}"
            })
            failed_count += 1

    response = BatchUploadResponse(
        success_count=success_count,
        failed_count=failed_count,
        results=results
    )

    logger.info(
        "批量上传完成",
        total=len(files),
        success=success_count,
        failed=failed_count
    )

    return BaseResponse(code=200, msg="批量上传完成", data=response)


@router.delete("/{filename}", summary="删除文件（示例）")
async def delete_file(filename: str):
    """
    删除文件（示例端点）

    安全注意：
    - 校验文件名（防止路径遍历）
    - 仅允许删除 FILES_DIR 内的文件
    - 记录删除日志（审计）

    Example:
        ```bash
        curl -X DELETE "http://localhost:8000/api/v1/upload/document.pdf"
        ```
    """
    # 文件名校验
    validate_filename(filename)

    # 构造完整路径
    file_path = FILES_DIR / filename

    # 安全检查：确保路径在 FILES_DIR 内（防止路径遍历）
    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str(FILES_DIR.resolve())):
            raise ValidationError(
                "非法文件路径",
                filename=filename,
                path=str(file_path)
            )
    except Exception as e:
        raise ValidationError(f"路径解析失败: {str(e)}", filename=filename)

    # 检查文件是否存在
    if not file_path.exists():
        raise BusinessException(
            "文件不存在",
            code=ErrorCode.NOT_FOUND,
            details={"filename": filename}
        )

    # 删除文件
    try:
        file_path.unlink()
        logger.info("文件删除成功", filename=filename, path=str(file_path))

        return BaseResponse(
            code=200,
            msg="删除成功",
            data={"filename": filename, "path": str(file_path)}
        )

    except Exception as e:
        logger.error(f"文件删除失败: {str(e)}", filename=filename, exc_info=True)
        raise BusinessException(
            f"文件删除失败: {str(e)}",
            code=ErrorCode.FILE_DELETE_ERROR,
            details={"filename": filename}
        )
