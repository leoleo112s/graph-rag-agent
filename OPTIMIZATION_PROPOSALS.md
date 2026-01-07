# 提示词管理优化方案

## 📊 当前架构问题

### 问题1️⃣：三种方案并存，职责不清

```
传统模式 (graph_prompts.py)
    ↓ 硬编码，Few-shot示例在代码中

GraphConfig模式 (DynamicPromptBuilder)
    ↓ 多领域支持，但Few-shot示例仍在代码中

YAML模式 (PromptBuilder)
    ↓ 灵活可配置，但未集成
```

**问题**：
- 传统模式和YAML模式功能重叠（都是单领域）
- Few-shot示例散落在代码中，难以维护
- YAML文件存在但未使用，容易造成误解

### 问题2️⃣：缺少统一的Few-shot管理

**当前状态**：
- `graph_prompts.py` - 示例硬编码在提示词中
- `DynamicPromptBuilder` - 示例硬编码在代码中（第115-148行）
- `entity_extraction.yaml` - 示例在YAML中（但未被使用）

**后果**：
- 修改示例需要改代码并重启服务
- 不同场景无法快速切换示例
- A/B测试提示词成本高

### 问题3️⃣：YAML配置本身存在问题

1. **示例不符合约束**：
   ```yaml
   # 约束：每个实体至少出现 2 次才抽取
   # 但示例中的实体大多只出现 1 次 ❌
   ```

2. **默认参数为空**：
   ```yaml
   parameters:
     entity_types: []  # 空列表会导致无法抽取
     relation_types: []
   ```

---

## 💡 优化方案（三选一）

### 方案A：最小化改动 - 统一到YAML（推荐⭐）

**适用场景**：单一领域项目，不需要GraphConfig的多领域能力

**改动**：
1. ✅ 修复YAML配置中的问题
2. ✅ 让`extractor_factory.py`支持从YAML加载
3. ✅ 废弃传统模式（graph_prompts.py）

**优点**：
- ✅ 提示词配置统一到YAML，易读易维护
- ✅ Few-shot示例可配置，支持快速迭代
- ✅ 修改提示词无需改代码、无需重启服务

**缺点**：
- ❌ 不支持多领域动态路由
- ❌ 需要手动管理不同领域的YAML文件

**实施步骤**：
```python
# 1. 修改 extractor_factory.py
def create_entity_extractor(...):
    # 优先级：GraphConfig > YAML > 传统模式
    config = storage.load()

    if config is not None:
        # 使用 GraphConfig（多领域场景）
        return create_from_graph_config(config, llm, ...)

    # 尝试加载 YAML 模板
    yaml_builder = PromptBuilder()
    if "entity_extraction" in yaml_builder.list_templates():
        # 使用 YAML 配置（单领域场景）
        return create_from_yaml(yaml_builder, llm, ...)

    # 回退到传统模式
    return create_from_templates(system_template, human_template, ...)
```

---

### 方案B：混合架构 - GraphConfig + YAML示例库

**适用场景**：多领域项目，但希望Few-shot示例可配置

**改动**：
1. ✅ 保留GraphConfig的多领域能力
2. ✅ 将Few-shot示例迁移到YAML
3. ✅ DynamicPromptBuilder从YAML加载示例

**优点**：
- ✅ 保留多领域、桥接点等高级功能
- ✅ Few-shot示例可配置，易于调整
- ✅ 架构清晰：GraphConfig管结构，YAML管示例

**缺点**：
- ⚠️ 需要维护两套配置（GraphConfig + YAML）
- ⚠️ 复杂度增加

**实施步骤**：
```python
# 1. 创建 examples.yaml
few_shot_examples:
  entity_extraction:
    - input: "..."
      output: "..."

  reasoning:
    - input: "..."
      output: "..."

# 2. 修改 DynamicPromptBuilder
class DynamicPromptBuilder:
    def __init__(self, config: GraphConfig, examples_path: str = None):
        self.config = config
        self.examples = self._load_examples(examples_path)

    def build_system_prompt(self):
        prompt = [...]

        # 从YAML加载示例
        if self.examples:
            prompt.append("\n## 示例")
            for ex in self.examples.get("entity_extraction", []):
                prompt.append(f"输入: {ex['input']}")
                prompt.append(f"输出: {ex['output']}")
```

---

### 方案C：完全重构 - 统一提示词管理层

**适用场景**：大型项目，需要支持多种场景

**改动**：
1. ✅ 创建统一的`PromptManager`
2. ✅ 支持多种配置源（GraphConfig、YAML、代码）
3. ✅ 支持提示词版本管理、A/B测试

**架构**：
```python
class PromptManager:
    """统一的提示词管理器"""

    def __init__(self):
        self.sources = [
            GraphConfigSource(),
            YAMLSource(),
            CodeSource()
        ]

    def get_prompt(self, task: str, mode: str = "auto"):
        """
        获取提示词

        Args:
            task: entity_extraction | reasoning | summarization
            mode: graphconfig | yaml | traditional | auto
        """
        if mode == "auto":
            # 自动选择最佳配置源
            for source in self.sources:
                if source.supports(task):
                    return source.get_prompt(task)
        else:
            # 手动指定配置源
            source = self._get_source(mode)
            return source.get_prompt(task)

    def get_examples(self, task: str, num: int = 3):
        """获取Few-shot示例（支持动态选择）"""
        return self.example_store.get(task, num)
```

**优点**：
- ✅ 统一接口，易于扩展
- ✅ 支持动态切换配置源
- ✅ 支持A/B测试、版本管理

**缺点**：
- ❌ 重构成本高
- ❌ 可能过度设计

---

## 🎯 我的推荐：方案A（统一到YAML）

### 为什么推荐方案A？

1. **你的项目可能是单领域的**
   - 如果你没有创建`data/graph_config.json`，说明不需要多领域能力
   - YAML方案足够满足需求

2. **YAML方案更灵活**
   - 修改提示词只需编辑YAML，无需重启服务
   - 非技术人员也能参与提示词优化
   - 支持快速A/B测试

3. **改动最小**
   - 不需要大规模重构
   - 只需修复YAML配置 + 集成到extractor_factory

### 具体实施计划

#### 第一步：修复YAML配置

```yaml
# config/prompts/entity_extraction.yaml

# 1. 修复示例（让实体至少出现2次）
examples:
  - input: |
      文本：学生在每学期开始前需要到教务处注册课程。学生注册时需要携带学生证到教务处办理。
      实体类型：["学生", "部门", "证件", "课程"]
      关系类型：["办理", "需要", "管理"]
    output: |
      {
        "entities": [
          {"name": "学生", "type": "学生", "description": "在校学习的人员"},
          {"name": "教务处", "type": "部门", "description": "负责教学管理的部门"},
          {"name": "学生证", "type": "证件", "description": "学生身份证明"}
        ],
        "relations": [
          {"source": "学生", "target": "教务处", "type": "办理", "description": "在教务处注册"},
          {"source": "学生", "target": "学生证", "type": "需要", "description": "注册时需要携带"}
        ]
      }

# 2. 添加合理的默认参数
parameters:
  domain: "通用"
  entity_types: ["人物", "组织", "地点", "事件", "概念"]  # 通用实体类型
  relation_types: ["属于", "包含", "相关", "导致"]  # 通用关系类型
```

#### 第二步：集成到extractor_factory.py

```python
def create_entity_extractor(...):
    # 优先级：GraphConfig > YAML > 传统模式

    # 1. 尝试加载 GraphConfig
    storage = get_storage()
    config = storage.load()

    if config is not None:
        print("✨ 检测到通用图谱配置，使用动态提示词生成")
        return _create_from_graph_config(config, llm, ...)

    # 2. 尝试加载 YAML 配置
    try:
        from graphrag_agent.prompts.prompt_builder import PromptBuilder
        yaml_builder = PromptBuilder()

        if "entity_extraction" in yaml_builder.list_templates():
            print("📄 使用 YAML 提示词模板")
            return _create_from_yaml(yaml_builder, llm, entity_types, relationship_types, ...)
    except Exception as e:
        print(f"⚠️  YAML 加载失败: {e}")

    # 3. 回退到传统模式
    print("📝 使用传统配置模式")
    return _create_from_templates(system_template, human_template, ...)


def _create_from_yaml(yaml_builder, llm, entity_types, relationship_types, **kwargs):
    """从YAML模板创建提取器"""

    # 如果没有传入entity_types，使用YAML默认值
    template = yaml_builder.load_template("entity_extraction")
    if not entity_types:
        entity_types = template.parameters.get("entity_types", [])
    if not relationship_types:
        relationship_types = template.parameters.get("relation_types", [])

    # 构建系统提示词和用户提示词
    messages = yaml_builder.build_messages(
        "entity_extraction",
        entity_types=entity_types,
        relation_types=relationship_types,
        text="{input_text}"  # 占位符
    )

    system_template = messages[0]["content"]
    # 提取用户提示词模板（去除示例）
    user_template = messages[-1]["content"]

    extractor = EntityRelationExtractor(
        llm=llm,
        system_template=system_template,
        human_template=user_template,
        entity_types=entity_types,
        relationship_types=relationship_types,
        **kwargs
    )

    extractor.is_dynamic = False
    extractor.prompt_source = "yaml"

    return extractor
```

#### 第三步：废弃传统模式

```python
# 在 graph_prompts.py 顶部添加警告
"""
⚠️ DEPRECATED: 此文件将被废弃

请使用以下方案之一：
1. GraphConfig模式（多领域项目）- 通过AI Copilot生成配置
2. YAML模式（单领域项目）- 编辑 config/prompts/entity_extraction.yaml

此文件仅作为回退方案保留。
"""
```

---

## 🔍 快速诊断：你的项目适合哪种方案？

运行以下命令：

```bash
# 1. 检查是否有 GraphConfig
if [ -f "data/graph_config.json" ]; then
    echo "✅ 发现 GraphConfig - 你的项目使用多领域模式"
    echo "   推荐：方案B（GraphConfig + YAML示例库）"
else
    echo "❌ 未发现 GraphConfig - 你的项目使用单领域模式"
    echo "   推荐：方案A（统一到YAML）"
fi

# 2. 检查领域数量
python3 -c "
from graphrag_agent.config.settings import entity_types, relationship_types
print(f'实体类型数: {len(entity_types)}')
print(f'关系类型数: {len(relationship_types)}')

if len(entity_types) > 20:
    print('⚠️  实体类型过多，建议使用多领域模式（GraphConfig）')
else:
    print('✅ 实体类型适中，可以使用YAML模式')
"
```

---

## ⏱️ 实施时间估算

| 方案 | 开发时间 | 测试时间 | 风险 |
|------|---------|---------|------|
| 方案A（YAML统一） | 2-3小时 | 1小时 | 低 |
| 方案B（混合架构） | 4-6小时 | 2小时 | 中 |
| 方案C（完全重构） | 2-3天 | 1天 | 高 |

---

## 🎯 下一步行动

如果你选择**方案A**（推荐）：

1. [ ] 修复 `entity_extraction.yaml` 中的问题
2. [ ] 在 `extractor_factory.py` 中添加YAML支持
3. [ ] 运行测试，确保向后兼容
4. [ ] 更新文档，说明如何使用YAML配置

我可以帮你实现这些改动，需要我开始吗？
