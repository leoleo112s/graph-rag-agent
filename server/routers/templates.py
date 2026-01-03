"""
模板市场 API

提供图谱模板的浏览、下载、评分、发布等功能。
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from graphrag_agent.config.graph_config_model import GraphConfig
from graphrag_agent.config.graph_config_storage import GraphConfigStorage
from server.models.graph_template import GraphTemplate, TemplateRating, get_template_db

router = APIRouter(prefix="/admin/templates", tags=["templates"])
logger = logging.getLogger(__name__)


class PublishTemplateRequest(BaseModel):
    """发布模板请求"""

    name: str
    domain: str
    description: str
    tags: Optional[List[str]] = None
    author_id: str = "anonymous"
    author_name: str = "Anonymous"
    is_public: bool = True


class RateTemplateRequest(BaseModel):
    """评分请求"""

    rating: int  # 1-5
    comment: Optional[str] = None
    user_id: str = "anonymous"


class ApplyTemplateRequest(BaseModel):
    """应用模板请求"""

    template_id: str


@router.get("/")
async def list_templates(
    domain: Optional[str] = None,
    author_id: Optional[str] = None,
    is_official: Optional[bool] = None,
    sort_by: str = Query("rating", description="Sort by: rating, downloads, created_at"),
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    获取模板列表

    Args:
        domain: 过滤领域 (legal, medical, ecommerce, etc.)
        author_id: 过滤作者
        is_official: 过滤官方/非官方
        sort_by: 排序字段 (rating, downloads, created_at)
        limit: 返回数量
        offset: 偏移量

    Returns:
        模板列表
    """
    try:
        db = get_template_db()

        templates = db.list_templates(
            domain=domain, author_id=author_id, is_official=is_official, sort_by=sort_by, limit=limit, offset=offset
        )

        return {
            "templates": [t.model_dump() for t in templates],
            "total": len(templates),
            "limit": limit,
            "offset": offset,
        }

    except Exception as e:
        logger.error(f"Failed to list templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{template_id}")
async def get_template(template_id: str) -> Dict[str, Any]:
    """
    获取模板详情

    Args:
        template_id: 模板ID

    Returns:
        模板详情
    """
    try:
        db = get_template_db()
        template = db.get_template(template_id)

        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # 同时获取评分
        ratings = db.get_template_ratings(template_id, limit=10)

        return {"template": template.model_dump(), "ratings": [r.model_dump() for r in ratings]}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/publish")
async def publish_template(request: PublishTemplateRequest) -> Dict[str, Any]:
    """
    发布当前配置为模板

    将当前的 graph_config.json 转换为模板并发布到市场

    Args:
        request: 发布请求（包含名称、描述等元数据）

    Returns:
        创建的模板信息
    """
    try:
        # 加载当前配置
        storage = GraphConfigStorage()
        config = storage.load()

        if not config:
            raise HTTPException(status_code=400, detail="No configuration found. Please create a configuration first.")

        # 转换为JSON
        config_json = config.model_dump(mode="json")

        # 创建模板
        db = get_template_db()
        template_id = db.create_template(
            name=request.name,
            domain=request.domain,
            description=request.description,
            config_json=config_json,
            author_id=request.author_id,
            author_name=request.author_name,
            tags=request.tags or [],
            is_official=False,  # 用户发布的模板默认非官方
            is_public=request.is_public,
        )

        template = db.get_template(template_id)

        return {
            "status": "success",
            "template_id": template_id,
            "template": template.model_dump() if template else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to publish template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{template_id}/rate")
async def rate_template(template_id: str, request: RateTemplateRequest) -> Dict[str, Any]:
    """
    为模板评分

    Args:
        template_id: 模板ID
        request: 评分请求

    Returns:
        评分结果
    """
    try:
        db = get_template_db()

        # 验证模板是否存在
        template = db.get_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # 验证评分范围
        if not 1 <= request.rating <= 5:
            raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

        # 提交评分
        rating_id = db.rate_template(
            template_id=template_id, user_id=request.user_id, rating=request.rating, comment=request.comment
        )

        # 获取更新后的模板信息
        updated_template = db.get_template(template_id)

        return {
            "status": "success",
            "rating_id": rating_id,
            "template": updated_template.model_dump() if updated_template else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to rate template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{template_id}/download")
async def download_template(template_id: str) -> Dict[str, Any]:
    """
    下载模板（增加下载计数）

    Args:
        template_id: 模板ID

    Returns:
        模板配置
    """
    try:
        db = get_template_db()

        # 验证模板是否存在
        template = db.get_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # 增加下载次数
        db.increment_downloads(template_id)

        # 返回配置
        return {"status": "success", "template_id": template_id, "config": template.config_json}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/apply")
async def apply_template(request: ApplyTemplateRequest) -> Dict[str, Any]:
    """
    应用模板（一键替换当前配置）

    将选中的模板配置应用到当前的 graph_config.json

    Args:
        request: 应用请求（包含模板ID）

    Returns:
        应用结果
    """
    try:
        db = get_template_db()

        # 获取模板
        template = db.get_template(request.template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # 转换为GraphConfig对象
        config = GraphConfig(**template.config_json)

        # 保存到当前配置文件
        storage = GraphConfigStorage()
        success = storage.save(config)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to save configuration")

        # 增加下载次数
        db.increment_downloads(request.template_id)

        return {
            "status": "success",
            "message": f"Template '{template.name}' applied successfully",
            "template_id": request.template_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to apply template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{template_id}")
async def delete_template(template_id: str) -> Dict[str, Any]:
    """
    删除模板（仅作者或管理员）

    Args:
        template_id: 模板ID

    Returns:
        删除结果
    """
    try:
        db = get_template_db()

        # 验证模板是否存在
        template = db.get_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # TODO: 添加权限检查（仅作者或管理员可删除）

        # 删除模板
        success = db.delete_template(template_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete template")

        return {"status": "success", "message": f"Template '{template.name}' deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/domains/list")
async def list_domains() -> Dict[str, Any]:
    """
    获取所有可用的领域列表

    Returns:
        领域列表
    """
    from server.models.graph_template import TemplateDomain

    domains = [{"value": d.value, "label": d.name} for d in TemplateDomain]

    # 添加中文标签
    domain_labels = {
        "legal": "法务",
        "medical": "医疗",
        "ecommerce": "电商",
        "education": "教育",
        "finance": "金融",
        "government": "政府",
        "manufacturing": "制造业",
        "custom": "自定义",
    }

    for domain in domains:
        domain["label_zh"] = domain_labels.get(domain["value"], domain["value"])

    return {"domains": domains}
