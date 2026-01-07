"""
对比 DynamicPromptBuilder（GraphConfig模式）和 PromptBuilder（YAML模式）

演示两种提示词构建方式的差异
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

print("=" * 80)
print("📊 提示词构建器对比演示")
print("=" * 80)
print()

# ============================================================================
# 方案A: DynamicPromptBuilder (基于 GraphConfig)
# ============================================================================
print("🔵 方案A: DynamicPromptBuilder (基于 GraphConfig - 当前生产使用)")
print("-" * 80)

try:
    from graphrag_agent.config.graph_config_storage import get_storage
    from graphrag_agent.prompts.dynamic_prompt_builder import DynamicPromptBuilder

    storage = get_storage()
    config = storage.load()

    if config:
        builder_a = DynamicPromptBuilder(config)

        print(f"✅ 成功加载 GraphConfig")
        print(f"   项目名: {config.project_name}")
        print(f"   行业: {config.industry}")
        print(f"   桥接点数: {len(config.bridge_definitions)}")
        print(f"   领域数: {len(config.domain_definitions)}")
        print()

        # 生成系统提示词
        system_prompt_a = builder_a.build_system_prompt()

        print("📝 生成的系统提示词（前500字）:")
        print("-" * 80)
        print(system_prompt_a[:500])
        print("...")
        print()

        print(f"📏 系统提示词总长度: {len(system_prompt_a)} 字符")
        print()

        # 获取实体和关系类型
        entity_types_a = builder_a.get_all_entity_types()
        relation_types_a = builder_a.get_all_relationship_types()

        print(f"🏷️  实体类型 ({len(entity_types_a)} 种):")
        print(f"   {entity_types_a[:10]}{'...' if len(entity_types_a) > 10 else ''}")
        print()

        print(f"🔗 关系类型 ({len(relation_types_a)} 种):")
        print(f"   {relation_types_a[:10]}{'...' if len(relation_types_a) > 10 else ''}")
        print()

    else:
        print("❌ 未找到 GraphConfig 配置")
        print("   提示: 运行 AI Copilot 创建配置，或使用传统模式")
        print()

except Exception as e:
    print(f"❌ 方案A 加载失败: {e}")
    print()

# ============================================================================
# 方案B: PromptBuilder (基于 YAML)
# ============================================================================
print()
print("🟢 方案B: PromptBuilder (基于 YAML 模板 - 未集成到生产)")
print("-" * 80)

try:
    from graphrag_agent.prompts.prompt_builder import PromptBuilder

    builder_b = PromptBuilder()

    print(f"✅ 成功加载 PromptBuilder")
    print(f"   可用模板: {builder_b.list_templates()}")
    print()

    # 加载 entity_extraction 模板
    template = builder_b.load_template("entity_extraction")

    print(f"📄 模板: {template.name} (v{template.version})")
    print(f"   描述: {template.description}")
    print(f"   默认参数: {template.parameters}")
    print()

    # 使用 build_messages 构建消息列表
    messages = builder_b.build_messages(
        "entity_extraction",
        text="学生在每学期开始前需要到教务处注册课程。学生注册时需要携带学生证。",
        entity_types=["学生", "部门", "证件", "课程"],
        relation_types=["办理", "需要", "管理"],
        domain="教育"
    )

    print("📝 生成的消息列表:")
    print("-" * 80)
    for i, msg in enumerate(messages):
        print(f"\n消息 {i+1} (role={msg['role']}):")
        content = msg['content']
        if len(content) > 300:
            print(content[:300] + "...")
        else:
            print(content)

    print()
    print(f"📏 系统消息长度: {len(messages[0]['content'])} 字符")
    print(f"📏 用户消息长度: {len(messages[-1]['content'])} 字符")
    print()

except Exception as e:
    print(f"❌ 方案B 加载失败: {e}")
    import traceback
    traceback.print_exc()
    print()

# ============================================================================
# 对比总结
# ============================================================================
print()
print("=" * 80)
print("📊 对比总结")
print("=" * 80)
print()

comparison = """
┌─────────────────────┬─────────────────────────┬─────────────────────────┐
│      特性           │   方案A (GraphConfig)   │    方案B (YAML)         │
├─────────────────────┼─────────────────────────┼─────────────────────────┤
│ 配置方式            │ Python 对象 (Pydantic)  │ YAML 文件               │
│ 配置位置            │ data/graph_config.json  │ config/prompts/*.yaml   │
│ 提示词生成          │ 动态拼接（代码生成）    │ 模板插值 (str.format)   │
│ 领域支持            │ ✅ 多领域（动态路由）   │ ❌ 单领域（需手动切换） │
│ 桥接点支持          │ ✅ 支持（跨领域连接）   │ ❌ 不支持               │
│ AI Copilot 集成     │ ✅ 完全集成             │ ❌ 未集成               │
│ 版本控制            │ ✅ Git + JSON           │ ✅ Git + YAML           │
│ 可读性              │ ⚠️  需要理解 GraphConfig │ ✅ YAML 更直观          │
│ 灵活性              │ ⚠️  需要修改代码        │ ✅ 修改 YAML 即可       │
│ Few-shot 示例       │ ❌ 硬编码在代码中       │ ✅ 在 YAML 中配置       │
│ 参数验证            │ ✅ Pydantic 自动验证    │ ⚠️  需要手动验证        │
│ 缓存键生成          │ ⚠️  基于 GraphConfig    │ ✅ MD5 哈希（模板版本） │
│ 当前状态            │ ✅ 生产使用中           │ ❌ 未集成到生产         │
└─────────────────────┴─────────────────────────┴─────────────────────────┘

🎯 主要区别:

1. **配置来源不同**:
   - 方案A: GraphConfig (AI Copilot 生成，存储在 data/graph_config.json)
   - 方案B: YAML 模板 (手动编写，存储在 config/prompts/*.yaml)

2. **提示词生成逻辑不同**:
   - 方案A: 通过代码动态拼接（DynamicPromptBuilder.build_system_prompt()）
   - 方案B: 通过模板变量插值（template.format(**params)）

3. **适用场景不同**:
   - 方案A: 适合多领域、复杂业务场景（如教育管理系统）
   - 方案B: 适合单一领域、快速迭代场景（如纯法律文档分析）

4. **维护成本不同**:
   - 方案A: 修改提示词需要改代码（DynamicPromptBuilder.py）
   - 方案B: 修改提示词只需改 YAML 文件（无需重启服务）

💡 推荐使用场景:

- **方案A (GraphConfig)**:
  ✅ 如果你的项目有多个业务领域（规则库、事实库、关系库等）
  ✅ 如果你需要跨领域的桥接点连接
  ✅ 如果你想使用 AI Copilot 自动生成配置

- **方案B (YAML)**:
  ✅ 如果你的项目只有单一领域
  ✅ 如果你希望提示词配置更易读、易维护
  ✅ 如果你需要频繁调整提示词（A/B测试）

"""

print(comparison)

print()
print("=" * 80)
print("🔍 如何验证当前使用的方案?")
print("=" * 80)
print()
print("运行知识图谱构建时，查看日志输出:")
print()
print("  如果看到: '✨ 检测到通用图谱配置，使用动态提示词生成'")
print("  → 说明使用的是 方案A (GraphConfig)")
print()
print("  如果看到: '📝 使用传统配置模式'")
print("  → 说明使用的是 传统模式（既不是A也不是B，而是直接传入的模板）")
print()
print("方案B (YAML) 目前 **没有集成到生产代码**，需要手动修改代码才能使用。")
print()
