"""
动态提示词构建器

支持 YAML 配置、参数插值、模板版本管理
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PromptTemplate(BaseModel):
    """提示词模板数据模型"""

    name: str = Field(..., description="模板名称")
    version: str = Field(default="1.0.0", description="模板版本")
    description: str = Field(default="", description="模板描述")
    system_prompt: str = Field(..., description="系统提示词")
    user_prompt_template: str = Field(..., description="用户提示词模板（支持 {变量} 插值）")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="默认参数")
    examples: List[Dict[str, str]] = Field(default_factory=list, description="Few-shot 示例")
    constraints: List[str] = Field(default_factory=list, description="约束条件")
    output_format: Optional[str] = Field(default=None, description="输出格式说明")

    def get_content_hash(self) -> str:
        """生成模板内容的 MD5 哈希（用于缓存版本控制）"""
        content = f"{self.system_prompt}|{self.user_prompt_template}|{self.version}"
        return hashlib.md5(content.encode()).hexdigest()[:8]


class PromptBuilder:
    """
    动态提示词构建器

    功能：
    - 从 YAML 文件加载模板
    - 参数插值和动态构建
    - 模板版本管理（用于缓存失效）
    - Few-shot 示例注入

    使用示例：
        >>> builder = PromptBuilder()
        >>> builder.load_template("entity_extraction")
        >>> prompt = builder.build(
        ...     text="学生需要在每学期开始前注册课程",
        ...     entity_types=["学生", "课程"],
        ...     domain="教育"
        ... )
    """

    def __init__(self, templates_dir: Optional[str] = None):
        """
        初始化 PromptBuilder

        Args:
            templates_dir: 模板目录路径（默认为 config/prompts/）
        """
        if templates_dir is None:
            # 默认模板目录：项目根目录下的 config/prompts/
            project_root = Path(__file__).parent.parent.parent
            templates_dir = project_root / "config" / "prompts"

        self.templates_dir = Path(templates_dir)
        self.templates: Dict[str, PromptTemplate] = {}
        self._load_all_templates()

    def _load_all_templates(self):
        """加载模板目录下的所有 YAML 文件"""
        if not self.templates_dir.exists():
            logger.warning(f"Templates directory not found: {self.templates_dir}")
            return

        for yaml_file in self.templates_dir.glob("*.yaml"):
            try:
                self._load_template_file(yaml_file)
            except Exception as e:
                logger.error(f"Failed to load template {yaml_file}: {e}")

    def _load_template_file(self, yaml_path: Path):
        """从 YAML 文件加载模板"""
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        template = PromptTemplate(**data)
        self.templates[template.name] = template
        logger.info(f"Loaded template: {template.name} (v{template.version})")

    def load_template(self, template_name: str) -> PromptTemplate:
        """
        加载指定模板

        Args:
            template_name: 模板名称

        Returns:
            PromptTemplate 实例

        Raises:
            KeyError: 模板不存在
        """
        if template_name not in self.templates:
            raise KeyError(f"Template '{template_name}' not found in {self.templates_dir}")
        return self.templates[template_name]

    def build(self, template_name: str, **kwargs) -> str:
        """
        构建完整提示词

        Args:
            template_name: 模板名称
            **kwargs: 用于插值的参数

        Returns:
            完整的提示词字符串

        Example:
            >>> builder.build("entity_extraction", text="...", entity_types=["Person", "Org"])
        """
        template = self.load_template(template_name)

        # 合并默认参数和传入参数
        params = {**template.parameters, **kwargs}

        # 构建系统提示词
        system_prompt = template.system_prompt

        # 添加约束条件
        if template.constraints:
            constraints_text = "\n".join(f"- {c}" for c in template.constraints)
            system_prompt += f"\n\n约束条件：\n{constraints_text}"

        # 添加输出格式说明
        if template.output_format:
            system_prompt += f"\n\n输出格式：\n{template.output_format}"

        # 构建用户提示词（参数插值）
        user_prompt = template.user_prompt_template.format(**params)

        # 添加 Few-shot 示例
        if template.examples:
            examples_text = self._format_examples(template.examples)
            user_prompt = f"{examples_text}\n\n{user_prompt}"

        # 组合系统提示词和用户提示词
        full_prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"

        return full_prompt

    def build_messages(self, template_name: str, **kwargs) -> List[Dict[str, str]]:
        """
        构建 OpenAI 格式的消息列表

        Args:
            template_name: 模板名称
            **kwargs: 用于插值的参数

        Returns:
            消息列表 [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]

        Example:
            >>> messages = builder.build_messages("entity_extraction", text="...")
            >>> response = openai.ChatCompletion.create(model="gpt-4", messages=messages)
        """
        template = self.load_template(template_name)

        # 合并参数
        params = {**template.parameters, **kwargs}

        # 构建系统消息
        system_content = template.system_prompt

        # 添加约束条件
        if template.constraints:
            constraints_text = "\n".join(f"- {c}" for c in template.constraints)
            system_content += f"\n\n约束条件：\n{constraints_text}"

        # 添加输出格式说明
        if template.output_format:
            system_content += f"\n\n输出格式：\n{template.output_format}"

        messages = [{"role": "system", "content": system_content}]

        # 添加 Few-shot 示例（作为 assistant/user 对话历史）
        if template.examples:
            for example in template.examples:
                messages.append({"role": "user", "content": example.get("input", "")})
                messages.append({"role": "assistant", "content": example.get("output", "")})

        # 添加用户消息（参数插值）
        user_content = template.user_prompt_template.format(**params)
        messages.append({"role": "user", "content": user_content})

        return messages

    def get_template_version(self, template_name: str) -> str:
        """
        获取模板版本哈希（用于缓存键）

        Args:
            template_name: 模板名称

        Returns:
            8 位 MD5 哈希字符串

        Example:
            >>> cache_key = f"query:{query_hash}:template:{builder.get_template_version('entity_extraction')}"
        """
        template = self.load_template(template_name)
        return template.get_content_hash()

    def _format_examples(self, examples: List[Dict[str, str]]) -> str:
        """格式化 Few-shot 示例"""
        formatted = ["示例："]
        for i, example in enumerate(examples, 1):
            formatted.append(f"\n示例 {i}:")
            formatted.append(f"输入: {example.get('input', '')}")
            formatted.append(f"输出: {example.get('output', '')}")
        return "\n".join(formatted)

    def list_templates(self) -> List[str]:
        """列出所有可用模板名称"""
        return list(self.templates.keys())

    def reload_templates(self):
        """重新加载所有模板（热更新）"""
        self.templates.clear()
        self._load_all_templates()
        logger.info(f"Reloaded {len(self.templates)} templates")
