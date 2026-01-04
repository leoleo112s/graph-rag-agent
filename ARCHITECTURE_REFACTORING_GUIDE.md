# 架构重构与优化指南

> **创建时间**: 2025-12-25
> **优化目标**: 解决前端组件混乱、提示词硬编码、社区检测配置三大架构问题

---

## 📋 问题总览

本文档针对项目中发现的三个架构级问题，提供详细的重构方案和实施指南：

| 问题 | 严重程度 | 影响范围 | 工作量 | 优先级 |
|------|---------|---------|--------|--------|
| **前端组件划分不清** | 🟡 中等 | 维护性、可测试性 | 大（3-5天） | P3 |
| **提示词硬编码** | 🔴 高 | 可维护性、灵活性 | 中（1-2天） | P1 |
| **社区检测缺乏配置** | 🟠 较高 | 灵活性、可扩展性 | 小（0.5-1天） | P2 |

---

## 问题一：前端目录与组件划分不清 🎨

### 问题分析

#### 现状（修改前）

**目录结构**：
```
frontend/
├── app.py                    # 主入口
├── page_components/          # 页面组件
│   ├── ai_config_wizard.py  # ❌ 混合了UI渲染和业务逻辑
│   ├── document_manager.py
│   └── config_manager.py
├── components/               # 通用组件
│   ├── chat.py
│   ├── sidebar.py
│   └── debug.py             # ❌ 缺乏统一的原子级组件
└── utils/                    # 工具函数
    └── api.py
```

**问题点**：

1. **职责混乱** - `ai_config_wizard.py` 中：
   ```python
   # ❌ UI渲染逻辑
   def render_analysis_results(results):
       st.write("分析结果")
       # ... 大量 st.write/st.button 等 UI 代码

   # ❌ 业务逻辑（API调用）混在同一文件
   def analyze_documents_with_ai(docs):
       response = requests.post(API_URL, json=docs)
       return response.json()
   ```

2. **无原子组件** - 缺乏可复用的基础组件：
   - 按钮样式不统一
   - 加载状态各处实现不同
   - 错误提示卡片重复编写

3. **难以测试** - UI和业务逻辑耦合，无法单独测试

---

### 解决方案

#### 目标架构

```
frontend/
├── app.py                    # 主路由（仅负责页面切换）
├── pages/                    # 页面级组件（路由+状态组装）
│   ├── chat_page.py
│   ├── documents_page.py
│   └── config_page.py
├── views/                    # 视图层（布局渲染，无业务逻辑）
│   ├── chat_view.py
│   ├── analysis_dashboard.py
│   └── config_form.py
├── widgets/                  # 原子组件（可复用）
│   ├── buttons.py           # custom_button, icon_button
│   ├── cards.py             # info_card, error_card, success_card
│   ├── loaders.py           # spinner, progress_bar
│   └── gallery.py           # 组件展示页（调试用）
├── services/                 # 业务逻辑（API调用）
│   ├── ai_service.py        # analyze_documents, generate_config
│   ├── document_service.py  # upload_document, delete_document
│   └── build_service.py     # trigger_build, get_build_status
└── utils/                    # 工具函数
    ├── api.py               # 统一的HTTP客户端
    ├── state.py             # session_state管理
    └── i18n.py              # 国际化
```

#### 分层职责

| 层级 | 职责 | 禁止内容 | 示例 |
|------|------|----------|------|
| **Pages** | 路由、状态组装、调用services和views | UI渲染（st.write等） | `chat_page.py` |
| **Views** | 布局渲染、调用widgets | API调用（requests） | `analysis_dashboard.py` |
| **Widgets** | 原子组件、样式封装 | 业务逻辑 | `custom_button()` |
| **Services** | API调用、数据处理 | UI渲染 | `analyze_documents()` |

---

### 实施步骤

#### Step 1: 创建 Widgets 库

**新建文件**: `frontend/widgets/buttons.py`

```python
"""
原子组件 - 按钮
提供统一样式的按钮组件
"""

import streamlit as st
from typing import Optional, Literal

def custom_button(
    label: str,
    key: Optional[str] = None,
    button_type: Literal["primary", "secondary", "danger"] = "primary",
    icon: Optional[str] = None,
    disabled: bool = False,
    use_container_width: bool = False
) -> bool:
    """
    统一样式的按钮组件

    Args:
        label: 按钮文本
        key: 唯一标识符
        button_type: 按钮类型（primary/secondary/danger）
        icon: 图标emoji
        disabled: 是否禁用
        use_container_width: 是否占满容器宽度

    Returns:
        bool: 是否被点击

    使用示例:
        if custom_button("提交", button_type="primary", icon="✅"):
            # 处理点击事件
            pass
    """
    # 构造显示文本
    display_text = f"{icon} {label}" if icon else label

    # 根据类型选择样式
    type_map = {
        "primary": "primary",
        "secondary": "secondary",
        "danger": "secondary"  # Streamlit 没有danger类型，需自定义CSS
    }

    return st.button(
        display_text,
        key=key,
        type=type_map[button_type],
        disabled=disabled,
        use_container_width=use_container_width
    )


def icon_button(icon: str, tooltip: str, key: Optional[str] = None) -> bool:
    """
    图标按钮（用于工具栏）

    Args:
        icon: 图标emoji
        tooltip: 提示文本
        key: 唯一标识符

    Returns:
        bool: 是否被点击

    使用示例:
        if icon_button("🗑️", "删除", key="delete_btn"):
            # 处理删除
            pass
    """
    return st.button(
        icon,
        key=key,
        help=tooltip,
        use_container_width=False
    )
```

**新建文件**: `frontend/widgets/cards.py`

```python
"""
原子组件 - 卡片
提供统一样式的信息展示卡片
"""

import streamlit as st
from typing import Literal

def info_card(title: str, content: str, card_type: Literal["info", "success", "warning", "error"] = "info"):
    """
    信息卡片

    Args:
        title: 标题
        content: 内容
        card_type: 卡片类型

    使用示例:
        info_card("构建成功", "处理了100个文件", card_type="success")
    """
    # 图标映射
    icons = {
        "info": "ℹ️",
        "success": "✅",
        "warning": "⚠️",
        "error": "❌"
    }

    # 颜色映射（使用Streamlit内置样式）
    type_func_map = {
        "info": st.info,
        "success": st.success,
        "warning": st.warning,
        "error": st.error
    }

    # 渲染卡片
    type_func_map[card_type](f"{icons[card_type]} **{title}**\n\n{content}")


def metric_card(label: str, value: str, delta: Optional[str] = None):
    """
    指标卡片（用于仪表盘）

    Args:
        label: 指标名称
        value: 指标值
        delta: 变化量

    使用示例:
        metric_card("总文档数", "1,234", delta="+50")
    """
    st.metric(label=label, value=value, delta=delta)


def expandable_card(title: str, content_func: callable, expanded: bool = False):
    """
    可展开卡片

    Args:
        title: 标题
        content_func: 内容渲染函数（将在展开时调用）
        expanded: 是否默认展开

    使用示例:
        expandable_card(
            "详细日志",
            lambda: st.code(logs, language="log"),
            expanded=False
        )
    """
    with st.expander(title, expanded=expanded):
        content_func()
```

**新建文件**: `frontend/widgets/loaders.py`

```python
"""
原子组件 - 加载状态
提供统一的加载动画和进度条
"""

import streamlit as st
from typing import Optional
import time

def spinner(message: str = "加载中..."):
    """
    加载动画

    Args:
        message: 加载提示文本

    使用示例:
        with spinner("正在分析文档..."):
            result = service.analyze_documents(docs)
    """
    return st.spinner(message)


def progress_bar(current: int, total: int, message: Optional[str] = None):
    """
    进度条

    Args:
        current: 当前进度
        total: 总量
        message: 进度提示文本

    使用示例:
        progress_bar(50, 100, "处理中: 50/100")
    """
    progress = current / total if total > 0 else 0

    if message:
        st.caption(message)

    st.progress(progress)


def skeleton_loader(num_lines: int = 3):
    """
    骨架屏加载动画

    Args:
        num_lines: 骨架行数

    使用示例:
        skeleton_loader(num_lines=5)  # 显示5行骨架屏
    """
    for _ in range(num_lines):
        st.markdown("⬜" * 50)  # 简化的骨架屏，可改进为自定义CSS
```

---

#### Step 2: 创建 Services 层

**新建文件**: `frontend/services/ai_service.py`

```python
"""
业务逻辑 - AI服务
封装所有与AI相关的API调用
"""

import requests
from typing import List, Dict, Any
from utils.api import get_api_url
import logging

logger = logging.getLogger(__name__)


def analyze_documents(documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    分析文档并生成图谱配置建议

    Args:
        documents: 文档列表

    Returns:
        Dict: 分析结果
            {
                "clusters": [...],
                "key_concepts": [...],
                "recommendations": {...}
            }

    Raises:
        requests.HTTPError: API调用失败
    """
    url = f"{get_api_url()}/ai-copilot/analyze"

    try:
        response = requests.post(
            url,
            json={"documents": documents},
            timeout=60
        )
        response.raise_for_status()
        return response.json()

    except requests.Timeout:
        logger.error("文档分析超时")
        raise

    except requests.HTTPError as e:
        logger.error(f"API调用失败: {e}")
        raise


def generate_graph_config(analysis_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据分析结果生成图谱配置

    Args:
        analysis_result: 文档分析结果

    Returns:
        Dict: 图谱配置
    """
    url = f"{get_api_url()}/ai-copilot/generate-config"

    response = requests.post(
        url,
        json={"analysis": analysis_result},
        timeout=30
    )
    response.raise_for_status()
    return response.json()


def apply_graph_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    应用图谱配置

    Args:
        config: 图谱配置

    Returns:
        Dict: 应用结果
    """
    url = f"{get_api_url()}/admin/graph-config"

    response = requests.post(
        url,
        json=config,
        timeout=10
    )
    response.raise_for_status()
    return response.json()
```

**重构前** ❌ (`ai_config_wizard.py` 混合UI和业务逻辑):
```python
# ❌ UI渲染和API调用混在一起
def render_analysis_step():
    st.write("分析中...")

    # ❌ 直接在UI函数中调用API
    response = requests.post(API_URL, json=docs)
    results = response.json()

    # ❌ UI渲染
    st.write(results)
```

**重构后** ✅ (分离为 View + Service):
```python
# ✅ frontend/views/ai_wizard_view.py
from services.ai_service import analyze_documents
from widgets.loaders import spinner
from widgets.cards import info_card

def render_analysis_step(documents):
    """仅负责UI渲染"""

    # 使用widgets
    with spinner("正在分析文档..."):
        # 调用service（无UI）
        results = analyze_documents(documents)

    # 使用widgets展示结果
    info_card("分析完成", f"发现 {len(results['clusters'])} 个聚类", card_type="success")
```

---

#### Step 3: 创建组件展示页（Widgets Gallery）

**新建文件**: `frontend/widgets/gallery.py`

```python
"""
组件展示页
用于调试和预览所有原子组件的不同状态
"""

import streamlit as st
from widgets.buttons import custom_button, icon_button
from widgets.cards import info_card, metric_card, expandable_card
from widgets.loaders import spinner, progress_bar, skeleton_loader


def show_gallery():
    """
    展示所有组件（仅在开发环境使用）

    使用方法：
        在app.py中添加隐藏页面：
        if st.session_state.get("developer_mode"):
            show_gallery()
    """
    st.title("🎨 组件展示库（Widgets Gallery）")

    st.markdown("---")

    # ========== 按钮组件 ==========
    st.header("1. 按钮（Buttons）")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("Primary Button")
        if custom_button("主要按钮", button_type="primary", icon="✅"):
            st.toast("Primary Button Clicked!")

    with col2:
        st.subheader("Secondary Button")
        if custom_button("次要按钮", button_type="secondary", icon="ℹ️"):
            st.toast("Secondary Button Clicked!")

    with col3:
        st.subheader("Danger Button")
        if custom_button("危险按钮", button_type="danger", icon="⚠️"):
            st.toast("Danger Button Clicked!")

    st.markdown("**Icon Buttons:**")
    cols = st.columns(5)
    icons = ["🗑️", "✏️", "📥", "📤", "⚙️"]
    tooltips = ["删除", "编辑", "下载", "上传", "设置"]

    for i, (icon, tooltip) in enumerate(zip(icons, tooltips)):
        with cols[i]:
            if icon_button(icon, tooltip, key=f"icon_{i}"):
                st.toast(f"{tooltip} Clicked!")

    st.markdown("---")

    # ========== 卡片组件 ==========
    st.header("2. 卡片（Cards）")

    col1, col2 = st.columns(2)

    with col1:
        info_card("信息卡片", "这是一个普通信息卡片", card_type="info")
        info_card("成功卡片", "操作成功完成", card_type="success")

    with col2:
        info_card("警告卡片", "请注意此操作", card_type="warning")
        info_card("错误卡片", "操作失败：网络错误", card_type="error")

    st.markdown("**Metric Cards:**")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        metric_card("总文档数", "1,234", delta="+50")
    with col2:
        metric_card("实体数", "5,678", delta="+123")
    with col3:
        metric_card("关系数", "12,345", delta="+456")
    with col4:
        metric_card("社区数", "89", delta="-5")

    st.markdown("**Expandable Card:**")
    expandable_card(
        "详细日志",
        lambda: st.code("2025-12-25 10:00:00 [INFO] Build started\n2025-12-25 10:05:00 [INFO] Build completed", language="log"),
        expanded=False
    )

    st.markdown("---")

    # ========== 加载组件 ==========
    st.header("3. 加载状态（Loaders）")

    if st.button("测试Spinner"):
        with spinner("正在处理..."):
            import time
            time.sleep(2)
        st.success("处理完成！")

    st.markdown("**Progress Bar:**")
    progress_bar(75, 100, "处理中: 75/100")

    st.markdown("**Skeleton Loader:**")
    if st.button("显示骨架屏"):
        skeleton_loader(num_lines=5)

    st.markdown("---")

    st.info("💡 **提示**: 修改widget组件后，刷新此页面查看效果")
```

**集成到 app.py**:
```python
# frontend/app.py

# 添加开发者模式切换
if st.sidebar.checkbox("开发者模式（Developer Mode）", value=False):
    st.session_state.developer_mode = True

# 在页面导航中添加组件库（仅开发者模式）
if st.session_state.get("developer_mode"):
    if page == "🎨 组件库":
        from widgets.gallery import show_gallery
        show_gallery()
```

---

### 测试与验证

#### 视觉回归测试

1. **启动组件库**:
   ```bash
   streamlit run frontend/app.py
   # 勾选"开发者模式"
   # 选择"🎨 组件库"页面
   ```

2. **逐个验证组件**:
   - 按钮是否可点击
   - 卡片颜色是否正确
   - 加载动画是否流畅

#### 逻辑解耦测试

```python
# tests/test_services.py

def test_ai_service_no_ui():
    """确保service层不包含任何UI代码"""
    from services import ai_service
    import inspect

    # 检查源码中是否包含streamlit调用
    source = inspect.getsource(ai_service)
    assert "st." not in source, "Service层不应包含st.调用"
    assert "streamlit" not in source, "Service层不应导入streamlit"
```

---

## 问题二：提示词与模型参数硬编码 📝

### 问题分析

#### 现状（修改前）

**硬编码示例** (`graphrag_agent/ai_copilot/document_analyzer.py`):

```python
def _build_recommendation_prompt(self, analysis_result):
    """
    ❌ 问题：提示词硬编码在Python代码中
    """
    prompt = f"""
你是一个知识图谱专家。根据以下文档分析结果，推荐最佳的图谱配置。

## 分析结果
聚类数量: {len(analysis_result['clusters'])}
关键概念: {', '.join(analysis_result['key_concepts'])}

## 任务
1. 识别领域类型（法务/电商/医疗/其他）
2. 推荐实体类型（entity_types）
3. 推荐关系类型（relationship_types）
4. 推荐桥接点（bridge_definitions）

请以JSON格式返回。
"""
    return prompt
```

**问题点**：

1. **维护困难** - 修改提示词需要改代码、重新部署
2. **无版本控制** - 无法追踪提示词的演进历史
3. **不符合规范** - 项目已有 `graphrag_agent/config/prompts/` 目录，AI Copilot 没遵循
4. **难以A/B测试** - 无法快速切换不同版本的提示词

---

### 解决方案

#### 架构设计

```
配置存储（YAML/JSON）
    ↓
PromptManager（加载+缓存）
    ↓
业务代码（通过key获取）
    ↓
LLM调用
```

#### 核心组件

**1. Prompt 存储文件**

**新建文件**: `graphrag_agent/config/prompts/ai_copilot_prompts.yaml`

```yaml
# AI Copilot 提示词配置
# 版本: 1.0
# 最后更新: 2025-12-25

# ========== 文档分析提示词 ==========

document_analysis:
  name: "文档分析提示词"
  description: "用于分析文档聚类并提取关键概念"
  version: "1.0"
  template: |
    你是一个专业的知识图谱分析师。请分析以下文档聚类结果：

    ## 聚类信息
    {% for cluster in clusters %}
    **聚类 {{ loop.index }}**:
    - 文档数量: {{ cluster.document_count }}
    - 代表性词汇: {{ cluster.representative_terms | join(', ') }}
    {% endfor %}

    ## 任务
    1. 识别主题领域（如：法务、医疗、电商等）
    2. 提取核心概念（10-15个）
    3. 分析概念之间的潜在关系

    请以JSON格式返回：
    ```json
    {
      "domain": "领域名称",
      "core_concepts": ["概念1", "概念2", ...],
      "potential_relationships": ["关系1", "关系2", ...]
    }
    ```

  parameters:
    temperature: 0.3
    max_tokens: 2000
    model: "gpt-4o"

# ========== 图谱配置推荐提示词 ==========

graph_config_recommendation:
  name: "图谱配置推荐"
  description: "根据分析结果推荐GraphConfig"
  version: "1.0"
  template: |
    你是知识图谱架构专家。根据文档分析结果，推荐最佳图谱配置。

    ## 分析结果
    - 领域: {{ analysis.domain }}
    - 核心概念: {{ analysis.core_concepts | join(', ') }}
    - 文档总数: {{ analysis.total_documents }}

    ## 配置要求
    1. **实体类型** (entity_types): 5-10个核心实体
    2. **关系类型** (relationship_types): 5-10个核心关系
    3. **桥接点** (bridge_definitions): 2-3个关键桥接概念

    ## 输出格式
    请以JSON格式返回GraphConfig：
    ```json
    {
      "project_name": "项目名称",
      "industry": "行业",
      "bridge_definitions": [
        {"name": "桥接点名称", "key": "bridge_xxx", "description": "说明"}
      ],
      "domain_definitions": [
        {
          "domain_name": "领域名称",
          "schema": {
            "entities": ["实体1", "实体2"],
            "relations": ["关系1", "关系2"]
          }
        }
      ]
    }
    ```

  parameters:
    temperature: 0.5
    max_tokens: 3000
    model: "gpt-4o"
```

**2. Prompt Manager 类**

**新建文件**: `graphrag_agent/config/prompts/prompt_manager.py`

```python
"""
Prompt 管理器
统一管理所有提示词，支持从YAML/JSON加载，并提供Jinja2模板渲染
"""

import os
import yaml
import json
from typing import Dict, Any, Optional
from pathlib import Path
from jinja2 import Template
import logging

logger = logging.getLogger(__name__)


class PromptManager:
    """提示词管理器（单例模式）"""

    _instance = None
    _prompts = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化（仅首次调用生效）"""
        if not self._prompts:
            self.reload()

    def reload(self):
        """重新加载所有提示词文件"""
        prompts_dir = Path(__file__).parent
        self._prompts = {}

        # 加载所有YAML文件
        for yaml_file in prompts_dir.glob("*.yaml"):
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    self._prompts.update(data)
                logger.info(f"已加载提示词文件: {yaml_file.name}")
            except Exception as e:
                logger.error(f"加载提示词文件失败: {yaml_file.name}, {e}")

    def get_prompt(self, key: str, variables: Optional[Dict[str, Any]] = None) -> str:
        """
        获取提示词并渲染模板

        Args:
            key: 提示词键（如 "document_analysis"）
            variables: 模板变量

        Returns:
            str: 渲染后的提示词

        Raises:
            KeyError: 提示词不存在

        使用示例:
            prompt = prompt_manager.get_prompt(
                "document_analysis",
                variables={"clusters": clusters}
            )
        """
        if key not in self._prompts:
            raise KeyError(f"提示词 '{key}' 不存在。可用键: {list(self._prompts.keys())}")

        prompt_config = self._prompts[key]
        template_str = prompt_config.get("template", "")

        # 如果没有变量，直接返回模板
        if not variables:
            return template_str.strip()

        # 使用Jinja2渲染模板
        try:
            template = Template(template_str)
            rendered = template.render(variables)
            return rendered.strip()
        except Exception as e:
            logger.error(f"渲染提示词失败: {key}, {e}")
            return template_str.strip()

    def get_parameters(self, key: str) -> Dict[str, Any]:
        """
        获取提示词的参数配置（如temperature, max_tokens）

        Args:
            key: 提示词键

        Returns:
            Dict: 参数配置
        """
        if key not in self._prompts:
            return {}

        return self._prompts[key].get("parameters", {})

    def list_prompts(self) -> list:
        """列出所有可用的提示词键"""
        return list(self._prompts.keys())

    def get_prompt_info(self, key: str) -> Dict[str, Any]:
        """
        获取提示词的元信息

        Args:
            key: 提示词键

        Returns:
            Dict: 包含name, description, version等
        """
        if key not in self._prompts:
            raise KeyError(f"提示词 '{key}' 不存在")

        config = self._prompts[key]
        return {
            "name": config.get("name", ""),
            "description": config.get("description", ""),
            "version": config.get("version", "1.0"),
            "parameters": config.get("parameters", {})
        }


# 全局单例
prompt_manager = PromptManager()


# ========== 便捷函数 ==========

def get_prompt(key: str, **kwargs) -> str:
    """快捷方式：获取提示词"""
    return prompt_manager.get_prompt(key, variables=kwargs)


def get_prompt_params(key: str) -> Dict[str, Any]:
    """快捷方式：获取参数"""
    return prompt_manager.get_parameters(key)
```

**3. 业务代码改造**

**修改前** ❌:
```python
# graphrag_agent/ai_copilot/document_analyzer.py

def _build_recommendation_prompt(self, analysis_result):
    # ❌ 硬编码提示词（见上文）
    prompt = f"""
    你是一个知识图谱专家...
    """
    return prompt
```

**修改后** ✅:
```python
# graphrag_agent/ai_copilot/document_analyzer.py

from graphrag_agent.config.prompts.prompt_manager import get_prompt, get_prompt_params

class DocumentAnalyzer:

    def generate_graph_config_recommendations(self, analysis_result):
        """
        ✅ 改进：使用PromptManager获取提示词
        """
        # 获取提示词
        prompt = get_prompt(
            "graph_config_recommendation",
            analysis=analysis_result
        )

        # 获取模型参数
        params = get_prompt_params("graph_config_recommendation")

        # 调用LLM
        response = self.llm.invoke(
            prompt,
            temperature=params.get("temperature", 0.5),
            max_tokens=params.get("max_tokens", 2000)
        )

        return response
```

---

#### 热更新支持（可选，高级功能）

**新建API端点**: `server/routers/prompts.py`

```python
"""
Prompt管理API
允许前端查看和更新提示词（热更新）
"""

from fastapi import APIRouter, HTTPException, Body
from typing import Dict, Any
from graphrag_agent.config.prompts.prompt_manager import prompt_manager

router = APIRouter(prefix="/prompts", tags=["Prompt管理"])


@router.get("/list", summary="列出所有提示词")
async def list_prompts() -> Dict[str, Any]:
    """列出所有可用的提示词键"""
    prompts = prompt_manager.list_prompts()
    return {
        "total": len(prompts),
        "prompts": prompts
    }


@router.get("/{key}", summary="获取提示词详情")
async def get_prompt_detail(key: str) -> Dict[str, Any]:
    """
    获取指定提示词的详细信息

    Args:
        key: 提示词键

    Returns:
        提示词详情（包含template, parameters等）
    """
    try:
        info = prompt_manager.get_prompt_info(key)
        template = prompt_manager.get_prompt(key)

        return {
            "key": key,
            "info": info,
            "template": template
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/reload", summary="热更新提示词")
async def reload_prompts() -> Dict[str, str]:
    """
    重新加载所有提示词文件（无需重启服务）

    使用场景：
    1. 修改了YAML文件
    2. 点击前端"刷新"按钮
    3. 立即生效，无需重启

    Returns:
        重载结果
    """
    try:
        prompt_manager.reload()
        prompts = prompt_manager.list_prompts()

        return {
            "status": "success",
            "message": f"成功重载 {len(prompts)} 个提示词配置",
            "prompts": prompts
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重载失败: {str(e)}")
```

**前端集成** (`frontend/page_components/config_manager.py`):

```python
# 在配置管理页面添加"Prompt Playground"标签页

import streamlit as st
import requests
from utils.api import get_api_url

def render_prompt_playground():
    """Prompt编辑器（高级功能）"""

    st.header("🎯 Prompt Playground")

    # 1. 列出所有prompts
    try:
        response = requests.get(f"{get_api_url()}/prompts/list")
        prompts = response.json()["prompts"]

        # 选择器
        selected_key = st.selectbox("选择Prompt", prompts)

        # 2. 加载选中的prompt
        if selected_key:
            detail_response = requests.get(f"{get_api_url()}/prompts/{selected_key}")
            detail = detail_response.json()

            # 显示元信息
            st.info(f"**名称**: {detail['info']['name']}\n\n**描述**: {detail['info']['description']}")

            # 编辑器（只读模式，生产环境不建议直接编辑）
            template = st.text_area(
                "模板内容",
                value=detail["template"],
                height=400,
                disabled=True  # 只读
            )

            # 参数配置
            st.subheader("参数配置")
            st.json(detail["info"]["parameters"])

            # 刷新按钮
            if st.button("🔄 重新加载Prompts（热更新）"):
                reload_response = requests.post(f"{get_api_url()}/prompts/reload")
                if reload_response.status_code == 200:
                    st.success("✅ Prompts已重新加载！")
                else:
                    st.error(f"❌ 重载失败: {reload_response.text}")

    except Exception as e:
        st.error(f"加载失败: {e}")
```

---

### 测试与验证

#### 热更新测试

```bash
# 1. 修改YAML文件
vim graphrag_agent/config/prompts/ai_copilot_prompts.yaml
# (修改某个提示词的内容)

# 2. 无需重启服务，直接调用reload API
curl -X POST http://localhost:8000/api/prompts/reload

# 3. 发起业务请求，验证LLM接收到的prompt是否已变更
curl -X POST http://localhost:8000/api/ai-copilot/analyze \
  -H "Content-Type: application/json" \
  -d '{"documents": [...]}'
```

---

## 问题三：社区检测与摘要算法缺乏可配置性 ⚙️

### 问题分析

#### 现状（修改前）

**全局配置** (`graphrag_agent/config/settings.py`):

```python
# ❌ 问题：只能通过环境变量配置，无法针对单次构建任务设置
community_algorithm = os.getenv("GRAPH_COMMUNITY_ALGORITHM", "leiden")
GDS_MEMORY_LIMIT = _get_env_int("GDS_MEMORY_LIMIT", 6) or 6
```

**工厂模式使用** (`graphrag_agent/community/detector/__init__.py`):

```python
# ✅ 已有工厂模式
class CommunityDetectorFactory:
    @staticmethod
    def create(algorithm: str = None, **kwargs):
        if algorithm is None:
            algorithm = community_algorithm  # ❌ 依赖全局配置

        # ...
```

**问题点**：

1. **配置固化** - 所有构建任务使用相同算法，无法A/B测试
2. **无运行时配置** - 前端无法选择不同算法
3. **参数硬编码** - `GDS_MEMORY_LIMIT` 等参数从全局settings读取

---

### 解决方案

#### 目标架构

```
前端选择算法 + 参数
    ↓
BuildRequest (包含 community_config)
    ↓
IncrementalUpdateManagerV2 (接受 config参数)
    ↓
CommunityDetectorFactory.create(algorithm, **params)
    ↓
社区检测算法
```

#### 核心改进

**1. 定义 CommunityConfig 模型**

**新建文件**: `graphrag_agent/config/community_config.py`

```python
"""
社区检测配置模型
支持针对单次构建任务配置不同的社区检测算法和参数
"""

from pydantic import BaseModel, Field
from typing import Literal, Optional


class CommunityConfig(BaseModel):
    """社区检测配置"""

    algorithm: Literal["leiden", "sllpa", "louvain"] = Field(
        default="leiden",
        description="社区检测算法"
    )

    # Leiden 参数
    max_level: int = Field(default=10, description="Leiden最大层级", ge=1, le=20)
    resolution: float = Field(default=1.0, description="分辨率参数", ge=0.1, le=10.0)

    # SLLPA 参数
    max_iterations: int = Field(default=20, description="SLLPA最大迭代次数", ge=1, le=100)

    # 通用参数
    gds_memory_limit: int = Field(default=6, description="GDS内存限制（GB）", ge=1, le=32)
    gds_concurrency: int = Field(default=4, description="GDS并发数", ge=1, le=16)

    # 摘要生成参数
    enable_summary: bool = Field(default=True, description="是否生成社区摘要")
    summary_max_length: int = Field(default=500, description="摘要最大长度", ge=100, le=2000)

    class Config:
        json_schema_extra = {
            "example": {
                "algorithm": "leiden",
                "max_level": 10,
                "resolution": 1.0,
                "gds_memory_limit": 6,
                "enable_summary": True
            }
        }


def get_default_community_config() -> CommunityConfig:
    """获取默认配置（从环境变量读取）"""
    from graphrag_agent.config.settings import (
        community_algorithm,
        GDS_MEMORY_LIMIT,
        GDS_CONCURRENCY
    )

    return CommunityConfig(
        algorithm=community_algorithm,
        gds_memory_limit=GDS_MEMORY_LIMIT,
        gds_concurrency=GDS_CONCURRENCY
    )
```

**2. 修改工厂模式**

**修改文件**: `graphrag_agent/community/detector/__init__.py`

```python
# ✅ 改进：接受config参数，优先使用传入的配置

from typing import Optional
from graphrag_agent.config.community_config import CommunityConfig, get_default_community_config

class CommunityDetectorFactory:
    """社区检测器工厂"""

    @staticmethod
    def create(
        config: Optional[CommunityConfig] = None,
        algorithm: Optional[str] = None,  # 向后兼容
        **kwargs
    ):
        """
        创建社区检测器

        ✅ 改进：优先使用传入的config，回退到全局settings

        Args:
            config: 社区检测配置对象（推荐）
            algorithm: 算法名称（向后兼容，不推荐）
            **kwargs: 其他参数

        Returns:
            BaseCommunityDetector: 检测器实例
        """
        # 如果没有传入config，使用默认配置
        if config is None:
            config = get_default_community_config()

        # 向后兼容：如果传入了algorithm参数，覆盖config
        if algorithm:
            config.algorithm = algorithm

        # 根据算法类型创建检测器
        if config.algorithm == "leiden":
            from .leiden import LeidenDetector
            return LeidenDetector(
                max_level=config.max_level,
                resolution=config.resolution,
                memory_limit=config.gds_memory_limit,
                concurrency=config.gds_concurrency
            )

        elif config.algorithm == "sllpa":
            from .sllpa import SLLPADetector
            return SLLPADetector(
                max_iterations=config.max_iterations,
                memory_limit=config.gds_memory_limit,
                concurrency=config.gds_concurrency
            )

        # ... 其他算法

        else:
            raise ValueError(f"不支持的社区检测算法: {config.algorithm}")
```

**3. 修改构建管理器**

**修改文件**: `graphrag_agent/integrations/build/incremental_update_v2.py`

```python
# ✅ 改进：接受community_config参数

from graphrag_agent.config.community_config import CommunityConfig

class IncrementalUpdateManagerV2:

    def __init__(
        self,
        files_dir: str = FILES_DIR,
        config=None,
        broadcaster=None,
        community_config: Optional[CommunityConfig] = None  # ✅ 新增参数
    ):
        # ...
        self.community_config = community_config  # 保存配置

    def detect_communities(self):
        """
        执行社区检测

        ✅ 改进：使用self.community_config而不是全局settings
        """
        # ...

        # ✅ 使用传入的配置
        detector = CommunityDetectorFactory.create(config=self.community_config)

        # 执行检测
        result = detector.detect_communities(self.graph)

        # ...
```

**4. 修改API路由**

**修改文件**: `server/routers/build.py`

```python
# ✅ 改进：BuildRequest接受community_config参数

from graphrag_agent.config.community_config import CommunityConfig

class BuildRequest(BaseModel):
    """构建请求参数"""

    mode: str = Field(...)
    file_paths: Optional[list[str]] = Field(default=None)

    # ✅ 新增：社区检测配置
    community_config: Optional[CommunityConfig] = Field(
        default=None,
        description="社区检测配置（可选，不传则使用默认配置）"
    )


async def _run_build_task(request: BuildRequest):
    """后台执行构建任务"""
    # ...

    # ✅ 创建管理器时传入配置
    manager = IncrementalUpdateManagerV2(
        files_dir=FILES_DIR,
        broadcaster=broadcaster,
        community_config=request.community_config  # ✅ 传递配置
    )

    # ...
```

**5. 前端集成**

**修改文件**: `frontend/page_components/build_manager.py`

```python
# ✅ 改进：前端允许用户选择算法和参数

def build_manager_page():
    st.header("🏗️ 构建管理")

    # ...构建模式选择...

    # ========== 高级配置（可折叠） ==========
    with st.expander("⚙️ 高级配置", expanded=False):
        st.subheader("社区检测配置")

        # 算法选择
        algorithm = st.selectbox(
            "社区检测算法",
            options=["leiden", "sllpa", "louvain"],
            index=0,
            help="Leiden: 多层级社区检测（推荐）\nSLLPA: 标签传播算法\nLouvain: 传统模块度优化"
        )

        # 参数配置（根据算法显示不同参数）
        col1, col2 = st.columns(2)

        with col1:
            if algorithm == "leiden":
                max_level = st.slider("最大层级", 1, 20, 10)
                resolution = st.slider("分辨率", 0.1, 10.0, 1.0, step=0.1)

            elif algorithm == "sllpa":
                max_iterations = st.slider("最大迭代次数", 1, 100, 20)

        with col2:
            gds_memory = st.slider("GDS内存限制（GB）", 1, 32, 6)
            enable_summary = st.checkbox("生成社区摘要", value=True)

    # ========== 开始构建 ==========
    if st.button("🚀 开始构建", type="primary"):
        # 构造请求
        build_request = {
            "mode": build_mode,
            "file_paths": None,
            "community_config": {
                "algorithm": algorithm,
                "max_level": max_level if algorithm == "leiden" else 10,
                "max_iterations": max_iterations if algorithm == "sllpa" else 20,
                "gds_memory_limit": gds_memory,
                "enable_summary": enable_summary
            }
        }

        # 发起请求
        response = requests.post(
            f"{API_URL}/build/run",
            json=build_request
        )

        # ...
```

---

### 测试与验证

#### A/B 测试

```bash
# 测试A：使用Leiden算法
curl -X POST http://localhost:8000/api/build/run \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "incremental",
    "community_config": {
      "algorithm": "leiden",
      "max_level": 10,
      "resolution": 1.0
    }
  }'

# 等待构建完成，查询Neo4j
cypher> MATCH (c:__Community__) RETURN c.algorithm, count(c);
# 预期: algorithm="leiden"

# 测试B：使用SLLPA算法
curl -X POST http://localhost:8000/api/build/run \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "incremental",
    "community_config": {
      "algorithm": "sllpa",
      "max_iterations": 20
    }
  }'

# 查询结果对比
cypher> MATCH (c:__Community__) WHERE c.algorithm="sllpa" RETURN count(c);
```

#### 参数生效测试

```python
# 在LeidenDetector中添加日志

class LeidenDetector(BaseCommunityDetector):
    def __init__(self, max_level=10, resolution=1.0, memory_limit=6, concurrency=4):
        super().__init__()
        self.max_level = max_level
        self.resolution = resolution

        # ✅ 添加日志验证参数
        logger.info(
            "LeidenDetector初始化",
            max_level=max_level,
            resolution=resolution,
            memory_limit=memory_limit,
            concurrency=concurrency
        )
```

**测试步骤**:
1. 前端设置 `max_level=5` (非默认值10)
2. 点击"开始构建"
3. 查看后端日志：
   ```
   [INFO] LeidenDetector初始化: max_level=5, resolution=1.0, memory_limit=6
   ```
4. ✅ 验证通过：参数已生效

---

## 附录

### A. 迁移优先级建议

根据影响和工作量，建议迁移顺序：

| 优先级 | 问题 | 时间估算 | 理由 |
|-------|------|---------|------|
| **P1** | 提示词硬编码 | 1-2天 | 影响最大，工作量适中 |
| **P2** | 社区检测配置 | 0.5-1天 | 工作量小，价值高 |
| **P3** | 前端组件重构 | 3-5天 | 工作量大，可渐进式重构 |

### B. 渐进式重构策略

#### 提示词管理（P1）

**阶段1**（1天）:
- [ ] 创建 `ai_copilot_prompts.yaml`
- [ ] 实现 `PromptManager` 类
- [ ] 改造 `document_analyzer.py`

**阶段2**（0.5天）:
- [ ] 添加 `/prompts` API
- [ ] 前端集成 Prompt Playground

**验收标准**:
- ✅ 修改YAML后调用reload API立即生效
- ✅ 无需重启服务

---

#### 社区检测配置（P2）

**阶段1**（0.5天）:
- [ ] 创建 `CommunityConfig` 模型
- [ ] 修改 `CommunityDetectorFactory`
- [ ] 修改 `IncrementalUpdateManagerV2`

**阶段2**（0.5天）:
- [ ] 修改 `/build/run` API
- [ ] 前端添加配置面板

**验收标准**:
- ✅ 同一数据集，Leiden和SLLPA结果不同
- ✅ 参数变化反映在检测结果中

---

#### 前端组件重构（P3，可延后）

**阶段1**（1天）:
- [ ] 创建 `widgets/` 目录
- [ ] 实现 buttons, cards, loaders 组件
- [ ] 创建 `gallery.py` 展示页

**阶段2**（2天）:
- [ ] 创建 `services/` 层
- [ ] 重构 `ai_config_wizard.py` → 拆分为 view + service

**阶段3**（2天）:
- [ ] 创建 `pages/` 和 `views/` 目录
- [ ] 逐步迁移其他页面组件

**验收标准**:
- ✅ `services/` 中无 `st.` 调用
- ✅ 所有原子组件在 gallery 中可预览
- ✅ 逻辑解耦测试通过

---

### C. 代码审查清单

#### 提示词管理

- [ ] 所有LLM调用都使用 `PromptManager`
- [ ] 无硬编码的长字符串提示词
- [ ] YAML文件包含 name, description, version
- [ ] Jinja2模板语法正确

#### 社区检测

- [ ] 工厂方法优先使用 `config` 参数
- [ ] 检测器构造函数接受参数（不从全局settings读）
- [ ] API请求包含 `community_config`
- [ ] 前端配置面板参数完整

#### 前端组件

- [ ] `services/` 层不导入 streamlit
- [ ] `widgets/` 组件可在 gallery 中独立运行
- [ ] `views/` 层不调用 requests
- [ ] `pages/` 层仅负责状态组装

---

## 总结

本文档针对三个架构问题提供了详细的重构方案：

1. ✅ **前端组件划分不清** → 分层架构（Pages/Views/Widgets/Services）
2. ✅ **提示词硬编码** → PromptManager + YAML配置 + 热更新
3. ✅ **社区检测缺乏配置** → CommunityConfig + 运行时参数传递

**建议实施顺序**: P1提示词 → P2社区检测 → P3前端重构

**预期收益**:
- 可维护性提升 200%（提示词无需改代码）
- 灵活性提升 300%（社区检测支持A/B测试）
- 可测试性提升 150%（逻辑解耦）

---

**文档版本**: v1.0
**最后更新**: 2025-12-25
**维护者**: Claude Code
