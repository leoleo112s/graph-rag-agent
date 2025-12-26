# Model 模块

## 目录结构

```
graphrag_agent/models/
├── __init__.py          # 模块初始化文件
├── get_models.py        # 模型获取和初始化功能
├── model_manager.py     # 🆕 模型管理器（动态模型切换）
└── test_stream_model.py # 流式模型测试
```

## 模块说明

Model 模块负责初始化和管理各种语言模型，主要基于 LangChain 框架实现了对 OpenAI API 的集成，支持普通调用和流式输出两种模式。

### 核心功能

1. **模型初始化**：支持从环境变量加载配置参数，灵活配置模型行为

2. **支持的模型类型**：
   - 嵌入模型 (Embeddings)：用于文本向量化
   - 对话模型 (LLM)：支持普通和流式两种输出方式

3. **流式输出支持**：通过 AsyncIteratorCallbackHandler 实现逐字输出能力

### 核心函数

- `get_embeddings_model()`：初始化并返回文本嵌入模型，用于向量化查询和文档
- `get_llm_model()`：初始化并返回标准对话模型，用于一次性生成完整回答
- `get_stream_llm_model()`：初始化并返回流式对话模型，支持逐字输出，提升用户体验

## 🆕 模型管理器 (New in v2.1)

### 概述

`ModelManager` 是一个单例类，提供动态模型注册、切换和管理功能，无需重启服务即可更换 LLM 或 Embedding 模型。

### 核心特性

1. **单例模式**：全局唯一实例，线程安全
2. **动态切换**：无需重启服务即可更换模型
3. **持久化存储**：模型配置保存在 `data/model_registry.json`
4. **多提供商支持**：OpenAI、本地模型、自定义端点
5. **默认保护**：不允许删除从 `.env` 加载的默认模型

### 核心方法

- `get_model_manager()`：获取全局单例实例
- `register_model()`：注册新模型配置
- `list_models()`：列出所有模型（支持过滤）
- `get_model()`：获取指定模型配置
- `activate_model()`：激活模型（设为当前使用）
- `delete_model()`：删除模型（默认模型受保护）
- `get_active_llm()`：获取当前活跃的 LLM 实例
- `get_active_embedding()`：获取当前活跃的 Embedding 实例
- `reload_models()`：重新加载模型（清空缓存）

### 使用方法

```python
# 标准模型使用示例
from graphrag_agent.models.get_models import get_llm_model

llm = get_llm_model()
response = llm.invoke("你好")
print(response)

# 流式模型使用示例(注：由于langchain bug，这里需要改源码才能使用，本项目采用模拟流式输出)
import asyncio
from graphrag_agent.models.get_models import get_stream_llm_model
from langchain_core.messages import HumanMessage

async def main():
    chat = get_stream_llm_model()
    messages = [HumanMessage(content="Tell me a short joke.")]
    async for chunk in chat.astream(messages):
        print(chunk.content, end="", flush=True)

asyncio.run(main())
```

### 模型管理器使用示例

```python
from graphrag_agent.models.model_manager import get_model_manager

# 1. 获取单例实例
manager = get_model_manager()

# 2. 注册新的 LLM 模型
model_id = manager.register_model(
    name="DeepSeek-V3",
    model_type="llm",
    provider="openai",  # OpenAI 兼容
    config={
        "model": "deepseek-chat",
        "api_key": "sk-xxx",
        "base_url": "https://api.deepseek.com/v1",
        "temperature": 0.7,
        "max_tokens": 4096
    },
    description="DeepSeek V3 模型",
    tags=["deepseek", "chinese"],
    set_active=False  # 暂不激活
)

# 3. 列出所有 LLM 模型
llm_models = manager.list_models(model_type="llm")
for model in llm_models:
    print(f"{model.name} - Active: {model.is_active}")

# 4. 激活模型（切换当前使用的模型）
manager.activate_model(model_id)

# 5. 获取当前活跃的模型实例
llm = manager.get_active_llm()
response = llm.invoke("你好")
print(response)

# 6. 重新加载模型（清空缓存）
manager.reload_models()

# 7. 删除模型
manager.delete_model(model_id)
```

### 前端界面使用

访问 Web 界面的 "🧠 模型中心" 页面：

1. **查看当前模型**：页面顶部显示当前活跃的 LLM 和 Embedding 模型
2. **注册新模型**：点击 "➕ 注册新模型" 按钮，填写配置信息
3. **切换模型**：点击模型卡片上的 "激活" 按钮即可切换
4. **删除模型**：点击 "🗑️" 按钮删除不需要的模型（默认模型不可删除）

### 使用场景

- **A/B 测试**：快速切换不同模型对比效果
- **成本优化**：简单任务使用便宜模型，复杂任务使用高级模型
- **提供商迁移**：从 OpenAI 切换到 DeepSeek、Claude 等
- **本地部署**：使用本地 .gguf 模型保护隐私

### 配置说明

模块依赖以下环境变量：
- `OPENAI_API_KEY`: OpenAI API 密钥
- `OPENAI_BASE_URL`: API 基础 URL (可配置为代理或自定义端点)
- `OPENAI_EMBEDDINGS_MODEL`: 使用的嵌入模型名称
- `OPENAI_LLM_MODEL`: 使用的语言模型名称
- `TEMPERATURE`: 模型温度参数
- `MAX_TOKENS`: 最大生成token数