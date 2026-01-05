"""
用户配置仓库 (User Config Repository)
管理多个用户自定义的知识图谱配置

特性：
1. 支持多配置存储（无数量限制）
2. 默认配置机制
3. 文件存储（轻量级）
4. 配置元数据管理（名称、描述、创建时间等）
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from .graph_config_model import GraphConfig


class ConfigMetadata(BaseModel):
    """配置元数据"""

    id: str = Field(..., description="配置唯一标识 (UUID)")
    name: str = Field(..., description="配置名称")
    description: Optional[str] = Field(default=None, description="配置描述")
    file_path: str = Field(..., description="配置文件路径（相对于仓库目录）")
    is_default: bool = Field(default=False, description="是否为默认配置")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="最后更新时间")


class ConfigRegistry(BaseModel):
    """配置清单"""

    configs: List[ConfigMetadata] = Field(default_factory=list, description="配置列表")


class UserConfigRepository:
    """用户配置仓库管理器"""

    def __init__(self, repo_path: Optional[str] = None):
        """
        初始化配置仓库

        Args:
            repo_path: 仓库根目录，默认为 ./data/user_configs/
        """
        if repo_path is None:
            repo_path = os.path.join(os.getcwd(), "data", "user_configs")

        self.repo_path = Path(repo_path)
        self.registry_file = self.repo_path / "config_registry.json"
        self._ensure_repo_dir()
        self._migrate_existing_config()

    def _ensure_repo_dir(self):
        """确保仓库目录存在"""
        self.repo_path.mkdir(parents=True, exist_ok=True)

    def _migrate_existing_config(self):
        """迁移现有的 graph_config.json 到仓库（仅首次运行）"""
        # 如果注册表已存在，跳过迁移
        if self.registry_file.exists():
            return

        # 检查项目根目录是否有 graph_config.json
        old_config_path = Path(os.getcwd()) / "graph_config.json"
        if old_config_path.exists():
            try:
                # 加载旧配置
                with open(old_config_path, "r", encoding="utf-8") as f:
                    config_dict = json.load(f)

                config = GraphConfig(**config_dict)

                # 创建第一个配置条目（设为默认）
                config_id = str(uuid.uuid4())
                metadata = ConfigMetadata(
                    id=config_id,
                    name=config.project_name or "默认配置",
                    description=config.description,
                    file_path=f"config_{config_id}.json",
                    is_default=True,
                    created_at=config.created_at if hasattr(config, "created_at") else datetime.now(),
                    updated_at=config.updated_at if hasattr(config, "updated_at") else datetime.now(),
                )

                # 保存配置文件
                config_file_path = self.repo_path / metadata.file_path
                with open(config_file_path, "w", encoding="utf-8") as f:
                    json.dump(config.model_dump(mode="json"), f, ensure_ascii=False, indent=2)

                # 创建注册表
                registry = ConfigRegistry(configs=[metadata])
                self._save_registry(registry)

                print(f"✅ 迁移成功：已将 graph_config.json 迁移到仓库（ID: {config_id}）")

            except Exception as e:
                print(f"⚠️ 迁移失败: {e}")
                # 创建空注册表
                self._save_registry(ConfigRegistry())
        else:
            # 创建空注册表
            self._save_registry(ConfigRegistry())

    def _load_registry(self) -> ConfigRegistry:
        """加载配置清单"""
        if not self.registry_file.exists():
            return ConfigRegistry()

        try:
            with open(self.registry_file, "r", encoding="utf-8") as f:
                registry_dict = json.load(f)
            return ConfigRegistry(**registry_dict)
        except Exception as e:
            print(f"加载配置清单失败: {e}")
            return ConfigRegistry()

    def _save_registry(self, registry: ConfigRegistry) -> bool:
        """保存配置清单"""
        try:
            with open(self.registry_file, "w", encoding="utf-8") as f:
                json.dump(registry.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存配置清单失败: {e}")
            return False

    def list_configs(self) -> List[ConfigMetadata]:
        """
        列出所有配置

        Returns:
            配置元数据列表（按更新时间倒序）
        """
        registry = self._load_registry()
        # 按更新时间倒序排列
        return sorted(registry.configs, key=lambda c: c.updated_at, reverse=True)

    def get_config(self, config_id: str) -> Optional[GraphConfig]:
        """
        获取指定配置

        Args:
            config_id: 配置ID

        Returns:
            GraphConfig 实例，如果不存在则返回 None
        """
        registry = self._load_registry()

        # 查找配置元数据
        metadata = next((c for c in registry.configs if c.id == config_id), None)
        if not metadata:
            return None

        # 加载配置文件
        config_file = self.repo_path / metadata.file_path
        if not config_file.exists():
            print(f"配置文件不存在: {config_file}")
            return None

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config_dict = json.load(f)
            return GraphConfig(**config_dict)
        except Exception as e:
            print(f"加载配置失败: {e}")
            return None

    def get_metadata(self, config_id: str) -> Optional[ConfigMetadata]:
        """
        获取配置元数据

        Args:
            config_id: 配置ID

        Returns:
            ConfigMetadata 实例，如果不存在则返回 None
        """
        registry = self._load_registry()
        return next((c for c in registry.configs if c.id == config_id), None)

    def get_default_config(self) -> Optional[GraphConfig]:
        """
        获取默认配置

        Returns:
            默认配置的 GraphConfig 实例，如果不存在则返回 None
        """
        registry = self._load_registry()
        default_metadata = next((c for c in registry.configs if c.is_default), None)

        if not default_metadata:
            # 如果没有默认配置，返回第一个配置
            if registry.configs:
                default_metadata = registry.configs[0]
            else:
                return None

        return self.get_config(default_metadata.id)

    def get_default_metadata(self) -> Optional[ConfigMetadata]:
        """
        获取默认配置的元数据

        Returns:
            默认配置的 ConfigMetadata，如果不存在则返回 None
        """
        registry = self._load_registry()
        default_metadata = next((c for c in registry.configs if c.is_default), None)

        if not default_metadata and registry.configs:
            # 如果没有默认配置，返回第一个配置
            default_metadata = registry.configs[0]

        return default_metadata

    def create_config(
        self, config: GraphConfig, name: str, description: Optional[str] = None, set_as_default: bool = False
    ) -> str:
        """
        创建新配置

        Args:
            config: GraphConfig 实例
            name: 配置名称
            description: 配置描述
            set_as_default: 是否设为默认配置

        Returns:
            配置ID
        """
        registry = self._load_registry()

        # 生成配置ID
        config_id = str(uuid.uuid4())

        # 如果设为默认，取消其他配置的默认状态
        if set_as_default:
            for c in registry.configs:
                c.is_default = False

        # 创建元数据
        metadata = ConfigMetadata(
            id=config_id,
            name=name,
            description=description,
            file_path=f"config_{config_id}.json",
            is_default=set_as_default,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        # 保存配置文件
        config_file = self.repo_path / metadata.file_path
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置文件失败: {e}")
            raise

        # 添加到注册表
        registry.configs.append(metadata)
        self._save_registry(registry)

        print(f"✅ 配置已创建: {name} (ID: {config_id}, 默认: {set_as_default})")
        return config_id

    def update_config(
        self, config_id: str, config: GraphConfig, name: Optional[str] = None, description: Optional[str] = None
    ) -> bool:
        """
        更新配置

        Args:
            config_id: 配置ID
            config: 新的 GraphConfig 实例
            name: 新名称（可选）
            description: 新描述（可选）

        Returns:
            是否更新成功
        """
        registry = self._load_registry()

        # 查找配置元数据
        metadata = next((c for c in registry.configs if c.id == config_id), None)
        if not metadata:
            print(f"配置不存在: {config_id}")
            return False

        # 更新元数据
        if name is not None:
            metadata.name = name
        if description is not None:
            metadata.description = description
        metadata.updated_at = datetime.now()

        # 保存配置文件
        config_file = self.repo_path / metadata.file_path
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置文件失败: {e}")
            return False

        # 更新注册表
        self._save_registry(registry)

        print(f"✅ 配置已更新: {metadata.name} (ID: {config_id})")
        return True

    def delete_config(self, config_id: str) -> bool:
        """
        删除配置

        Args:
            config_id: 配置ID

        Returns:
            是否删除成功
        """
        registry = self._load_registry()

        # 查找配置元数据
        metadata = next((c for c in registry.configs if c.id == config_id), None)
        if not metadata:
            print(f"配置不存在: {config_id}")
            return False

        # 如果是默认配置，不允许删除（除非只剩一个配置）
        if metadata.is_default and len(registry.configs) > 1:
            print(f"无法删除默认配置，请先设置其他配置为默认")
            return False

        # 删除配置文件
        config_file = self.repo_path / metadata.file_path
        try:
            if config_file.exists():
                config_file.unlink()
        except Exception as e:
            print(f"删除配置文件失败: {e}")
            return False

        # 从注册表移除
        registry.configs = [c for c in registry.configs if c.id != config_id]
        self._save_registry(registry)

        print(f"✅ 配置已删除: {metadata.name} (ID: {config_id})")
        return True

    def set_default(self, config_id: str) -> bool:
        """
        设置默认配置

        Args:
            config_id: 配置ID

        Returns:
            是否设置成功
        """
        registry = self._load_registry()

        # 查找配置元数据
        metadata = next((c for c in registry.configs if c.id == config_id), None)
        if not metadata:
            print(f"配置不存在: {config_id}")
            return False

        # 取消其他配置的默认状态
        for c in registry.configs:
            c.is_default = False

        # 设置当前配置为默认
        metadata.is_default = True

        # 保存注册表
        self._save_registry(registry)

        print(f"✅ 已设为默认配置: {metadata.name} (ID: {config_id})")
        return True

    def duplicate_config(self, config_id: str, new_name: str) -> Optional[str]:
        """
        复制配置

        Args:
            config_id: 源配置ID
            new_name: 新配置名称

        Returns:
            新配置的ID，如果复制失败则返回 None
        """
        # 加载源配置
        source_config = self.get_config(config_id)
        if not source_config:
            print(f"源配置不存在: {config_id}")
            return None

        source_metadata = self.get_metadata(config_id)

        # 创建新配置（不设为默认）
        new_config_id = self.create_config(
            config=source_config, name=new_name, description=source_metadata.description, set_as_default=False
        )

        print(f"✅ 配置已复制: {new_name} (ID: {new_config_id})")
        return new_config_id


# 全局单例
_repository_instance = None


def get_user_config_repository() -> UserConfigRepository:
    """获取全局配置仓库实例"""
    global _repository_instance
    if _repository_instance is None:
        _repository_instance = UserConfigRepository()
    return _repository_instance
