"""
最小化演示：对比两种提示词构建方式
无需导入项目依赖，直接读取文件展示
"""

import yaml
from pathlib import Path

print("=" * 80)
print("📊 提示词构建器对比演示（最小化版本）")
print("=" * 80)
print()

# ============================================================================
# 方案B: PromptBuilder (基于 YAML) - 直接读取 YAML 文件
# ============================================================================
print("🟢 方案B: PromptBuilder (基于 YAML 模板)")
print("-" * 80)

yaml_path = Path("config/prompts/entity_extraction.yaml")

if yaml_path.exists():
    with open(yaml_path, 'r', encoding='utf-8') as f:
        template = yaml.safe_load(f)

    print(f"✅ 成功加载 YAML 模板")
    print(f"   模板名: {template['name']}")
    print(f"   版本: {template['version']}")
    print(f"   描述: {template['description']}")
    print()

    print("📝 系统提示词:")
    print("-" * 80)
    print(template['system_prompt'])
    print()

    print("📝 用户提示词模板:")
    print("-" * 80)
    print(template['user_prompt_template'])
    print()

    print("🎯 默认参数:")
    print(f"   {template['parameters']}")
    print()

    print("📏 约束条件:")
    for constraint in template['constraints']:
        print(f"   - {constraint}")
    print()

    print("📤 输出格式:")
    print("-" * 80)
    print(template['output_format'])
    print()

    print("💡 Few-shot 示例:")
    print("-" * 80)
    for i, example in enumerate(template['examples'], 1):
        print(f"\n示例 {i}:")
        print(f"输入:\n{example['input']}")
        print(f"\n输出:\n{example['output']}")
    print()

    # 模拟参数插值
    print("🔧 模拟参数插值（使用实际参数）:")
    print("-" * 80)
    user_prompt = template['user_prompt_template'].format(
        domain="教育",
        entity_types=["学生", "部门", "课程"],
        relation_types=["办理", "需要"],
        text="学生在每学期开始前需要到教务处注册课程"
    )
    print(user_prompt)
    print()

else:
    print(f"❌ 未找到 YAML 文件: {yaml_path}")
    print()

# ============================================================================
# 方案A: DynamicPromptBuilder (基于 GraphConfig) - 展示逻辑
# ============================================================================
print()
print("🔵 方案A: DynamicPromptBuilder (基于 GraphConfig)")
print("-" * 80)

config_path = Path("data/graph_config.json")

if config_path.exists():
    import json

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    print(f"✅ 成功加载 GraphConfig")
    print(f"   项目名: {config.get('project_name', 'N/A')}")
    print(f"   行业: {config.get('industry', 'N/A')}")
    print(f"   桥接点数: {len(config.get('bridge_definitions', []))}")
    print(f"   领域数: {len(config.get('domain_definitions', []))}")
    print()

    print("🌉 桥接点定义:")
    print("-" * 80)
    for bridge in config.get('bridge_definitions', []):
        print(f"  - {bridge['name']} (key: {bridge['key']})")
        print(f"    描述: {bridge['description']}")
        if bridge.get('examples'):
            print(f"    示例: {', '.join(bridge['examples'])}")
        print()

    print("📦 领域定义:")
    print("-" * 80)
    for domain in config.get('domain_definitions', []):
        print(f"  - {domain['domain_name']}")
        print(f"    描述: {domain['description']}")
        print(f"    触发条件: {domain['trigger_condition']}")
        print(f"    实体类型: {', '.join(domain['schema']['entities'][:5])}...")
        print(f"    关系类型: {', '.join(domain['schema']['relations'][:5])}...")
        print()

    print("📝 提示词生成逻辑（伪代码）:")
    print("-" * 80)
    print("""
def build_system_prompt():
    prompt = []
    prompt.append(f"# 任务：{project_name}")

    # 拼接桥接点
    for bridge in bridge_definitions:
        prompt.append(f"### {bridge.name}")
        prompt.append(f"- 描述：{bridge.description}")

    # 拼接领域
    for domain in domain_definitions:
        prompt.append(f"### 领域：{domain.domain_name}")
        prompt.append(f"- 实体类型：{domain.schema.entities}")

    return "\\n".join(prompt)
    """)
    print()

    # 展示实际生成的提示词片段
    print("📝 生成的提示词片段（示例）:")
    print("-" * 80)
    print(f"# 任务：{config.get('project_name', 'N/A')}\n")
    print("## 重要：桥接点（Bridge Points）")
    print("以下是连接所有领域的公共概念，必须在每个文档中提取：\n")

    for bridge in config.get('bridge_definitions', [])[:2]:  # 只展示前2个
        print(f"### {bridge['name']} (key: {bridge['key']})")
        print(f"- 描述：{bridge['description']}")
        if bridge.get('examples'):
            print(f"- 示例：{', '.join(bridge['examples'])}")
        print()

    print("## 领域（Domains）")
    print("根据文档内容，判断其所属领域，并提取相应的实体和关系：\n")

    for i, domain in enumerate(config.get('domain_definitions', [])[:2], 1):  # 只展示前2个
        print(f"### 领域 {i}：{domain['domain_name']}")
        print(f"- 描述：{domain['description']}")
        print(f"- 触发条件：{domain['trigger_condition']}")
        print(f"- 实体类型：{', '.join(domain['schema']['entities'][:5])}")
        print(f"- 关系类型：{', '.join(domain['schema']['relations'][:5])}")
        print()

else:
    print(f"❌ 未找到 GraphConfig 文件: {config_path}")
    print()

# ============================================================================
# 对比总结
# ============================================================================
print()
print("=" * 80)
print("📊 核心区别对比")
print("=" * 80)
print()

comparison_table = """
┌──────────────────────┬─────────────────────────┬─────────────────────────┐
│       特性           │   方案A (GraphConfig)   │    方案B (YAML)         │
├──────────────────────┼─────────────────────────┼─────────────────────────┤
│ 配置文件             │ data/graph_config.json  │ config/prompts/*.yaml   │
│ 提示词生成           │ 代码动态拼接            │ 模板字符串插值          │
│ 多领域支持           │ ✅ 支持                 │ ❌ 不支持               │
│ 桥接点支持           │ ✅ 支持                 │ ❌ 不支持               │
│ Few-shot 示例        │ ❌ 硬编码在代码中       │ ✅ 配置在 YAML 中       │
│ 修改提示词           │ ❌ 需要改代码           │ ✅ 只需改 YAML          │
│ AI Copilot 集成      │ ✅ 完全集成             │ ❌ 未集成               │
│ 可读性               │ ⚠️  需要理解架构        │ ✅ YAML 直观易读        │
│ 灵活性               │ ⚠️  结构复杂            │ ✅ 简单灵活             │
│ 当前状态             │ ✅ 生产使用中           │ ❌ 未集成               │
└──────────────────────┴─────────────────────────┴─────────────────────────┘
"""

print(comparison_table)
print()

# ============================================================================
# 实际应用建议
# ============================================================================
print("=" * 80)
print("💡 实际应用建议")
print("=" * 80)
print()

print("【场景1】单一领域项目（如纯法律文档分析）")
print("  推荐: 方案B (YAML)")
print("  原因: 配置简单，易于维护，支持快速调整提示词")
print()

print("【场景2】多领域项目（如学生管理系统）")
print("  推荐: 方案A (GraphConfig)")
print("  原因: 支持动态领域路由，桥接点连接不同领域")
print()

print("【场景3】需要频繁调整提示词（A/B测试）")
print("  推荐: 方案B (YAML)")
print("  原因: 修改 YAML 文件即可，无需重启服务")
print()

print("【场景4】使用 AI Copilot 自动配置")
print("  推荐: 方案A (GraphConfig)")
print("  原因: AI Copilot 直接生成 GraphConfig")
print()

print("=" * 80)
print("🔍 当前项目使用的方案")
print("=" * 80)
print()

if config_path.exists():
    print("✅ 当前使用: 方案A (GraphConfig)")
    print(f"   配置文件: {config_path}")
else:
    print("⚠️  当前使用: 传统模式（非 GraphConfig，非 YAML）")
    print("   提示词来自: graphrag_agent/prompts/graph_prompts.py（硬编码）")

print()

if yaml_path.exists():
    print(f"📄 YAML 模板存在但未集成: {yaml_path}")
    print("   如需使用，需要修改 extractor_factory.py")
else:
    print("❌ 未找到 YAML 模板")

print()
print("=" * 80)
