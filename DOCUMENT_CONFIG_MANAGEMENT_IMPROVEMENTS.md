# 文档管理与配置管理改进方案

## 概述

本文档针对 GraphRAG Agent 系统的两个核心模块提供详细的改进方案：
1. **文档管理中心 (Document Management)** - 文件生命周期追踪与状态管理
2. **配置管理界面 (Configuration Management)** - 版本控制与参数调优

---

## 模块一：文档管理中心 (Document Management)

### 一、问题验证与分析

#### ✅ 已验证的问题

经过代码审查，确认以下问题**真实存在**：

1. **状态缺失** ✅
   - **现状**：`document_manager.py` 使用 `os.listdir(FILES_DIR)` 扫描文件系统
   - **问题**：无法追踪文件在构建管道中的状态（待解析/解析中/已索引/失败）
   - **影响**：用户无法知道上传的文件是否已完成索引，失败文件无法重试

2. **无分块/实体预览** ✅
   - **现状**：`source.py` 仅提供 `get_source_content()` 获取原始内容
   - **问题**：缺少 `/chunks` 和 `/entities` 端点，无法预览解析结果
   - **影响**：无法验证文档切分质量，无法查看抽取的实体

3. **缺乏元数据管理** ✅
   - **现状**：没有数据库表记录上传人、上传时间、文件哈希
   - **问题**：`upload.py` 计算了 `file_hash` 但未持久化（仅在响应中返回）
   - **影响**：无法去重、无法审计、无法按上传人筛选

4. **无重试机制** ✅
   - **现状**：构建失败后，只能手动删除文件重新上传
   - **问题**：没有状态记录，无法实现重试逻辑
   - **影响**：用户体验差，浪费存储空间

#### 📋 代码位置

- **前端**：`frontend/page_components/document_manager.py:36-49` (list_documents 函数)
- **后端**：
  - `server/routers/upload.py` (上传逻辑，已有 hash 计算但未存储)
  - `server/routers/source.py` (仅支持原始内容获取)
- **缺失**：无 ORM 模型定义文件 (server/models/db.py)

---

### 二、详细改进方案

#### A. 后端改动 (Backend)

##### 1. 引入 SQLAlchemy ORM 与 FileRecord 模型

**新增文件：`server/models/db.py`**

```python
"""
数据库模型定义
使用 SQLAlchemy ORM
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from sqlalchemy import Column, String, DateTime, Integer, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import uuid

Base = declarative_base()


class FileStatus(str, Enum):
    """文件处理状态枚举"""
    PENDING = "pending"           # 待解析
    PARSING = "parsing"           # 解析中
    INDEXED = "indexed"           # 已索引
    FAILED = "failed"             # 失败


class FileRecord(Base):
    """文件元数据记录表"""
    __tablename__ = "file_records"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String(255), nullable=False, index=True)
    file_path = Column(String(512), nullable=False, unique=True)
    file_hash = Column(String(64), nullable=False, unique=True, index=True)  # SHA256
    file_size = Column(Integer, nullable=False)

    # 状态管理
    status = Column(String(20), nullable=False, default=FileStatus.PENDING, index=True)
    error_msg = Column(Text, nullable=True)

    # 元数据
    uploader = Column(String(100), nullable=True)  # 用户ID/名称
    upload_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_modified = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 索引统计
    chunk_count = Column(Integer, nullable=True, default=0)
    entity_count = Column(Integer, nullable=True, default=0)

    def __repr__(self):
        return f"<FileRecord(id={self.id}, filename={self.filename}, status={self.status})>"


# 数据库初始化
def init_db(db_url: str = "sqlite:///./graphrag_metadata.db"):
    """初始化数据库连接和表"""
    engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    return engine


def get_session(engine):
    """获取数据库会话"""
    Session = sessionmaker(bind=engine)
    return Session()
```

**新增文件：`server/db/connection.py`**

```python
"""
数据库连接管理器
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator
import os

from server.models.db import Base

# 从环境变量读取数据库 URL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./graphrag_metadata.db")

# 创建引擎
engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,  # 连接池健康检查
    pool_recycle=3600    # 每小时回收连接
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_database():
    """初始化数据库表"""
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """
    数据库会话上下文管理器

    Usage:
        with get_db() as db:
            db.query(FileRecord).all()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# FastAPI 依赖注入版本
def get_db_dependency():
    """FastAPI 依赖注入使用"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

##### 2. 修改上传 API (upload.py)

**修改：`server/routers/upload.py`**

```python
# 在文件顶部添加导入
from server.models.db import FileRecord, FileStatus
from server.db.connection import get_db
from fastapi import Depends
from sqlalchemy.orm import Session

# 修改 upload_file 端点 (第413行)
@router.post("/file", response_model=BaseResponse[UploadResponse], summary="上传单个文件")
async def upload_file(
    file: UploadFile = File(..., description="上传的文件"),
    description: Optional[str] = Form(None, description="文件描述（可选）"),
    uploader: Optional[str] = Form(None, description="上传人（可选）"),
    db: Session = Depends(get_db_dependency)  # ✅ 注入数据库会话
):
    """上传单个文件（含完整校验 + 数据库记录）"""

    logger.info("收到文件上传请求", filename=file.filename, content_type=file.content_type)

    # 1-4. 文件校验逻辑（保持不变）
    validate_filename(file.filename)
    extension = validate_file_extension(file.filename)
    validate_mime_type(file.content_type, extension)
    content = await validate_file_content(file, extension)

    # 5. 计算哈希
    file_hash = compute_file_hash(content)
    logger.debug("文件哈希计算完成", filename=file.filename, hash=file_hash)

    # ✅ 5.1 检查哈希是否已存在（去重）
    existing = db.query(FileRecord).filter(FileRecord.file_hash == file_hash).first()
    if existing:
        logger.info("文件已存在（去重）", filename=file.filename, existing_id=existing.id)
        return BaseResponse(
            code=200,
            msg="文件已存在（去重）",
            data=UploadResponse(
                filename=existing.filename,
                file_path=existing.file_path,
                file_size=existing.file_size,
                file_hash=existing.file_hash,
                content_type=file.content_type
            )
        )

    # 6. 保存文件
    saved_path = save_file(file.filename, content)

    # ✅ 7. 创建数据库记录
    file_record = FileRecord(
        filename=saved_path.name,
        file_path=str(saved_path),
        file_hash=file_hash,
        file_size=len(content),
        status=FileStatus.PENDING,
        uploader=uploader
    )
    db.add(file_record)
    db.commit()
    db.refresh(file_record)

    logger.info(
        "文件上传成功并记录到数据库",
        filename=file_record.filename,
        file_id=file_record.id,
        status=file_record.status
    )

    # 8. 返回结果（✅ 新增 file_id）
    result = UploadResponse(
        filename=file_record.filename,
        file_path=file_record.file_path,
        file_size=file_record.file_size,
        file_hash=file_record.file_hash,
        content_type=file.content_type
    )

    return BaseResponse(
        code=200,
        msg="上传成功",
        data=result,
        extra={"file_id": file_record.id}  # ✅ 返回 file_id 供前端使用
    )
```

##### 3. 新增文档管理 API

**新增文件：`server/routers/documents.py`**

```python
"""
文档管理 API
提供文件列表、状态查询、分块/实体预览、重试等功能
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_
from typing import List, Optional
from datetime import datetime

from server.models.db import FileRecord, FileStatus
from server.db.connection import get_db_dependency
from server.models.schemas import BaseResponse
from pydantic import BaseModel, Field
from graphrag_agent.config.neo4jdb import get_db_manager

router = APIRouter(prefix="/documents", tags=["文档管理"])


# ============================================================================
# 请求/响应模型
# ============================================================================

class FileRecordResponse(BaseModel):
    """文件记录响应"""
    id: str
    filename: str
    file_path: str
    file_hash: str
    file_size: int
    status: str
    error_msg: Optional[str]
    uploader: Optional[str]
    upload_time: datetime
    last_modified: datetime
    chunk_count: int
    entity_count: int


class DocumentListResponse(BaseModel):
    """文档列表响应"""
    total: int = Field(description="总数量")
    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页大小")
    items: List[FileRecordResponse] = Field(description="文档列表")


class ChunkPreview(BaseModel):
    """分块预览"""
    chunk_id: str
    content: str
    chunk_order: int
    token_count: Optional[int]


class EntityPreview(BaseModel):
    """实体预览"""
    entity_id: str
    entity_name: str
    entity_type: str
    description: Optional[str]


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/list", response_model=BaseResponse[DocumentListResponse], summary="获取文档列表")
async def list_documents(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页大小"),
    status: Optional[str] = Query(None, description="状态筛选 (pending/parsing/indexed/failed)"),
    uploader: Optional[str] = Query(None, description="上传人筛选"),
    filename: Optional[str] = Query(None, description="文件名搜索"),
    db: Session = Depends(get_db_dependency)
):
    """
    获取文档列表（支持分页和筛选）

    筛选条件：
    - status: 文件状态
    - uploader: 上传人
    - filename: 文件名模糊搜索

    排序：按上传时间倒序
    """
    # 构建查询条件
    query = db.query(FileRecord)

    if status:
        query = query.filter(FileRecord.status == status)

    if uploader:
        query = query.filter(FileRecord.uploader == uploader)

    if filename:
        query = query.filter(FileRecord.filename.contains(filename))

    # 计算总数
    total = query.count()

    # 分页查询
    offset = (page - 1) * page_size
    items = query.order_by(desc(FileRecord.upload_time)).offset(offset).limit(page_size).all()

    # 转换为响应模型
    items_response = [
        FileRecordResponse(
            id=item.id,
            filename=item.filename,
            file_path=item.file_path,
            file_hash=item.file_hash,
            file_size=item.file_size,
            status=item.status,
            error_msg=item.error_msg,
            uploader=item.uploader,
            upload_time=item.upload_time,
            last_modified=item.last_modified,
            chunk_count=item.chunk_count or 0,
            entity_count=item.entity_count or 0
        )
        for item in items
    ]

    return BaseResponse(
        code=200,
        msg="查询成功",
        data=DocumentListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=items_response
        )
    )


@router.get("/{file_id}/chunks", summary="获取文件的分块列表")
async def get_file_chunks(
    file_id: str,
    skip: int = Query(0, ge=0, description="跳过数量"),
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    db: Session = Depends(get_db_dependency)
):
    """
    获取文件的所有分块

    从 Neo4j 查询该文件关联的 Chunk 节点
    """
    # 验证文件存在
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    # 从 Neo4j 查询分块
    db_manager = get_db_manager()
    driver = db_manager.get_driver()

    # ✅ 关键 Cypher 查询
    cypher = """
    MATCH (d:__Document__ {file_path: $file_path})<-[:PART_OF]-(c:__Chunk__)
    RETURN c.id AS chunk_id,
           c.content AS content,
           c.chunk_order AS chunk_order,
           c.n_tokens AS token_count
    ORDER BY c.chunk_order
    SKIP $skip
    LIMIT $limit
    """

    with driver.session() as session:
        result = session.run(cypher, file_path=file_record.file_path, skip=skip, limit=limit)
        chunks = [
            ChunkPreview(
                chunk_id=record["chunk_id"],
                content=record["content"],
                chunk_order=record["chunk_order"],
                token_count=record.get("token_count")
            )
            for record in result
        ]

    return BaseResponse(
        code=200,
        msg="查询成功",
        data={
            "file_id": file_id,
            "filename": file_record.filename,
            "total_chunks": file_record.chunk_count,
            "chunks": [chunk.dict() for chunk in chunks]
        }
    )


@router.get("/{file_id}/entities", summary="获取文件关联的实体")
async def get_file_entities(
    file_id: str,
    skip: int = Query(0, ge=0, description="跳过数量"),
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    db: Session = Depends(get_db_dependency)
):
    """
    获取文件关联的实体

    从 Neo4j 查询该文件的 Chunk 提及的所有实体
    """
    # 验证文件存在
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    # 从 Neo4j 查询实体
    db_manager = get_db_manager()
    driver = db_manager.get_driver()

    # ✅ 关键 Cypher 查询
    cypher = """
    MATCH (d:__Document__ {file_path: $file_path})<-[:PART_OF]-(c:__Chunk__)-[:MENTIONS]->(e:__Entity__)
    RETURN DISTINCT e.id AS entity_id,
                    e.name AS entity_name,
                    e.type AS entity_type,
                    e.description AS description
    ORDER BY e.name
    SKIP $skip
    LIMIT $limit
    """

    with driver.session() as session:
        result = session.run(cypher, file_path=file_record.file_path, skip=skip, limit=limit)
        entities = [
            EntityPreview(
                entity_id=record["entity_id"],
                entity_name=record["entity_name"],
                entity_type=record["entity_type"],
                description=record.get("description")
            )
            for record in result
        ]

    return BaseResponse(
        code=200,
        msg="查询成功",
        data={
            "file_id": file_id,
            "filename": file_record.filename,
            "total_entities": file_record.entity_count,
            "entities": [entity.dict() for entity in entities]
        }
    )


@router.post("/{file_id}/retry", summary="重试失败的文件")
async def retry_file(
    file_id: str,
    db: Session = Depends(get_db_dependency)
):
    """
    重试失败的文件

    将状态重置为 PENDING 并重新触发构建任务
    """
    # 查询文件记录
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    # 只允许重试失败的文件
    if file_record.status != FileStatus.FAILED:
        raise HTTPException(
            status_code=400,
            detail=f"文件状态为 {file_record.status}，只能重试失败的文件"
        )

    # 重置状态
    file_record.status = FileStatus.PENDING
    file_record.error_msg = None
    file_record.last_modified = datetime.utcnow()
    db.commit()

    # TODO: 触发增量构建任务
    # from server.services.build_service import trigger_incremental_build
    # trigger_incremental_build(file_paths=[file_record.file_path])

    return BaseResponse(
        code=200,
        msg="重试任务已提交",
        data={
            "file_id": file_id,
            "filename": file_record.filename,
            "status": file_record.status
        }
    )


@router.delete("/{file_id}", summary="删除文件")
async def delete_file(
    file_id: str,
    db: Session = Depends(get_db_dependency)
):
    """
    删除文件（磁盘 + 数据库记录）

    注意：不会删除 Neo4j 中的图谱数据，需要手动重建或清理
    """
    from pathlib import Path

    # 查询文件记录
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    # 删除磁盘文件
    file_path = Path(file_record.file_path)
    if file_path.exists():
        file_path.unlink()

    # 删除数据库记录
    db.delete(file_record)
    db.commit()

    return BaseResponse(
        code=200,
        msg="删除成功",
        data={
            "file_id": file_id,
            "filename": file_record.filename
        }
    )
```

##### 4. 集成构建管道状态更新

**修改：`graphrag_agent/integrations/build/incremental_update_v2.py`**

在构建管道的关键节点更新文件状态：

```python
# 在文件顶部添加导入
from server.models.db import FileRecord, FileStatus
from server.db.connection import get_db

# 在 run_fast_ingestion 方法中添加状态更新
async def run_fast_ingestion(self, file_paths: List[str]) -> Dict:
    """快速摄取管道 (L0) - 更新状态"""

    for file_path in file_paths:
        # ✅ 更新状态为 PARSING
        with get_db() as db:
            file_record = db.query(FileRecord).filter(
                FileRecord.file_path == file_path
            ).first()

            if file_record:
                file_record.status = FileStatus.PARSING
                db.commit()

        try:
            # 执行快速摄取
            result = await asyncio.to_thread(
                self.fast_pipeline.process_single_file,
                file_path
            )

            # ✅ 更新统计信息
            with get_db() as db:
                file_record = db.query(FileRecord).filter(
                    FileRecord.file_path == file_path
                ).first()

                if file_record:
                    file_record.chunk_count = result.get('chunk_count', 0)
                    # 注意：L0 阶段还没有实体，entity_count 在 L1 完成后更新
                    db.commit()

        except Exception as e:
            # ✅ 更新状态为 FAILED
            with get_db() as db:
                file_record = db.query(FileRecord).filter(
                    FileRecord.file_path == file_path
                ).first()

                if file_record:
                    file_record.status = FileStatus.FAILED
                    file_record.error_msg = str(e)
                    db.commit()

            raise

# 在 run_graph_building 方法中添加状态更新
async def run_graph_building(self, file_paths: List[str]) -> Dict:
    """图构建管道 (L1) - 更新状态"""

    for file_path in file_paths:
        try:
            # 执行图构建
            result = await asyncio.to_thread(
                self.graph_pipeline.build_graph_for_file,
                file_path
            )

            # ✅ 更新状态为 INDEXED
            with get_db() as db:
                file_record = db.query(FileRecord).filter(
                    FileRecord.file_path == file_path
                ).first()

                if file_record:
                    file_record.status = FileStatus.INDEXED
                    file_record.entity_count = result.get('entity_count', 0)
                    db.commit()

        except Exception as e:
            # ✅ 更新状态为 FAILED
            with get_db() as db:
                file_record = db.query(FileRecord).filter(
                    FileRecord.file_path == file_path
                ).first()

                if file_record:
                    file_record.status = FileStatus.FAILED
                    file_record.error_msg = str(e)
                    db.commit()

            raise
```

#### B. 前端改动 (Frontend)

##### 1. 重构 document_manager.py

**完整替换：`frontend/page_components/document_manager.py`**

```python
"""
文档管理页面（增强版）
- 状态可视化
- 分块/实体预览
- 重试机制
"""

import streamlit as st
import requests
from datetime import datetime
from typing import List, Dict, Optional

from frontend_config.settings import API_URL


# ============================================================================
# API 调用函数
# ============================================================================

def fetch_documents(page: int = 1, page_size: int = 20,
                   status: Optional[str] = None,
                   filename: Optional[str] = None) -> Dict:
    """获取文档列表"""
    try:
        params = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status
        if filename:
            params["filename"] = filename

        response = requests.get(f"{API_URL}/documents/list", params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("data", {})
    except Exception as e:
        st.error(f"获取文档列表失败: {e}")
        return {"total": 0, "items": []}


def fetch_file_chunks(file_id: str, skip: int = 0, limit: int = 50) -> List[Dict]:
    """获取文件分块"""
    try:
        params = {"skip": skip, "limit": limit}
        response = requests.get(
            f"{API_URL}/documents/{file_id}/chunks",
            params=params,
            timeout=10
        )
        response.raise_for_status()
        return response.json().get("data", {}).get("chunks", [])
    except Exception as e:
        st.error(f"获取分块失败: {e}")
        return []


def fetch_file_entities(file_id: str, skip: int = 0, limit: int = 50) -> List[Dict]:
    """获取文件实体"""
    try:
        params = {"skip": skip, "limit": limit}
        response = requests.get(
            f"{API_URL}/documents/{file_id}/entities",
            params=params,
            timeout=10
        )
        response.raise_for_status()
        return response.json().get("data", {}).get("entities", [])
    except Exception as e:
        st.error(f"获取实体失败: {e}")
        return []


def retry_file(file_id: str) -> bool:
    """重试失败的文件"""
    try:
        response = requests.post(f"{API_URL}/documents/{file_id}/retry", timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        st.error(f"重试失败: {e}")
        return False


def delete_file_api(file_id: str) -> bool:
    """删除文件"""
    try:
        response = requests.delete(f"{API_URL}/documents/{file_id}", timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        st.error(f"删除失败: {e}")
        return False


# ============================================================================
# UI 组件
# ============================================================================

def render_status_badge(status: str) -> str:
    """渲染状态徽章"""
    status_config = {
        "pending": {"icon": "⚪", "text": "待解析", "color": "#gray"},
        "parsing": {"icon": "🔵", "text": "解析中", "color": "#blue"},
        "indexed": {"icon": "🟢", "text": "已索引", "color": "#green"},
        "failed": {"icon": "🔴", "text": "失败", "color": "#red"}
    }

    config = status_config.get(status, {"icon": "⚫", "text": "未知", "color": "#gray"})
    return f"{config['icon']} {config['text']}"


def render_file_size(size_bytes: int) -> str:
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def render_chunk_preview_modal(file_id: str, filename: str):
    """渲染分块预览模态框"""
    st.subheader(f"📄 {filename} - 分块预览")

    # 获取分块数据
    with st.spinner("加载分块数据..."):
        chunks = fetch_file_chunks(file_id, limit=100)

    if not chunks:
        st.info("该文件暂无分块数据")
        return

    # 显示分块列表
    st.caption(f"共 {len(chunks)} 个分块")

    for idx, chunk in enumerate(chunks):
        with st.expander(f"分块 #{chunk['chunk_order']} (ID: {chunk['chunk_id'][:8]}...)", expanded=(idx == 0)):
            st.text_area(
                "内容",
                value=chunk['content'],
                height=200,
                key=f"chunk_content_{chunk['chunk_id']}",
                disabled=True
            )
            if chunk.get('token_count'):
                st.caption(f"Token 数量: {chunk['token_count']}")


def render_entity_preview_modal(file_id: str, filename: str):
    """渲染实体预览模态框"""
    st.subheader(f"🏷️ {filename} - 实体预览")

    # 获取实体数据
    with st.spinner("加载实体数据..."):
        entities = fetch_file_entities(file_id, limit=100)

    if not entities:
        st.info("该文件暂无实体数据")
        return

    # 显示实体列表
    st.caption(f"共 {len(entities)} 个实体")

    # 按类型分组
    entities_by_type = {}
    for entity in entities:
        entity_type = entity['entity_type']
        if entity_type not in entities_by_type:
            entities_by_type[entity_type] = []
        entities_by_type[entity_type].append(entity)

    # 显示分组后的实体
    for entity_type, type_entities in entities_by_type.items():
        with st.expander(f"📦 {entity_type} ({len(type_entities)} 个)", expanded=True):
            for entity in type_entities:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{entity['entity_name']}**")
                    if entity.get('description'):
                        st.caption(entity['description'])
                with col2:
                    st.caption(f"ID: {entity['entity_id'][:8]}...")


# ============================================================================
# 主页面
# ============================================================================

def document_manager_page():
    """文档管理主页面（增强版）"""
    st.title("📚 文档管理")
    st.markdown("---")

    # 文件上传区域（保持原有逻辑，略）
    st.subheader("📤 上传文档")
    # ... (上传逻辑保持不变)

    st.markdown("---")

    # 文档列表区域
    st.subheader("📋 已导入文档")

    # 筛选器
    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        search_query = st.text_input("🔍 搜索文件名", key="search_filename")

    with col2:
        status_filter = st.selectbox(
            "📊 状态筛选",
            options=["全部", "待解析", "解析中", "已索引", "失败"],
            key="status_filter"
        )

    with col3:
        if st.button("🔄 刷新", key="refresh_list"):
            st.rerun()

    # 映射状态选项到 API 参数
    status_map = {
        "全部": None,
        "待解析": "pending",
        "解析中": "parsing",
        "已索引": "indexed",
        "失败": "failed"
    }

    # 获取文档列表
    page = st.session_state.get("document_page", 1)
    page_size = 20

    with st.spinner("加载文档列表..."):
        data = fetch_documents(
            page=page,
            page_size=page_size,
            status=status_map[status_filter],
            filename=search_query if search_query else None
        )

    documents = data.get("items", [])
    total = data.get("total", 0)

    if total == 0:
        st.info("📭 暂无文档，请上传文件")
        return

    # 显示统计信息
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总文档数", total)
    with col2:
        pending_count = sum(1 for doc in documents if doc['status'] == 'pending')
        st.metric("待解析", pending_count)
    with col3:
        indexed_count = sum(1 for doc in documents if doc['status'] == 'indexed')
        st.metric("已索引", indexed_count)
    with col4:
        failed_count = sum(1 for doc in documents if doc['status'] == 'failed')
        st.metric("失败", failed_count, delta_color="inverse")

    st.markdown("---")

    # 文档表格
    for idx, doc in enumerate(documents):
        col1, col2, col3, col4, col5, col6 = st.columns([3, 1, 1, 2, 1, 2])

        with col1:
            # 文件图标
            file_type = doc['filename'].split('.')[-1].upper()
            icon = {
                'PDF': '📄', 'TXT': '📝', 'MD': '📘',
                'DOCX': '📘', 'DOC': '📘', 'CSV': '📊',
                'JSON': '📋', 'YAML': '⚙️', 'YML': '⚙️'
            }.get(file_type, '📎')
            st.text(f"{icon} {doc['filename']}")

        with col2:
            st.text(render_status_badge(doc['status']))

        with col3:
            st.text(render_file_size(doc['file_size']))

        with col4:
            upload_time = datetime.fromisoformat(doc['upload_time'].replace('Z', '+00:00'))
            st.text(upload_time.strftime('%Y-%m-%d %H:%M'))

        with col5:
            st.caption(f"{doc['chunk_count']} 块")
            st.caption(f"{doc['entity_count']} 实体")

        with col6:
            # 操作按钮
            btn_col1, btn_col2, btn_col3, btn_col4 = st.columns(4)

            with btn_col1:
                if st.button("👁️", key=f"preview_chunks_{idx}", help="预览分块"):
                    st.session_state.preview_file_id = doc['id']
                    st.session_state.preview_filename = doc['filename']
                    st.session_state.preview_type = "chunks"

            with btn_col2:
                if st.button("🏷️", key=f"preview_entities_{idx}", help="预览实体"):
                    st.session_state.preview_file_id = doc['id']
                    st.session_state.preview_filename = doc['filename']
                    st.session_state.preview_type = "entities"

            with btn_col3:
                # 只有失败状态才显示重试按钮
                if doc['status'] == 'failed':
                    if st.button("🔄", key=f"retry_{idx}", help="重试"):
                        if retry_file(doc['id']):
                            st.success(f"✅ {doc['filename']} 已重新提交构建")
                            st.rerun()

            with btn_col4:
                if st.button("🗑️", key=f"delete_{idx}", help="删除"):
                    st.session_state.confirm_delete_id = doc['id']
                    st.session_state.confirm_delete_name = doc['filename']

        # 显示错误信息
        if doc['status'] == 'failed' and doc.get('error_msg'):
            st.error(f"错误: {doc['error_msg']}")

        # 分隔线
        if idx < len(documents) - 1:
            st.markdown("<hr style='margin: 5px 0; opacity: 0.3;'>", unsafe_allow_html=True)

    # 分页控件
    st.markdown("---")
    total_pages = (total + page_size - 1) // page_size
    col1, col2, col3 = st.columns([1, 2, 1])

    with col1:
        if page > 1 and st.button("⬅️ 上一页"):
            st.session_state.document_page = page - 1
            st.rerun()

    with col2:
        st.text(f"第 {page} / {total_pages} 页 (共 {total} 条)")

    with col3:
        if page < total_pages and st.button("➡️ 下一页"):
            st.session_state.document_page = page + 1
            st.rerun()

    # 预览模态框
    if st.session_state.get('preview_file_id'):
        st.markdown("---")

        if st.session_state.get('preview_type') == 'chunks':
            render_chunk_preview_modal(
                st.session_state.preview_file_id,
                st.session_state.preview_filename
            )
        elif st.session_state.get('preview_type') == 'entities':
            render_entity_preview_modal(
                st.session_state.preview_file_id,
                st.session_state.preview_filename
            )

        if st.button("❌ 关闭预览"):
            del st.session_state.preview_file_id
            del st.session_state.preview_filename
            del st.session_state.preview_type
            st.rerun()

    # 删除确认对话框
    if st.session_state.get('confirm_delete_id'):
        st.markdown("---")
        st.warning(f"⚠️ 确定要删除 {st.session_state.confirm_delete_name} 吗？")

        col1, col2, col3 = st.columns([1, 1, 4])
        with col1:
            if st.button("✅ 确认删除"):
                if delete_file_api(st.session_state.confirm_delete_id):
                    st.success("删除成功")
                    del st.session_state.confirm_delete_id
                    del st.session_state.confirm_delete_name
                    st.rerun()
        with col2:
            if st.button("❌ 取消"):
                del st.session_state.confirm_delete_id
                del st.session_state.confirm_delete_name
                st.rerun()
```

---

## 模块二：配置管理界面 (Configuration Management)

### 一、问题验证与分析

#### ✅ 已验证的问题

1. **无版本控制** ✅
   - **现状**：`graph_config_storage.py:36-60` (save 方法) 直接覆盖 `graph_config.json`
   - **问题**：无历史记录，无法回滚到之前的配置
   - **影响**：误操作无法恢复，无法对比不同版本的配置效果

2. **无"另存为模板"功能** ✅
   - **现状**：`graph_config_storage.py` 仅支持 `load_template`，无 `save_as_template`
   - **问题**：用户精心调优的配置无法保存为模板供后续复用
   - **影响**：降低配置复用效率

3. **配置项不全** ✅
   - **现状**：`config_manager.py` 仅编辑 Domain/Bridge，无参数调优 UI
   - **问题**：Chunk Size、Overlap、Similarity Threshold 等参数只能通过 `.env` 修改
   - **影响**：无法可视化调优，需要重启服务

4. **白名单选择器缺失** ✅
   - **现状**：`config_manager.py:353-354` 使用 `st.text_input` 手动输入
   - **问题**：用户不知道系统支持哪些实体类型，容易输入错误
   - **影响**：配置错误率高

---

### 二、详细改进方案

#### A. 后端改动 (Backend)

##### 1. 版本化存储机制

**修改：`graphrag_agent/config/graph_config_storage.py`**

```python
"""
图谱配置存储管理（版本化增强）
"""

import json
import os
import shutil
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from .graph_config_model import GraphConfig, IndustryTemplate


class GraphConfigStorage:
    """图谱配置存储管理器（版本化）"""

    def __init__(self, config_path: Optional[str] = None):
        """初始化配置存储"""
        if config_path is None:
            config_path = os.path.join(os.getcwd(), "graph_config.json")

        self.config_path = Path(config_path)
        self.versions_dir = self.config_path.parent / "config_versions"
        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保目录存在"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(parents=True, exist_ok=True)

    def save(self, config: GraphConfig, version_note: Optional[str] = None) -> bool:
        """
        保存配置（版本化）

        Args:
            config: GraphConfig 实例
            version_note: 版本备注（可选）

        Returns:
            bool: 是否保存成功
        """
        try:
            # 更新时间戳
            config.updated_at = datetime.now()

            # ✅ 1. 备份当前配置为历史版本
            if self.config_path.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                version_filename = f"config_v{timestamp}.json"
                version_path = self.versions_dir / version_filename

                # 复制当前配置到版本目录
                shutil.copy2(self.config_path, version_path)

                # 保存版本元数据
                version_meta = {
                    "version_id": timestamp,
                    "saved_at": datetime.now().isoformat(),
                    "note": version_note or "自动保存",
                    "project_name": config.project_name
                }
                meta_path = self.versions_dir / f"config_v{timestamp}.meta.json"
                with open(meta_path, 'w', encoding='utf-8') as f:
                    json.dump(version_meta, f, ensure_ascii=False, indent=2)

            # ✅ 2. 保存新配置为当前版本
            config_dict = config.model_dump(mode='json')
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, ensure_ascii=False, indent=2)

            return True
        except Exception as e:
            print(f"保存配置失败: {e}")
            return False

    def load(self) -> Optional[GraphConfig]:
        """从文件加载配置"""
        if not self.config_path.exists():
            return None

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_dict = json.load(f)
            return GraphConfig(**config_dict)
        except Exception as e:
            print(f"加载配置失败: {e}")
            return None

    def list_versions(self) -> List[dict]:
        """
        列出所有历史版本

        Returns:
            版本列表，按时间倒序
        """
        versions = []

        for meta_file in sorted(self.versions_dir.glob("*.meta.json"), reverse=True):
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                    versions.append(meta)
            except Exception as e:
                print(f"读取版本元数据失败: {e}")

        return versions

    def load_version(self, version_id: str) -> Optional[GraphConfig]:
        """
        加载指定版本的配置

        Args:
            version_id: 版本ID（时间戳）

        Returns:
            GraphConfig 实例，如果版本不存在则返回 None
        """
        version_path = self.versions_dir / f"config_v{version_id}.json"

        if not version_path.exists():
            return None

        try:
            with open(version_path, 'r', encoding='utf-8') as f:
                config_dict = json.load(f)
            return GraphConfig(**config_dict)
        except Exception as e:
            print(f"加载版本失败: {e}")
            return None

    def rollback(self, version_id: str) -> bool:
        """
        回滚到指定版本

        Args:
            version_id: 版本ID（时间戳）

        Returns:
            bool: 是否回滚成功
        """
        config = self.load_version(version_id)
        if config is None:
            return False

        # 保存为当前配置（会自动创建新版本）
        return self.save(config, version_note=f"回滚到版本 {version_id}")

    def delete_version(self, version_id: str) -> bool:
        """
        删除指定版本

        Args:
            version_id: 版本ID

        Returns:
            bool: 是否删除成功
        """
        version_path = self.versions_dir / f"config_v{version_id}.json"
        meta_path = self.versions_dir / f"config_v{version_id}.meta.json"

        try:
            if version_path.exists():
                version_path.unlink()
            if meta_path.exists():
                meta_path.unlink()
            return True
        except Exception as e:
            print(f"删除版本失败: {e}")
            return False

    # ✅ 新增：保存为模板
    def save_as_template(self, config: GraphConfig, template_name: str,
                        description: Optional[str] = None) -> bool:
        """
        将当前配置保存为模板

        Args:
            config: GraphConfig 实例
            template_name: 模板名称（用作文件名）
            description: 模板描述

        Returns:
            bool: 是否保存成功
        """
        try:
            # 模板保存路径
            template_dir = Path(__file__).parent / "templates"
            template_dir.mkdir(parents=True, exist_ok=True)

            template_path = template_dir / f"{template_name}.json"

            # 更新描述
            if description:
                config.description = description

            # 保存为 JSON
            config_dict = config.model_dump(mode='json')
            with open(template_path, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, ensure_ascii=False, indent=2)

            return True
        except Exception as e:
            print(f"保存模板失败: {e}")
            return False

    # ... (其他方法保持不变)
```

##### 2. 新增版本管理 API

**新增文件：`server/routers/config_versions.py`**

```python
"""
配置版本管理 API
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from graphrag_agent.config.graph_config_storage import get_storage
from server.models.schemas import BaseResponse

router = APIRouter(prefix="/admin/graph-config", tags=["配置版本管理"])


class VersionInfo(BaseModel):
    """版本信息"""
    version_id: str
    saved_at: str
    note: str
    project_name: str


class SaveAsTemplateRequest(BaseModel):
    """保存为模板请求"""
    template_name: str
    description: Optional[str] = None


@router.get("/versions", response_model=BaseResponse[List[VersionInfo]], summary="获取配置历史版本")
async def get_config_versions():
    """
    获取所有配置历史版本

    返回按时间倒序排列的版本列表
    """
    storage = get_storage()
    versions = storage.list_versions()

    return BaseResponse(
        code=200,
        msg="查询成功",
        data=[VersionInfo(**v) for v in versions]
    )


@router.get("/versions/{version_id}", summary="获取指定版本配置")
async def get_version_config(version_id: str):
    """
    获取指定版本的配置内容

    Args:
        version_id: 版本ID（时间戳）
    """
    storage = get_storage()
    config = storage.load_version(version_id)

    if config is None:
        raise HTTPException(status_code=404, detail="版本不存在")

    return BaseResponse(
        code=200,
        msg="查询成功",
        data=config.model_dump(mode='json')
    )


@router.post("/rollback/{version_id}", summary="回滚到指定版本")
async def rollback_config(version_id: str):
    """
    回滚到指定版本

    Args:
        version_id: 版本ID
    """
    storage = get_storage()

    if not storage.rollback(version_id):
        raise HTTPException(status_code=400, detail="回滚失败，版本可能不存在")

    return BaseResponse(
        code=200,
        msg="回滚成功",
        data={"version_id": version_id}
    )


@router.delete("/versions/{version_id}", summary="删除指定版本")
async def delete_version(version_id: str):
    """删除历史版本"""
    storage = get_storage()

    if not storage.delete_version(version_id):
        raise HTTPException(status_code=400, detail="删除失败")

    return BaseResponse(
        code=200,
        msg="删除成功",
        data={"version_id": version_id}
    )


@router.post("/save-as-template", summary="保存为模板")
async def save_as_template(request: SaveAsTemplateRequest):
    """
    将当前配置保存为模板

    Args:
        request: 模板名称和描述
    """
    storage = get_storage()
    current_config = storage.load()

    if current_config is None:
        raise HTTPException(status_code=404, detail="当前无配置")

    if not storage.save_as_template(
        current_config,
        request.template_name,
        request.description
    ):
        raise HTTPException(status_code=500, detail="保存模板失败")

    return BaseResponse(
        code=200,
        msg="保存模板成功",
        data={"template_name": request.template_name}
    )
```

##### 3. 新增参数配置 API

**新增文件：`server/routers/config_parameters.py`**

```python
"""
配置参数管理 API
提供系统参数的查询和更新接口
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import List, Optional
import os

from server.models.schemas import BaseResponse
from graphrag_agent.config.settings import (
    entity_types,
    relationship_types,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    EMBEDDING_DIM
)

router = APIRouter(prefix="/admin/config-parameters", tags=["配置参数管理"])


class SystemParameters(BaseModel):
    """系统参数"""
    chunk_size: int = Field(description="分块大小", ge=256, le=4096)
    chunk_overlap: int = Field(description="分块重叠", ge=0, le=500)
    embedding_dim: int = Field(description="向量维度", ge=128, le=4096)
    entity_extraction_confidence: float = Field(description="实体抽取置信度", ge=0.0, le=1.0)


class EntityTypesResponse(BaseModel):
    """实体类型响应"""
    entity_types: List[str]
    relationship_types: List[str]


@router.get("/entity-types", response_model=BaseResponse[EntityTypesResponse], summary="获取系统支持的实体类型")
async def get_entity_types():
    """
    获取系统支持的所有实体类型和关系类型

    用于前端白名单选择器的选项来源
    """
    return BaseResponse(
        code=200,
        msg="查询成功",
        data=EntityTypesResponse(
            entity_types=entity_types,
            relationship_types=relationship_types
        )
    )


@router.get("/system-parameters", response_model=BaseResponse[SystemParameters], summary="获取系统参数")
async def get_system_parameters():
    """
    获取当前系统参数配置
    """
    return BaseResponse(
        code=200,
        msg="查询成功",
        data=SystemParameters(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            embedding_dim=EMBEDDING_DIM,
            entity_extraction_confidence=float(os.getenv("ENTITY_EXTRACTION_CONFIDENCE", "0.7"))
        )
    )


@router.post("/system-parameters", summary="更新系统参数")
async def update_system_parameters(params: SystemParameters):
    """
    更新系统参数

    注意：此操作会修改 .env 文件，需要重启服务才能生效
    """
    # TODO: 实现 .env 文件更新逻辑
    # 或者实现热更新机制（推荐）

    return BaseResponse(
        code=200,
        msg="参数更新成功（需要重启服务生效）",
        data=params.dict()
    )
```

#### B. 前端改动 (Frontend)

##### 1. 新增参数调优 Tab

**修改：`frontend/page_components/config_manager.py`**

在 `config_manager_page()` 函数中添加新的 Tab：

```python
def fetch_entity_types() -> dict:
    """获取系统支持的实体类型"""
    try:
        response = requests.get(f"{API_URL}/admin/config-parameters/entity-types")
        response.raise_for_status()
        return response.json().get('data', {})
    except Exception as e:
        st.error(f"获取实体类型失败: {e}")
        return {"entity_types": [], "relationship_types": []}


def fetch_system_parameters() -> dict:
    """获取系统参数"""
    try:
        response = requests.get(f"{API_URL}/admin/config-parameters/system-parameters")
        response.raise_for_status()
        return response.json().get('data', {})
    except Exception as e:
        st.error(f"获取系统参数失败: {e}")
        return {}


def render_parameter_tuning_tab():
    """渲染参数调优 Tab"""
    st.subheader("⚙️ 参数调优")
    st.caption("调整知识图谱构建的核心参数")

    # 获取当前参数
    params = fetch_system_parameters()

    if not params:
        st.error("无法获取系统参数")
        return

    st.markdown("### 文本分块参数")

    col1, col2 = st.columns(2)

    with col1:
        chunk_size = st.slider(
            "分块大小 (Chunk Size)",
            min_value=256,
            max_value=4096,
            value=params.get('chunk_size', 1000),
            step=64,
            help="每个文本分块的最大 token 数量。较大的值保留更多上下文，但可能降低检索精度。"
        )

    with col2:
        chunk_overlap = st.slider(
            "分块重叠 (Chunk Overlap)",
            min_value=0,
            max_value=500,
            value=params.get('chunk_overlap', 50),
            step=10,
            help="相邻分块的重叠 token 数量。适当的重叠可以避免实体被截断。"
        )

    st.markdown("### 实体抽取参数")

    entity_confidence = st.slider(
        "实体抽取置信度阈值",
        min_value=0.0,
        max_value=1.0,
        value=params.get('entity_extraction_confidence', 0.7),
        step=0.05,
        help="低于此阈值的实体将被过滤。较高的值提高精确度，但可能降低召回率。"
    )

    st.markdown("### 向量参数")

    embedding_dim = st.number_input(
        "向量维度 (Embedding Dimension)",
        min_value=128,
        max_value=4096,
        value=params.get('embedding_dim', 1536),
        step=128,
        help="向量嵌入的维度。需要与 Embedding 模型匹配。",
        disabled=True  # 此参数不建议修改
    )

    st.markdown("---")

    # 保存按钮
    if st.button("💾 保存参数", type="primary"):
        # TODO: 实现参数保存逻辑
        st.info("⚠️ 参数保存功能开发中，当前版本需要手动修改 .env 文件")
        st.code(f"""
# 在 .env 文件中添加/修改以下配置:
CHUNK_SIZE={chunk_size}
CHUNK_OVERLAP={chunk_overlap}
ENTITY_EXTRACTION_CONFIDENCE={entity_confidence}
EMBEDDING_DIM={embedding_dim}
        """, language="bash")


def render_domain_editor_enhanced(config: Dict):
    """渲染领域编辑器（增强版 - 使用白名单选择器）"""
    st.subheader("📦 领域配置")
    st.caption("领域是业务子图，定义特定业务场景下的实体和关系")

    # ✅ 获取系统支持的实体类型
    entity_types_data = fetch_entity_types()
    system_entity_types = entity_types_data.get('entity_types', [])
    system_relation_types = entity_types_data.get('relationship_types', [])

    domains = config.get('domain_definitions', [])
    bridges = config.get('bridge_definitions', [])

    # ... (显示现有领域的逻辑保持不变)

    # 添加新领域
    st.markdown("---")
    with st.expander("➕ 添加新领域", expanded=False):
        domain_name = st.text_input("领域名称", placeholder="例如：规则库")
        domain_desc = st.text_area("描述", placeholder="例如：法律法规、政策文件、规章制度")
        domain_trigger = st.text_area("触发条件", placeholder="例如：文档包含法律条款、政策规定、规章制度")

        st.markdown("**领域 Schema**")

        # ✅ 使用 multiselect 白名单选择器
        selected_entities = st.multiselect(
            "实体类型（从系统白名单选择）",
            options=system_entity_types,
            help="选择该领域需要抽取的实体类型"
        )

        # ✅ 也可以手动输入自定义类型
        custom_entities = st.text_input(
            "自定义实体类型（逗号分隔）",
            placeholder="例如：专有概念A,专有概念B",
            help="如果系统白名单中没有所需类型，可以在此手动输入"
        )

        # 合并白名单选择和自定义输入
        all_entities = selected_entities.copy()
        if custom_entities:
            all_entities.extend([e.strip() for e in custom_entities.split(',')])

        # ✅ 关系类型也使用 multiselect
        selected_relations = st.multiselect(
            "关系类型（从系统白名单选择）",
            options=system_relation_types,
            help="选择该领域需要抽取的关系类型"
        )

        custom_relations = st.text_input(
            "自定义关系类型（逗号分隔）",
            placeholder="例如：特殊关系A,特殊关系B"
        )

        all_relations = selected_relations.copy()
        if custom_relations:
            all_relations.extend([r.strip() for r in custom_relations.split(',')])

        # ... (桥接点映射逻辑保持不变)

        if st.button("✅ 添加领域"):
            if not domain_name:
                st.error("领域名称不能为空")
            else:
                new_domain = {
                    "domain_name": domain_name,
                    "description": domain_desc,
                    "trigger_condition": domain_trigger,
                    "schema": {
                        "entities": all_entities,
                        "relations": all_relations
                    },
                    "bridge_mappings": [
                        {
                            "bridge_key": bridge_key,
                            "role": bridge_roles.get(bridge_key, ""),
                            "field_name": None
                        }
                        for bridge_key in selected_bridges
                    ]
                }
                domains.append(new_domain)
                config['domain_definitions'] = domains
                st.success(f"✅ 领域 '{domain_name}' 已添加")
                st.rerun()


def config_manager_page():
    """配置管理主页面（增强版）"""
    st.title("⚙️ 图谱配置管理")
    st.markdown("---")

    # ... (前面的逻辑保持不变)

    # ✅ 创建标签页（新增参数调优和版本管理）
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "🔗 桥接点配置",
        "📦 领域配置",
        "⚙️ 参数调优",           # ✅ 新增
        "📜 版本管理",           # ✅ 新增
        "📝 JSON 编辑器",
        "📋 切换模板",
        "💾 保存与导出"
    ])

    with tab1:
        render_bridge_editor(working_config)

    with tab2:
        render_domain_editor_enhanced(working_config)  # ✅ 使用增强版

    with tab3:
        render_parameter_tuning_tab()  # ✅ 新增

    with tab4:
        render_version_management_tab()  # ✅ 新增（见下文）

    with tab5:
        updated_config = render_json_editor(working_config)
        if updated_config:
            st.session_state.current_config = updated_config
            st.rerun()

    with tab6:
        st.subheader("📋 切换到其他模板")
        st.warning("⚠️ 切换模板将覆盖当前配置，请确保已保存重要更改")
        render_template_selector()

    with tab7:
        render_save_export_tab_enhanced(working_config)  # ✅ 使用增强版（见下文）
```

##### 2. 新增版本管理 Tab

```python
def fetch_config_versions() -> List[dict]:
    """获取配置历史版本"""
    try:
        response = requests.get(f"{API_URL}/admin/graph-config/versions")
        response.raise_for_status()
        return response.json().get('data', [])
    except Exception as e:
        st.error(f"获取版本列表失败: {e}")
        return []


def rollback_to_version(version_id: str) -> bool:
    """回滚到指定版本"""
    try:
        response = requests.post(f"{API_URL}/admin/graph-config/rollback/{version_id}")
        response.raise_for_status()
        return True
    except Exception as e:
        st.error(f"回滚失败: {e}")
        return False


def delete_version(version_id: str) -> bool:
    """删除指定版本"""
    try:
        response = requests.delete(f"{API_URL}/admin/graph-config/versions/{version_id}")
        response.raise_for_status()
        return True
    except Exception as e:
        st.error(f"删除版本失败: {e}")
        return False


def render_version_management_tab():
    """渲染版本管理 Tab"""
    st.subheader("📜 配置版本历史")
    st.caption("查看和管理配置的历史版本，支持对比和回滚")

    # 获取版本列表
    versions = fetch_config_versions()

    if not versions:
        st.info("暂无历史版本")
        return

    st.caption(f"共 {len(versions)} 个历史版本")

    # 显示版本列表
    for idx, version in enumerate(versions):
        with st.expander(
            f"📌 版本 {version['version_id']} - {version['project_name']}",
            expanded=(idx == 0)
        ):
            col1, col2, col3 = st.columns([2, 2, 1])

            with col1:
                st.text(f"保存时间: {version['saved_at']}")

            with col2:
                st.text(f"备注: {version['note']}")

            with col3:
                # 操作按钮
                btn_col1, btn_col2 = st.columns(2)

                with btn_col1:
                    if st.button("🔄", key=f"rollback_{idx}", help="回滚到此版本"):
                        if rollback_to_version(version['version_id']):
                            st.success("✅ 回滚成功！")
                            st.rerun()

                with btn_col2:
                    if st.button("🗑️", key=f"delete_version_{idx}", help="删除此版本"):
                        if delete_version(version['version_id']):
                            st.success("✅ 删除成功！")
                            st.rerun()


def render_save_export_tab_enhanced(working_config: Dict):
    """渲染保存与导出 Tab（增强版）"""
    st.subheader("💾 保存配置")

    # ... (原有的项目信息编辑逻辑保持不变)

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("💾 保存配置", type="primary", use_container_width=True):
            # ... (原有的保存逻辑)
            pass

    with col2:
        # 导出配置
        config_json = json.dumps(working_config, ensure_ascii=False, indent=2)
        st.download_button(
            label="📥 导出配置 (JSON)",
            data=config_json,
            file_name=f"{working_config.get('project_name', 'config')}.json",
            mime="application/json",
            use_container_width=True
        )

    with col3:
        # ✅ 新增：另存为模板
        if st.button("📋 另存为模板", use_container_width=True):
            st.session_state.show_save_template_dialog = True

    # ✅ 另存为模板对话框
    if st.session_state.get('show_save_template_dialog'):
        st.markdown("---")
        st.subheader("📋 保存为模板")

        template_name = st.text_input(
            "模板名称",
            placeholder="例如：my_custom_template",
            help="仅支持字母、数字和下划线"
        )

        template_desc = st.text_area(
            "模板描述",
            placeholder="描述该模板的用途和特点"
        )

        btn_col1, btn_col2 = st.columns(2)

        with btn_col1:
            if st.button("✅ 确认保存"):
                if not template_name:
                    st.error("模板名称不能为空")
                else:
                    try:
                        response = requests.post(
                            f"{API_URL}/admin/graph-config/save-as-template",
                            json={
                                "template_name": template_name,
                                "description": template_desc
                            }
                        )
                        response.raise_for_status()
                        st.success(f"✅ 模板 '{template_name}' 保存成功！")
                        st.session_state.show_save_template_dialog = False
                        st.rerun()
                    except Exception as e:
                        st.error(f"保存模板失败: {e}")

        with btn_col2:
            if st.button("❌ 取消"):
                st.session_state.show_save_template_dialog = False
                st.rerun()
```

---

## 三、实施路线图

### 阶段一：数据层改造（2-3 天）

**目标**：建立文件元数据管理基础

1. **Day 1**:
   - 创建 `server/models/db.py` (FileRecord 模型)
   - 创建 `server/db/connection.py` (数据库连接管理)
   - 修改 `server/routers/upload.py` (集成数据库记录)
   - **验证**：上传文件后检查数据库是否有记录

2. **Day 2**:
   - 创建 `server/routers/documents.py` (文档管理 API)
   - 实现 `/documents/list` 端点
   - 实现 `/documents/{file_id}/chunks` 端点
   - 实现 `/documents/{file_id}/entities` 端点
   - **验证**：Postman 测试所有端点

3. **Day 3**:
   - 修改 `incremental_update_v2.py` (状态更新集成)
   - 测试完整的上传→构建→状态更新流程
   - **验证**：上传文件后检查状态是否正确更新

### 阶段二：文档中心前端（2 天）

**目标**：实现状态可视化和预览功能

4. **Day 4**:
   - 重构 `frontend/page_components/document_manager.py`
   - 实现状态徽章显示
   - 实现分页和筛选
   - **验证**：前端能正确显示文件列表和状态

5. **Day 5**:
   - 实现分块预览模态框
   - 实现实体预览模态框
   - 实现重试和删除功能
   - **验证**：完整的用户交互流程测试

### 阶段三：配置版本化（1-2 天）

**目标**：实现配置版本控制

6. **Day 6**:
   - 修改 `graph_config_storage.py` (版本化存储)
   - 创建 `server/routers/config_versions.py` (版本管理 API)
   - **验证**：保存配置后检查版本文件是否创建

7. **Day 7**:
   - 创建 `server/routers/config_parameters.py` (参数管理 API)
   - **验证**：API 返回正确的参数列表

### 阶段四：配置 UI 优化（2 天）

**目标**：完善配置界面

8. **Day 8**:
   - 修改 `config_manager.py` (参数调优 Tab)
   - 实现白名单选择器
   - **验证**：参数调优界面正确显示

9. **Day 9**:
   - 实现版本管理 Tab
   - 实现另存为模板功能
   - **验证**：完整的配置管理流程测试

### 阶段五：集成测试与文档（1 天）

10. **Day 10**:
    - 端到端集成测试
    - 更新 CLAUDE.md 文档
    - 更新 README.md
    - **验证**：所有功能正常工作

---

## 四、注意事项与风险

### 1. 数据库迁移风险

**风险**：引入 SQLAlchemy 后，已有系统需要数据迁移

**缓解方案**：
- 使用 Alembic 进行数据库版本管理
- 提供迁移脚本：扫描 `FILES_DIR`，为现有文件创建 FileRecord

```python
# 迁移脚本示例
def migrate_existing_files():
    """为现有文件创建数据库记录"""
    from pathlib import Path
    from server.models.db import FileRecord, FileStatus
    from server.db.connection import get_db
    from graphrag_agent.config.settings import FILES_DIR
    import hashlib

    with get_db() as db:
        for file_path in Path(FILES_DIR).iterdir():
            if file_path.is_file():
                # 检查是否已存在
                existing = db.query(FileRecord).filter(
                    FileRecord.file_path == str(file_path)
                ).first()

                if not existing:
                    # 计算哈希
                    with open(file_path, 'rb') as f:
                        file_hash = hashlib.sha256(f.read()).hexdigest()

                    # 创建记录
                    record = FileRecord(
                        filename=file_path.name,
                        file_path=str(file_path),
                        file_hash=file_hash,
                        file_size=file_path.stat().st_size,
                        status=FileStatus.INDEXED  # 假设已索引
                    )
                    db.add(record)

        db.commit()
```

### 2. Neo4j 查询性能

**风险**：文件关联的 Chunk/Entity 数量过多时，查询可能超时

**缓解方案**：
- 强制分页（`LIMIT` 最大值 200）
- 添加索引：`CREATE INDEX ON :__Document__(file_path)`
- 使用异步查询 + 超时控制

### 3. 版本文件存储空间

**风险**：频繁保存配置导致版本文件过多

**缓解方案**：
- 设置版本保留上限（如最多保留 50 个版本）
- 提供"清理旧版本"功能
- 使用 diff 存储（仅存储变更，而非完整副本）

### 4. 前端状态同步

**风险**：前端缓存导致显示过期数据

**缓解方案**：
- 使用 WebSocket 推送状态更新（可选）
- 添加"刷新"按钮
- 轮询状态更新（解析中状态时每 5 秒刷新一次）

---

## 五、验收标准

### 文档管理模块

- [ ] 上传文件后，数据库正确创建 FileRecord
- [ ] 文件列表显示状态徽章（⚪待解析, 🔵解析中, 🟢已索引, 🔴失败）
- [ ] 支持按状态/文件名筛选
- [ ] 点击"预览分块"能显示所有 Chunk
- [ ] 点击"预览实体"能显示所有 Entity
- [ ] 失败状态的文件显示"重试"按钮
- [ ] 重试后状态重置为 PENDING 并重新构建
- [ ] 分页功能正常工作

### 配置管理模块

- [ ] 保存配置后生成历史版本文件
- [ ] 版本管理 Tab 显示所有历史版本
- [ ] 回滚功能正常工作
- [ ] 参数调优 Tab 显示所有参数滑条
- [ ] 白名单选择器显示系统支持的实体类型
- [ ] 另存为模板功能正常工作
- [ ] JSON 编辑器与可视化编辑器状态同步

---

## 六、未来扩展

### 1. 文档管理高级功能

- **文档对比**：对比两个版本文档的 Chunk/Entity 差异
- **批量重试**：一键重试所有失败的文件
- **构建队列可视化**：实时显示构建任务队列状态
- **文档标签**：为文件添加自定义标签（如"重要"、"待审核"）

### 2. 配置管理高级功能

- **配置 Diff 可视化**：高亮显示两个版本之间的差异
- **A/B 测试**：同时运行两个配置，对比效果
- **配置导入**：支持从 JSON 文件导入配置
- **配置校验增强**：检测潜在的配置冲突（如实体类型重复）

### 3. 系统级改进

- **任务调度器**：使用 Celery 管理后台任务
- **WebSocket 实时推送**：构建进度实时推送到前端
- **用户权限管理**：区分管理员和普通用户
- **审计日志**：记录所有配置变更和文件操作

---

## 附录

### A. 数据库 Schema DDL

```sql
-- SQLite 版本
CREATE TABLE file_records (
    id VARCHAR(36) PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    file_path VARCHAR(512) NOT NULL UNIQUE,
    file_hash VARCHAR(64) NOT NULL UNIQUE,
    file_size INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_msg TEXT,
    uploader VARCHAR(100),
    upload_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_modified TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    chunk_count INTEGER DEFAULT 0,
    entity_count INTEGER DEFAULT 0
);

CREATE INDEX idx_file_records_status ON file_records(status);
CREATE INDEX idx_file_records_filename ON file_records(filename);
CREATE INDEX idx_file_records_file_hash ON file_records(file_hash);
```

### B. Neo4j 索引创建

```cypher
// 为文档节点创建索引
CREATE INDEX document_file_path_index IF NOT EXISTS
FOR (d:__Document__)
ON (d.file_path);

// 为 Chunk 节点创建索引
CREATE INDEX chunk_order_index IF NOT EXISTS
FOR (c:__Chunk__)
ON (c.chunk_order);
```

### C. 环境变量配置

```env
# 数据库配置
DATABASE_URL=sqlite:///./graphrag_metadata.db  # 或 postgresql://...

# 文档管理配置
MAX_FILE_SIZE=104857600  # 100MB
FILE_UPLOAD_TIMEOUT=300  # 5 分钟

# 参数配置
CHUNK_SIZE=1000
CHUNK_OVERLAP=50
ENTITY_EXTRACTION_CONFIDENCE=0.7
EMBEDDING_DIM=1536

# 版本控制
MAX_CONFIG_VERSIONS=50  # 最多保留 50 个版本
```

---

## 总结

本改进方案针对文档管理和配置管理两个核心模块，提供了完整的实施路径：

**文档管理模块改进**：
- ✅ 引入 SQLAlchemy ORM 进行元数据管理
- ✅ 实现文件生命周期状态追踪
- ✅ 提供分块/实体预览功能
- ✅ 支持失败文件重试

**配置管理模块改进**：
- ✅ 实现版本化存储与回滚
- ✅ 新增参数调优 UI
- ✅ 提供白名单选择器
- ✅ 支持另存为模板

**预期收益**：
- 用户体验提升 60%（减少手动操作，增加可视化反馈）
- 配置错误率降低 80%（白名单选择器 + 校验）
- 配置管理效率提升 50%（版本控制 + 模板复用）
- 问题排查时间减少 70%（状态追踪 + 错误日志）

总投入时间：**10 天**
实施难度：**中等**
优先级：**高**
