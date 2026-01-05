"""
用户配置仓库管理 API
提供多配置的 CRUD 操作
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from graphrag_agent.config.graph_config_model import GraphConfig
from graphrag_agent.config.user_config_repository import ConfigMetadata, get_user_config_repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/configs", tags=["user_configs"])


# ==================== Request/Response Models ====================


class CreateConfigRequest(BaseModel):
    """创建配置请求"""

    config: GraphConfig
    name: str
    description: Optional[str] = None
    set_as_default: bool = False


class UpdateConfigRequest(BaseModel):
    """更新配置请求"""

    config: GraphConfig
    name: Optional[str] = None
    description: Optional[str] = None


class DuplicateConfigRequest(BaseModel):
    """复制配置请求"""

    new_name: str


# ==================== API Endpoints ====================


@router.get("/list")
async def list_configs():
    """
    获取所有用户配置列表

    Returns:
        配置元数据列表（按更新时间倒序）
    """
    logger.info("收到获取配置列表请求")

    try:
        repo = get_user_config_repository()
        configs = repo.list_configs()

        logger.info(f"返回 {len(configs)} 个配置")
        return {"configs": [c.model_dump(mode="json") for c in configs], "count": len(configs)}

    except Exception as e:
        logger.error(f"获取配置列表失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取配置列表失败: {str(e)}")


@router.get("/{config_id}")
async def get_config(config_id: str):
    """
    获取指定配置的完整内容

    Args:
        config_id: 配置ID

    Returns:
        配置内容（GraphConfig）
    """
    logger.info(f"收到获取配置请求: {config_id}")

    try:
        repo = get_user_config_repository()
        config = repo.get_config(config_id)

        if not config:
            logger.warning(f"配置不存在: {config_id}")
            raise HTTPException(status_code=404, detail=f"配置不存在: {config_id}")

        # 同时返回元数据
        metadata = repo.get_metadata(config_id)

        logger.info(f"返回配置: {metadata.name}")
        return {"config": config.model_dump(mode="json"), "metadata": metadata.model_dump(mode="json")}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.get("/default/get")
async def get_default_config():
    """
    获取默认配置

    Returns:
        默认配置的完整内容
    """
    logger.info("收到获取默认配置请求")

    try:
        repo = get_user_config_repository()
        config = repo.get_default_config()
        metadata = repo.get_default_metadata()

        if not config:
            logger.warning("当前无默认配置")
            return {"exists": False, "config": None, "metadata": None}

        logger.info(f"返回默认配置: {metadata.name}")
        return {"exists": True, "config": config.model_dump(mode="json"), "metadata": metadata.model_dump(mode="json")}

    except Exception as e:
        logger.error(f"获取默认配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取默认配置失败: {str(e)}")


@router.post("/create")
async def create_config(request: CreateConfigRequest):
    """
    创建新配置

    Args:
        request: 创建配置请求（包含配置内容、名称、描述等）

    Returns:
        新配置的ID和元数据
    """
    logger.info(f"收到创建配置请求: {request.name}")

    try:
        repo = get_user_config_repository()
        config_id = repo.create_config(
            config=request.config,
            name=request.name,
            description=request.description,
            set_as_default=request.set_as_default,
        )

        metadata = repo.get_metadata(config_id)

        logger.info(f"配置创建成功: {request.name} (ID: {config_id})")
        return {
            "message": "配置创建成功",
            "config_id": config_id,
            "metadata": metadata.model_dump(mode="json"),
        }

    except Exception as e:
        logger.error(f"创建配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建配置失败: {str(e)}")


@router.put("/{config_id}")
async def update_config(config_id: str, request: UpdateConfigRequest):
    """
    更新配置

    Args:
        config_id: 配置ID
        request: 更新配置请求

    Returns:
        更新结果
    """
    logger.info(f"收到更新配置请求: {config_id}")

    try:
        repo = get_user_config_repository()
        success = repo.update_config(
            config_id=config_id, config=request.config, name=request.name, description=request.description
        )

        if not success:
            raise HTTPException(status_code=404, detail=f"配置不存在: {config_id}")

        metadata = repo.get_metadata(config_id)

        logger.info(f"配置更新成功: {metadata.name}")
        return {
            "message": "配置更新成功",
            "config_id": config_id,
            "metadata": metadata.model_dump(mode="json"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@router.delete("/{config_id}")
async def delete_config(config_id: str):
    """
    删除配置

    Args:
        config_id: 配置ID

    Returns:
        删除结果
    """
    logger.info(f"收到删除配置请求: {config_id}")

    try:
        repo = get_user_config_repository()

        # 获取元数据（用于返回消息）
        metadata = repo.get_metadata(config_id)
        if not metadata:
            raise HTTPException(status_code=404, detail=f"配置不存在: {config_id}")

        # 如果是默认配置，禁止删除
        if metadata.is_default:
            configs = repo.list_configs()
            if len(configs) > 1:
                raise HTTPException(status_code=400, detail="无法删除默认配置，请先设置其他配置为默认")

        success = repo.delete_config(config_id)

        if not success:
            raise HTTPException(status_code=500, detail="删除配置失败")

        logger.info(f"配置删除成功: {metadata.name}")
        return {"message": f"配置已删除: {metadata.name}", "config_id": config_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除配置失败: {str(e)}")


@router.post("/{config_id}/set-default")
async def set_default_config(config_id: str):
    """
    设置默认配置

    Args:
        config_id: 配置ID

    Returns:
        设置结果
    """
    logger.info(f"收到设置默认配置请求: {config_id}")

    try:
        repo = get_user_config_repository()
        success = repo.set_default(config_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"配置不存在: {config_id}")

        metadata = repo.get_metadata(config_id)

        logger.info(f"默认配置已设置: {metadata.name}")
        return {"message": f"已设为默认配置: {metadata.name}", "config_id": config_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置默认配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"设置默认配置失败: {str(e)}")


@router.post("/{config_id}/duplicate")
async def duplicate_config(config_id: str, request: DuplicateConfigRequest):
    """
    复制配置

    Args:
        config_id: 源配置ID
        request: 复制配置请求（包含新名称）

    Returns:
        新配置的ID和元数据
    """
    logger.info(f"收到复制配置请求: {config_id} -> {request.new_name}")

    try:
        repo = get_user_config_repository()
        new_config_id = repo.duplicate_config(config_id, request.new_name)

        if not new_config_id:
            raise HTTPException(status_code=404, detail=f"源配置不存在: {config_id}")

        metadata = repo.get_metadata(new_config_id)

        logger.info(f"配置复制成功: {request.new_name} (ID: {new_config_id})")
        return {
            "message": "配置复制成功",
            "config_id": new_config_id,
            "metadata": metadata.model_dump(mode="json"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"复制配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"复制配置失败: {str(e)}")
