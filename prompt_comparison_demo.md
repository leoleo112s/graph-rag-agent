# extractor_factory.py 工作原理详解

## 📋 工作流程图

```
用户调用 create_entity_extractor()
    ↓
检查是否存在 GraphConfig (data/graph_config.json)
    ↓
┌───────────────┴───────────────┐
│                               │
有 GraphConfig                  无 GraphConfig
(动态模式)                      (传统模式)
    ↓                               ↓
DynamicPromptBuilder            使用传入的
    ↓                           system_template
生成系统提示词                   human_template
(包含所有领域定义)                  ↓
    ↓                           创建 EntityRelationExtractor
获取所有实体/关系类型            extractor.is_dynamic = False
    ↓
创建 EntityRelationExtractor
extractor.prompt_builder = prompt_builder
extractor.is_dynamic = True
```

---

## 🔵 方案A: DynamicPromptBuilder (GraphConfig 模式)

### 配置来源
```json
// data/graph_config.json
{
  "project_name": "学生管理系统",
  "industry": "教育",
  "bridge_definitions": [
    {
      "name": "学生类型",
      "key": "bridge_student_type",
      "description": "学生的分类",
      "examples": ["本科生", "研究生", "博士生"]
    }
  ],
  "domain_definitions": [
    {
      "domain_name": "规则库",
      "description": "学校规章制度",
      "trigger_condition": "当文档包含条款、规定、处分时",
      "schema": {
        "entities": ["学生", "处分", "规定", "部门"],
        "relations": ["违纪", "处分", "申诉"]
      }
    },
    {
      "domain_name": "奖学金库",
      "description": "奖学金相关文档",
      "trigger_condition": "当文档包含奖学金、评选、资助时",
      "schema": {
        "entities": ["奖学金类型", "评选条件", "资助金额"],
        "relations": ["申请", "评选", "发放"]
      }
    }
  ]
}
```

### 生成的系统提示词（示例）

```
# 任务：学生管理系统

本项目用于构建学生管理相关的知识图谱

## 重要：桥接点（Bridge Points）
以下是连接所有领域的公共概念，必须在每个文档中提取：

### 学生类型 (key: bridge_student_type)
- 描述：学生的分类
- 示例：本科生, 研究生, 博士生
- **提取规则**：根据文档内容自由提取

## 领域（Domains）
根据文档内容，判断其所属领域，并提取相应的实体和关系：

### 领域 1：规则库
- 描述：学校规章制度
- 触发条件：当文档包含条款、规定、处分时
- 实体类型：学生, 处分, 规定, 部门
- 关系类型：违纪, 处分, 申诉

### 领域 2：奖学金库
- 描述：奖学金相关文档
- 触发条件：当文档包含奖学金、评选、资助时
- 实体类型：奖学金类型, 评选条件, 资助金额
- 关系类型：申请, 评选, 发放

## 关键抽取规则 (CRITICAL RULES)
1. **实体名称(name)必须保持原文**：
   - 不要翻译，不要缩写，不要改写
   - 例如原文是"学生处"，name必须是"学生处"，不能是"StudentOffice"

2. **实体类型(type)必须使用Schema定义的类型**：
   - 类型必须严格从定义的 schema 中选择
   - 禁止创造新类型

3. **桥接点(Bridge)优先**：
   - 一旦发现文档内容匹配'桥接点'定义，必须提取

4. **禁止臆造关系**：
   - 只有当原文明确提到两个实体有关联时才提取

[... 更多规则和示例 ...]
```

### 特点
- ✅ **动态领域路由**: 根据文档内容自动判断属于哪个领域
- ✅ **桥接点连接**: 支持跨领域的公共概念
- ✅ **多领域支持**: 可以在一个文档中提取多个领域的实体
- ⚠️ **提示词硬编码**: Few-shot 示例写死在代码中，修改需要改代码

---

## 🟢 方案B: PromptBuilder (YAML 模式)

### 配置来源
```yaml
# config/prompts/entity_extraction.yaml
name: entity_extraction
version: "1.0.0"
description: "实体和关系抽取提示词模板"

system_prompt: |
  你是一个专业的知识图谱构建助手。你的任务是从给定文本中抽取实体和关系。

  请严格遵循以下原则：
  - 只抽取属于指定实体类型的实体
  - 实体名称必须与原文完全一致（保持中文）
  - 关系必须基于文本明确表达的内容
  - 每个实体至少出现 2 次才抽取

user_prompt_template: |
  领域：{domain}

  允许的实体类型：{entity_types}
  允许的关系类型：{relation_types}

  文本内容：
  {text}

  请抽取文本中的实体和关系，以 JSON 格式返回。

parameters:
  domain: "通用"
  entity_types: []
  relation_types: []

examples:
  - input: |
      文本：学生在每学期开始前需要到教务处注册课程。注册时需要携带学生证。
      实体类型：["学生", "部门", "证件", "课程"]
      关系类型：["办理", "需要", "管理"]
    output: |
      {
        "entities": [
          {"name": "学生", "type": "学生", "description": "在校学习的人员"},
          {"name": "教务处", "type": "部门", "description": "负责教学管理的部门"},
          {"name": "学生证", "type": "证件", "description": "学生身份证明"},
          {"name": "课程", "type": "课程", "description": "教学科目"}
        ],
        "relations": [
          {"source": "学生", "target": "教务处", "type": "办理", "description": "在教务处注册"},
          {"source": "学生", "target": "学生证", "type": "需要", "description": "注册时需要携带"}
        ]
      }
```

### 生成的系统提示词（示例）

调用方式：
```python
builder = PromptBuilder()
messages = builder.build_messages(
    "entity_extraction",
    text="学生在每学期开始前需要到教务处注册课程",
    entity_types=["学生", "部门", "课程"],
    relation_types=["办理", "需要"],
    domain="教育"
)
```

生成的消息：
```python
[
  {
    "role": "system",
    "content": """
你是一个专业的知识图谱构建助手。你的任务是从给定文本中抽取实体和关系。

请严格遵循以下原则：
- 只抽取属于指定实体类型的实体
- 实体名称必须与原文完全一致（保持中文）
- 关系必须基于文本明确表达的内容
- 每个实体至少出现 2 次才抽取

约束条件：
- 实体名称必须与原文保持一致
- 只抽取出现次数 ≥ 2 的实体
- 关系必须基于明确的文本依据
- 不要推测或补充原文中没有的信息

输出格式：
{
  "entities": [
    {"name": "实体名", "type": "实体类型", "description": "简短描述"}
  ],
  "relations": [
    {"source": "源实体", "target": "目标实体", "type": "关系类型", "description": "关系描述"}
  ]
}
"""
  },
  {
    "role": "user",
    "content": "文本：学生在每学期开始前需要到教务处注册课程。注册时需要携带学生证。\n实体类型：[\"学生\", \"部门\", \"证件\", \"课程\"]\n关系类型：[\"办理\", \"需要\", \"管理\"]"
  },
  {
    "role": "assistant",
    "content": "{\"entities\": [{\"name\": \"学生\", \"type\": \"学生\"...}]}"
  },
  {
    "role": "user",
    "content": """
领域：教育

允许的实体类型：['学生', '部门', '课程']
允许的关系类型：['办理', '需要']

文本内容：
学生在每学期开始前需要到教务处注册课程

请抽取文本中的实体和关系，以 JSON 格式返回。
"""
  }
]
```

### 特点
- ✅ **易读易维护**: YAML 格式清晰，非技术人员也能理解
- ✅ **灵活配置**: 修改提示词只需编辑 YAML 文件，无需重启服务
- ✅ **Few-shot 示例**: 在 YAML 中配置，支持多个示例
- ✅ **模板版本控制**: MD5 哈希用于缓存失效
- ❌ **单领域限制**: 无法动态路由到不同领域
- ❌ **无桥接点支持**: 不支持跨领域的公共概念

---

## 📊 两种方案的核心区别

### 1. 提示词生成逻辑

**方案A (DynamicPromptBuilder)**:
```python
# graphrag_agent/prompts/dynamic_prompt_builder.py:23
def build_system_prompt(self) -> str:
    prompt_parts = []
    prompt_parts.append(f"# 任务：{self.config.project_name}")

    # 动态拼接桥接点
    for bridge in self.config.bridge_definitions:
        prompt_parts.append(f"### {bridge.name} (key: {bridge.key})")
        prompt_parts.append(f"- 描述：{bridge.description}")

    # 动态拼接领域
    for domain in self.config.domain_definitions:
        prompt_parts.append(f"### 领域：{domain.domain_name}")
        prompt_parts.append(f"- 实体类型：{', '.join(domain.schema.entities)}")

    return "\n".join(prompt_parts)
```

**方案B (PromptBuilder)**:
```python
# graphrag_agent/prompts/prompt_builder.py:144
def build(self, template_name: str, **kwargs) -> str:
    template = self.load_template(template_name)
    params = {**template.parameters, **kwargs}

    # 简单的字符串插值
    user_prompt = template.user_prompt_template.format(**params)

    return f"System: {system_prompt}\n\nUser: {user_prompt}"
```

### 2. 领域处理方式

**方案A**:
- 在 `entity_extractor.py` 中调用 `_route_domain_for_document()` 进行**动态领域路由**
- LLM 根据文档内容判断属于哪个领域
- 不同领域使用不同的实体/关系类型

**方案B**:
- **单一领域**，所有文档使用相同的实体/关系类型
- 需要手动切换模板或参数来处理不同领域

### 3. 使用场景对比

| 场景 | 方案A (GraphConfig) | 方案B (YAML) |
|------|---------------------|--------------|
| 单一领域项目 (如纯法律文档) | ⚠️ 过度设计 | ✅ **推荐** |
| 多领域项目 (如学生管理系统) | ✅ **推荐** | ❌ 无法支持 |
| AI Copilot 自动配置 | ✅ **推荐** | ❌ 无法集成 |
| 手动调整提示词 | ❌ 需要改代码 | ✅ **推荐** |
| 提示词 A/B 测试 | ❌ 需要改代码 | ✅ **推荐** |
| 跨领域实体连接 (桥接点) | ✅ **推荐** | ❌ 无法支持 |

---

## 🔍 如何验证当前使用的方案？

### 方法1: 查看日志

运行知识图谱构建：
```bash
python graphrag_agent/integrations/build/main.py
```

查看日志输出：
```
✨ 检测到通用图谱配置，使用动态提示词生成
📋 项目: 学生管理系统
🏢 行业: 教育
🔗 桥接点数量: 3
📦 领域数量: 2
```
→ **使用方案A (GraphConfig)**

或者：
```
📝 使用传统配置模式
```
→ **使用传统模式**（既不是A也不是B）

### 方法2: 检查配置文件是否存在

```bash
# 检查 GraphConfig
ls -lh data/graph_config.json

# 检查 YAML 模板
ls -lh config/prompts/*.yaml
```

如果 `data/graph_config.json` 存在 → 使用方案A
如果不存在 → 使用传统模式或方案B

### 方法3: 代码中添加调试日志

在 `extractor_factory.py:86` 添加：
```python
print(f"🔍 提示词构建器类型: {type(prompt_builder).__name__}")
print(f"🔍 is_dynamic: {extractor.is_dynamic}")
```

---

## 💡 结论

### extractor_factory.py 的工作原理：

1. **优先检查 GraphConfig**（方案A）
   - 如果存在 `data/graph_config.json`，使用 `DynamicPromptBuilder`
   - 生成包含所有领域定义的系统提示词
   - 支持动态领域路由和桥接点

2. **回退到传统模式**（既不是方案A也不是方案B）
   - 如果没有 GraphConfig，使用传入的 `system_template` 和 `human_template`
   - 这些模板来自 `graphrag_agent/prompts/graph_prompts.py`（硬编码）

3. **方案B (YAML) 目前未集成**
   - `entity_extraction.yaml` 等文件存在，但没有被 `extractor_factory.py` 使用
   - 需要手动修改代码才能启用

### 推荐方案：

- **如果你的项目是多领域的**（如学生管理系统有规则库、奖学金库、事实库等）
  → 使用 **方案A (GraphConfig)** + AI Copilot

- **如果你的项目是单一领域的**（如纯法律文档分析）
  → 考虑集成 **方案B (YAML)**，更灵活易维护

- **如果你想快速上手**
  → 使用当前的 **传统模式**（不需要配置，直接用）
