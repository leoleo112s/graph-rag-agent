"""
模型管理 API

提供LLM和Embedding模型的注册、切换、管理功能。
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from graphrag_agent.models.model_manager import ModelConfig, get_model_manager

router = APIRouter(prefix="/admin/models", tags=["models"])
logger = logging.getLogger(__name__)


class RegisterModelRequest(BaseModel):
    """注册模型请求"""

    name: str
    model_type: str  # llm | embedding
    provider: str  # openai | local | custom
    config: Dict[str, Any]  # model配置 (model, api_key, base_url等)
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    set_active: bool = False


class ActivateModelRequest(BaseModel):
    """激活模型请求"""

    model_id: str


@router.get("/")
async def list_models(
    model_type: Optional[str] = None, provider: Optional[str] = None, active_only: bool = False
) -> Dict[str, Any]:
    """
    获取模型列表

    Args:
        model_type: 过滤模型类型 (llm | embedding)
        provider: 过滤提供商 (openai | local | custom)
        active_only: 仅返回活跃模型

    Returns:
        模型列表
    """
    try:
        manager = get_model_manager()
        models = manager.list_models(model_type=model_type, provider=provider, active_only=active_only)

        return {"models": [m.model_dump() for m in models], "total": len(models)}

    except Exception as e:
        logger.error(f"Failed to list models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{model_id}")
async def get_model(model_id: str) -> Dict[str, Any]:
    """
    获取模型详情

    Args:
        model_id: 模型ID

    Returns:
        模型详情
    """
    try:
        manager = get_model_manager()
        model = manager.get_model(model_id)

        if not model:
            raise HTTPException(status_code=404, detail="Model not found")

        return {"model": model.model_dump()}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get model: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/register")
async def register_model(request: RegisterModelRequest) -> Dict[str, Any]:
    """
    注册新模型

    Args:
        request: 注册请求

    Returns:
        创建的模型信息
    """
    try:
        manager = get_model_manager()

        # 验证模型类型
        if request.model_type not in ["llm", "embedding"]:
            raise HTTPException(status_code=400, detail="model_type must be 'llm' or 'embedding'")

        # 验证提供商
        if request.provider not in ["openai", "local", "custom"]:
            raise HTTPException(status_code=400, detail="provider must be 'openai', 'local', or 'custom'")

        # 验证配置
        if not request.config.get("model"):
            raise HTTPException(status_code=400, detail="config must contain 'model' field")

        # 注册模型
        model_id = manager.register_model(
            name=request.name,
            model_type=request.model_type,
            provider=request.provider,
            config=request.config,
            description=request.description,
            tags=request.tags or [],
            set_active=request.set_active,
        )

        model = manager.get_model(model_id)

        return {"status": "success", "model_id": model_id, "model": model.model_dump() if model else None}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to register model: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/activate")
async def activate_model(request: ActivateModelRequest) -> Dict[str, Any]:
    """
    激活模型（设为当前活跃）

    Args:
        request: 激活请求

    Returns:
        激活结果
    """
    try:
        manager = get_model_manager()

        # 验证模型是否存在
        model = manager.get_model(request.model_id)
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")

        # 激活模型
        success = manager.activate_model(request.model_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to activate model")

        # 重新加载模型实例
        manager.reload_models()

        return {
            "status": "success",
            "message": f"Model '{model.name}' activated successfully",
            "model_id": request.model_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to activate model: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{model_id}")
async def delete_model(model_id: str) -> Dict[str, Any]:
    """
    删除模型

    Args:
        model_id: 模型ID

    Returns:
        删除结果
    """
    try:
        manager = get_model_manager()

        # 验证模型是否存在
        model = manager.get_model(model_id)
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")

        # 删除模型
        success = manager.delete_model(model_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete model")

        return {"status": "success", "message": f"Model '{model.name}' deleted successfully"}

    except HTTPException:
        raise
    except ValueError as e:
        # 不能删除默认模型
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete model: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reload")
async def reload_models() -> Dict[str, Any]:
    """
    重新加载模型（清空缓存）

    Returns:
        重载结果
    """
    try:
        manager = get_model_manager()
        manager.reload_models()

        return {"status": "success", "message": "Models reloaded successfully"}

    except Exception as e:
        logger.error(f"Failed to reload models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active/llm")
async def get_active_llm_info() -> Dict[str, Any]:
    """
    获取当前活跃的LLM模型信息

    Returns:
        LLM模型信息
    """
    try:
        manager = get_model_manager()
        active_llms = manager.list_models(model_type="llm", active_only=True)

        if not active_llms:
            raise HTTPException(status_code=404, detail="No active LLM model found")

        return {"model": active_llms[0].model_dump()}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get active LLM: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active/embedding")
async def get_active_embedding_info() -> Dict[str, Any]:
    """
    获取当前活跃的Embedding模型信息

    Returns:
        Embedding模型信息
    """
    try:
        manager = get_model_manager()
        active_embeddings = manager.list_models(model_type="embedding", active_only=True)

        if not active_embeddings:
            raise HTTPException(status_code=404, detail="No active embedding model found")

        return {"model": active_embeddings[0].model_dump()}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get active embedding: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/providers/list")
async def list_providers() -> Dict[str, Any]:
    """
    获取支持的提供商列表

    Returns:
        提供商列表
    """
    providers = [
        {"value": "openai", "label": "OpenAI", "description": "OpenAI API compatible models"},
        {"value": "local", "label": "Local", "description": "Local models (.gguf, adapters)"},
        {"value": "custom", "label": "Custom", "description": "Custom model configurations"},
    ]

    return {"providers": providers}
