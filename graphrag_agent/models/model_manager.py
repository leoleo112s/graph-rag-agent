"""
模型管理器

管理多个LLM和Embedding模型配置，支持动态切换和自定义模型上传。
"""

import json
import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import BaseModel, Field

from graphrag_agent.config.settings import OPENAI_EMBEDDING_CONFIG, OPENAI_LLM_CONFIG, TIKTOKEN_CACHE_DIR
from graphrag_agent.utils.logging_config import get_logger

logger = get_logger(__name__)


class ModelConfig(BaseModel):
    """模型配置"""

    id: str
    name: str
    model_type: str  # llm | embedding
    provider: str  # openai | local | custom
    config: Dict[str, Any]  # 模型参数 (model, api_key, base_url, etc.)
    is_active: bool = False
    is_default: bool = False
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ModelManager:
    """
    模型管理器单例

    管理LLM和Embedding模型的注册、切换、加载。
    """

    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.config_file = Path("./data/model_registry.json")
        self.config_file.parent.mkdir(parents=True, exist_ok=True)

        # 模型注册表
        self.models: Dict[str, ModelConfig] = {}

        # 当前活跃模型实例
        self._active_llm: Optional[ChatOpenAI] = None
        self._active_embedding: Optional[OpenAIEmbeddings] = None

        # 加载配置
        self._load_registry()

        # 如果没有模型，注册默认模型
        if not self.models:
            self._register_default_models()

        self._initialized = True

    def _load_registry(self):
        """从文件加载模型注册表"""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for model_data in data:
                        model_config = ModelConfig(**model_data)
                        self.models[model_config.id] = model_config
            except Exception as e:
                logger.error(f"加载模型注册表失败: {e}", exc_info=True)

    def _save_registry(self):
        """保存模型注册表到文件"""
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                data = [model.model_dump() for model in self.models.values()]
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存模型注册表失败: {e}", exc_info=True)

    def _register_default_models(self):
        """注册默认模型（从环境变量）"""
        # 默认 LLM
        default_llm = ModelConfig(
            id="default_llm",
            name="Default LLM (from .env)",
            model_type="llm",
            provider="openai",
            config=OPENAI_LLM_CONFIG,
            is_active=True,
            is_default=True,
            description="从环境变量加载的默认LLM模型",
            tags=["default", "openai"],
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        self.models[default_llm.id] = default_llm

        # 默认 Embedding
        default_embedding = ModelConfig(
            id="default_embedding",
            name="Default Embedding (from .env)",
            model_type="embedding",
            provider="openai",
            config=OPENAI_EMBEDDING_CONFIG,
            is_active=True,
            is_default=True,
            description="从环境变量加载的默认Embedding模型",
            tags=["default", "openai"],
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        self.models[default_embedding.id] = default_embedding

        self._save_registry()

    def register_model(
        self,
        name: str,
        model_type: str,
        provider: str,
        config: Dict[str, Any],
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        set_active: bool = False,
    ) -> str:
        """
        注册新模型

        Args:
            name: 模型名称
            model_type: 模型类型 (llm | embedding)
            provider: 提供商 (openai | local | custom)
            config: 模型配置 (model, api_key, base_url等)
            description: 描述
            tags: 标签
            set_active: 是否立即设为活跃

        Returns:
            模型ID
        """
        import uuid

        model_id = str(uuid.uuid4())

        model_config = ModelConfig(
            id=model_id,
            name=name,
            model_type=model_type,
            provider=provider,
            config=config,
            is_active=False,
            is_default=False,
            description=description,
            tags=tags or [],
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )

        self.models[model_id] = model_config
        self._save_registry()

        if set_active:
            self.activate_model(model_id)

        return model_id

    def list_models(
        self, model_type: Optional[str] = None, provider: Optional[str] = None, active_only: bool = False
    ) -> List[ModelConfig]:
        """
        列出模型

        Args:
            model_type: 过滤模型类型
            provider: 过滤提供商
            active_only: 仅返回活跃模型

        Returns:
            模型配置列表
        """
        models = list(self.models.values())

        if model_type:
            models = [m for m in models if m.model_type == model_type]

        if provider:
            models = [m for m in models if m.provider == provider]

        if active_only:
            models = [m for m in models if m.is_active]

        return models

    def get_model(self, model_id: str) -> Optional[ModelConfig]:
        """获取模型配置"""
        return self.models.get(model_id)

    def activate_model(self, model_id: str) -> bool:
        """
        激活模型（设为当前活跃）

        Args:
            model_id: 模型ID

        Returns:
            是否成功
        """
        model = self.models.get(model_id)
        if not model:
            return False

        # 停用同类型的其他模型
        for m in self.models.values():
            if m.model_type == model.model_type and m.id != model_id:
                m.is_active = False

        # 激活当前模型
        model.is_active = True
        model.updated_at = datetime.now().isoformat()

        # 清空缓存实例，强制重新加载
        if model.model_type == "llm":
            self._active_llm = None
        elif model.model_type == "embedding":
            self._active_embedding = None

        self._save_registry()
        return True

    def delete_model(self, model_id: str) -> bool:
        """
        删除模型

        Args:
            model_id: 模型ID

        Returns:
            是否成功
        """
        model = self.models.get(model_id)
        if not model:
            return False

        # 不允许删除默认模型
        if model.is_default:
            raise ValueError("不能删除默认模型")

        # 如果是活跃模型，先激活默认模型
        if model.is_active:
            default_models = [m for m in self.models.values() if m.model_type == model.model_type and m.is_default]
            if default_models:
                self.activate_model(default_models[0].id)

        del self.models[model_id]
        self._save_registry()
        return True

    def get_active_llm(self) -> ChatOpenAI:
        """
        获取当前活跃的LLM实例

        Returns:
            ChatOpenAI 实例
        """
        if self._active_llm is not None:
            return self._active_llm

        # 查找活跃的LLM模型
        active_llms = [m for m in self.models.values() if m.model_type == "llm" and m.is_active]

        if not active_llms:
            # 如果没有活跃模型，激活默认模型
            default_llms = [m for m in self.models.values() if m.model_type == "llm" and m.is_default]
            if default_llms:
                self.activate_model(default_llms[0].id)
                active_llms = [default_llms[0]]
            else:
                raise ValueError("没有可用的LLM模型")

        # 创建实例
        config = active_llms[0].config
        config_filtered = {k: v for k, v in config.items() if v is not None and v != ""}
        self._active_llm = ChatOpenAI(**config_filtered)

        return self._active_llm

    def get_active_embedding(self) -> OpenAIEmbeddings:
        """
        获取当前活跃的Embedding实例

        Returns:
            OpenAIEmbeddings 实例
        """
        if self._active_embedding is not None:
            return self._active_embedding

        # 查找活跃的Embedding模型
        active_embeddings = [m for m in self.models.values() if m.model_type == "embedding" and m.is_active]

        if not active_embeddings:
            # 如果没有活跃模型，激活默认模型
            default_embeddings = [m for m in self.models.values() if m.model_type == "embedding" and m.is_default]
            if default_embeddings:
                self.activate_model(default_embeddings[0].id)
                active_embeddings = [default_embeddings[0]]
            else:
                raise ValueError("没有可用的Embedding模型")

        # 创建实例
        config = active_embeddings[0].config
        config_filtered = {k: v for k, v in config.items() if v}
        self._active_embedding = OpenAIEmbeddings(**config_filtered)

        return self._active_embedding

    def reload_models(self):
        """重新加载模型（清空缓存）"""
        self._active_llm = None
        self._active_embedding = None


# 全局单例实例
def get_model_manager() -> ModelManager:
    """
    获取全局模型管理器实例

    Returns:
        ModelManager 单例
    """
    return ModelManager()
