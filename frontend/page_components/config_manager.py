"""
配置管理页面（通用图谱构建器）
支持用户定义领域（Domain）和桥接点（Bridge）

增强功能：
- 配置校验反馈
- JSON 源码编辑模式
- 状态同步提示
"""

import json
from typing import Dict, List, Optional

import requests
import streamlit as st

from frontend.frontend_config.settings import API_URL
from frontend.utils.config_repository_api import (
    list_all_configs,
    get_config_detail,
    create_config,
    update_config,
    delete_config,
    set_default_config,
    duplicate_config,
)


def validate_config(config: Dict) -> tuple[bool, Optional[str]]:
    """
    校验配置格式（前端快速校验）

    Returns:
        (is_valid, error_message)
    """
    try:
        # 必需字段
        required_fields = ["project_name", "version", "domain_definitions", "bridge_definitions"]
        for field in required_fields:
            if field not in config:
                return False, f"缺少必需字段: {field}"

        # 项目名称不能为空
        if not config["project_name"]:
            return False, "项目名称不能为空"

        # 检查领域定义
        for idx, domain in enumerate(config.get("domain_definitions", [])):
            if "domain_name" not in domain:
                return False, f"领域 #{idx+1} 缺少 domain_name 字段"
            if "schema" not in domain:
                return False, f"领域 '{domain['domain_name']}' 缺少 schema 字段"

            schema = domain["schema"]
            if "entities" not in schema or "relations" not in schema:
                return False, f"领域 '{domain['domain_name']}' 的 schema 必须包含 entities 和 relations"

        # 检查桥接点定义
        bridge_keys = set()
        for idx, bridge in enumerate(config.get("bridge_definitions", [])):
            if "key" not in bridge:
                return False, f"桥接点 #{idx+1} 缺少 key 字段"

            if bridge["key"] in bridge_keys:
                return False, f"桥接点 key '{bridge['key']}' 重复"
            bridge_keys.add(bridge["key"])

        return True, None

    except Exception as e:
        return False, f"校验异常: {str(e)}"


def fetch_graph_config() -> Optional[Dict]:
    """获取当前图谱配置"""
    try:
        response = requests.get(f"{API_URL}/admin/graph/config")
        response.raise_for_status()
        data = response.json()
        return data.get("config") if data.get("exists") else None
    except Exception as e:
        st.error(f"获取配置失败: {e}")
        return None


def save_graph_config(config: Dict, show_feedback: bool = True) -> tuple[bool, Optional[Dict]]:
    """
    保存图谱配置（增强版：包含校验和详细反馈）

    Args:
        config: 配置字典
        show_feedback: 是否显示 Streamlit 反馈消息

    Returns:
        (success, response_data)
    """
    # 1. 前端快速校验
    is_valid, error_msg = validate_config(config)
    if not is_valid:
        if show_feedback:
            st.error(f"❌ 配置校验失败: {error_msg}")
        return False, None

    # 2. 发送到后端
    try:
        response = requests.post(f"{API_URL}/admin/graph/config", json=config, timeout=10)
        response.raise_for_status()
        data = response.json()

        if show_feedback:
            st.success("✅ 配置保存成功！")

            # 显示缓存状态
            cache_status = data.get("cache_status", {})
            if cache_status:
                with st.expander("🔍 查看缓存状态", expanded=False):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("缓存状态", "已刷新" if cache_status.get("has_cache") else "空")
                    with col2:
                        st.metric("领域数量", cache_status.get("domain_count", 0))
                    with col3:
                        st.metric("桥接点数量", cache_status.get("bridge_count", 0))

            # 提示用户下一步操作
            st.info("💡 **下一步**: 前往「🏗️ 构建管理」重新构建知识图谱以应用新配置")
            st.caption("⚡ 配置已热更新到内存，无需重启服务")

        return True, data

    except requests.exceptions.Timeout:
        if show_feedback:
            st.error("❌ 保存超时，请检查后端服务状态")
        return False, None
    except requests.exceptions.HTTPError as e:
        error_detail = "未知错误"
        try:
            error_detail = e.response.json().get("detail", str(e))
        except:
            error_detail = str(e)

        if show_feedback:
            st.error(f"❌ 保存失败: {error_detail}")
        return False, None
    except Exception as e:
        if show_feedback:
            st.error(f"❌ 保存配置失败: {str(e)}")
        return False, None


def fetch_templates() -> Dict:
    """获取所有模板"""
    try:
        response = requests.get(f"{API_URL}/admin/graph/templates")
        response.raise_for_status()
        return response.json().get("templates", {})
    except Exception as e:
        st.error(f"获取模板失败: {e}")
        return {}


def fetch_template_detail(template_name: str) -> Optional[Dict]:
    """获取模板详情"""
    try:
        response = requests.get(f"{API_URL}/admin/graph/templates/{template_name}")
        response.raise_for_status()
        return response.json().get("config")
    except Exception as e:
        st.error(f"获取模板详情失败: {e}")
        return None


def load_template(template_name: str, project_name: Optional[str] = None) -> bool:
    """从模板加载配置"""
    try:
        params = {"template_name": template_name}
        if project_name:
            params["project_name"] = project_name

        response = requests.post(f"{API_URL}/admin/graph/config/from-template", params=params)
        response.raise_for_status()
        return True
    except Exception as e:
        st.error(f"加载模板失败: {e}")
        return False


def check_config_modified(working_config: Dict, saved_config: Optional[Dict]) -> bool:
    """检查配置是否被修改（未保存）"""
    if saved_config is None:
        return True  # 没有保存的配置，算作有修改

    # 简单比较：转为JSON字符串比较
    import json
    working_str = json.dumps(working_config, sort_keys=True)
    saved_str = json.dumps(saved_config, sort_keys=True)
    return working_str != saved_str


def render_save_button(working_config: Dict) -> bool:
    """
    渲染统一的保存按钮（每个tab底部都会调用）

    Returns:
        True if saved successfully, False otherwise
    """
    st.markdown("---")
    col1, col2, col3 = st.columns([2, 1, 2])

    with col2:
        if st.button("💾 保存配置", type="primary", use_container_width=True, key=f"save_btn_{st.session_state.get('active_tab', 'default')}"):
            # 🔥 使用新的保存函数（配置仓库API）
            if "save_current_config" in st.session_state:
                success = st.session_state.save_current_config()
                if success:
                    st.success("✅ 配置已保存")
                    st.rerun()
                    return True
                return False
            else:
                # 兼容旧逻辑（如果save_current_config不存在）
                success, _ = save_graph_config(working_config, show_feedback=True)
                if success:
                    st.session_state.saved_config_snapshot = working_config.copy()
                    st.session_state.config_reload_trigger = True
                    st.rerun()
                    return True
                return False
    return False


def render_template_selector(is_create_mode: bool = False):
    """
    渲染模板选择器

    Args:
        is_create_mode: 是否为创建模式（True=创建新配置，False=覆盖当前配置）
    """
    st.subheader("📋 选择预置行业模板")
    st.caption(f"系统内置 3 个行业模板（法务、电商、医疗），可作为配置的起点")

    templates = fetch_templates()

    if not templates:
        st.warning("暂无可用模板")
        return

    st.info(f"💡 共 {len(templates)} 个预置模板可用")

    # 显示模板卡片
    cols = st.columns(3)

    for idx, (template_key, template_info) in enumerate(templates.items()):
        with cols[idx % 3]:
            st.markdown(f"### {template_info['project_name']}")
            st.caption(f"行业：{template_info.get('industry', '未知')}")
            st.write(template_info.get("description", ""))
            st.caption(f"🔗 {template_info['bridge_count']} 个桥接点")
            st.caption(f"📦 {template_info['domain_count']} 个领域")

            button_label = "📥 使用此模板" if is_create_mode else "📥 加载"
            if st.button(button_label, key=f"load_{template_key}_{'create' if is_create_mode else 'edit'}"):
                with st.spinner("正在加载模板..."):
                    template_config = fetch_template_detail(template_key)
                    if template_config:
                        if is_create_mode:
                            # 创建模式：提示输入配置名称
                            config_name = st.text_input(
                                "配置名称*",
                                value=f"{template_info['project_name']}",
                                key=f"name_for_{template_key}"
                            )
                            if config_name:
                                success, config_id, error = create_config(
                                    template_config,
                                    config_name,
                                    template_info.get('description'),
                                    set_as_default=False
                                )
                                if success:
                                    st.success(f"✅ 配置已创建: {config_name}")
                                    st.session_state.selected_config_id = config_id
                                    st.rerun()
                                else:
                                    st.error(error)
                        else:
                            # 编辑模式：覆盖当前配置
                            st.session_state.current_config = template_config
                            st.success(f"✅ 模板 '{template_info['project_name']}' 已加载到当前配置")
                            st.info("💡 请点击下方「💾 保存配置」按钮保存修改")
                            st.rerun()

            if st.button(f"👁️ 预览", key=f"preview_{template_key}"):
                st.session_state.preview_template = template_key


def render_template_tab(config: Dict):
    """渲染模板加载标签页"""
    st.subheader("📋 加载预置行业模板")
    st.info("💡 这里提供 3 个预置的行业模板作为快速起点，适合首次使用或重新开始项目时使用")
    st.warning("⚠️ **重要提示**：加载模板会**完全覆盖**你当前的所有配置（包括桥接点和领域）！")

    # 添加确认开关
    confirm_load = st.checkbox("我已了解风险，允许覆盖当前配置", key="confirm_template_load")

    if confirm_load:
        render_template_selector()
    else:
        st.info("👆 请先勾选上方确认框，才能加载模板")

    # 渲染保存按钮
    render_save_button(config)


def render_project_info_tab(config: Dict):
    """渲染项目信息编辑标签页"""
    st.subheader("💼 项目信息")
    st.caption("修改项目的元数据信息")

    # 修改项目信息
    project_name = st.text_input("项目名称", value=config.get("project_name", ""), key="edit_project_name")
    industry = st.text_input("所属行业", value=config.get("industry", ""), key="edit_industry")
    description = st.text_area("项目描述", value=config.get("description", ""), key="edit_description")

    # 更新配置
    config["project_name"] = project_name
    config["industry"] = industry
    config["description"] = description

    st.markdown("---")

    # 🔥 分块配置
    st.subheader("✂️ 分块配置")
    st.caption("配置文档分块策略，控制文本如何被切分为小段落")

    # 分块策略选择
    chunking_strategy = st.selectbox(
        "分块策略",
        options=["simple", "adaptive", "semantic", "custom"],
        index=["simple", "adaptive", "semantic", "custom"].index(config.get("chunking_strategy", "simple")),
        format_func=lambda x: {
            "simple": "简单分词 - 基于固定字符数切分",
            "adaptive": "自适应 - 根据内容动态调整块大小",
            "semantic": "语义分块 - 按句子/段落语义切分",
            "custom": "自定义 - 使用自定义分隔符"
        }[x],
        key="edit_chunking_strategy",
        help="选择分块策略会影响知识图谱的构建质量和检索性能"
    )

    col1, col2 = st.columns(2)

    with col1:
        chunk_size = st.number_input(
            "分块大小（字符数）",
            min_value=100,
            max_value=5000,
            value=config.get("chunk_size", 500),
            step=50,
            key="edit_chunk_size",
            help="每个文本块的最大字符数。较大的块包含更多上下文，较小的块更精确"
        )

    with col2:
        chunk_overlap = st.number_input(
            "分块重叠（字符数）",
            min_value=0,
            max_value=1000,
            value=config.get("chunk_overlap", 100),
            step=20,
            key="edit_chunk_overlap",
            help="相邻块之间的重叠字符数。重叠可以避免重要信息被切断"
        )

    # 自定义分隔符（仅在custom策略时显示）
    custom_separators = None
    if chunking_strategy == "custom":
        st.markdown("**自定义分隔符**")
        separators_input = st.text_input(
            "分隔符列表（逗号分隔）",
            value=",".join(config.get("custom_separators", [])) if config.get("custom_separators") else "\\n\\n,。,！,？",
            key="edit_custom_separators",
            help="使用逗号分隔多个分隔符，例如：\\n\\n,。,！,？"
        )
        if separators_input:
            custom_separators = [s.strip() for s in separators_input.split(",")]

    # 更新配置
    config["chunking_strategy"] = chunking_strategy
    config["chunk_size"] = chunk_size
    config["chunk_overlap"] = chunk_overlap
    if custom_separators is not None:
        config["custom_separators"] = custom_separators

    # 显示分块策略说明
    with st.expander("📖 分块策略说明", expanded=False):
        st.markdown("""
        ### 分块策略对比

        **🔹 Simple（简单分词）**
        - 基于固定字符数进行切分
        - 速度最快，适合大多数场景
        - 可能会在词语中间切断

        **🔹 Adaptive（自适应）**
        - 根据文档结构动态调整块大小
        - 保留文档的自然段落边界
        - 平衡速度和质量

        **🔹 Semantic（语义分块）**
        - 按句子和段落语义进行切分
        - 保证每个块语义完整
        - 质量最高，但速度较慢

        **🔹 Custom（自定义）**
        - 使用用户指定的分隔符
        - 适合特定格式的文档
        - 需要熟悉文档结构

        ### 参数建议

        **📊 知识图谱构建**（推荐）
        - chunk_size: 1000
        - chunk_overlap: 50
        - 策略: simple 或 adaptive

        **🔍 向量检索**（精确搜索）
        - chunk_size: 400
        - chunk_overlap: 80
        - 策略: semantic 或 simple

        ⚠️ **注意**：修改分块配置后需要重新构建知识图谱才能生效
        """)

    # 渲染保存按钮
    render_save_button(config)


def render_export_tab(config: Dict):
    """渲染导出配置标签页"""
    st.subheader("📥 导出配置")
    st.caption("将当前配置导出为 JSON 文件，作为备份或分享给他人")

    # 显示配置摘要
    st.markdown("### 当前配置摘要")
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**项目名称**: {config.get('project_name', 'N/A')}")
        st.info(f"**所属行业**: {config.get('industry', 'N/A')}")
    with col2:
        bridge_count = len(config.get("bridge_definitions", []))
        domain_count = len(config.get("domain_definitions", []))
        st.info(f"**桥接点数量**: {bridge_count}")
        st.info(f"**领域数量**: {domain_count}")

    st.markdown("---")

    # 导出按钮
    config_json = json.dumps(config, ensure_ascii=False, indent=2)
    st.download_button(
        label="📥 导出配置文件 (JSON)",
        data=config_json,
        file_name=f"{config.get('project_name', 'graph_config')}.json",
        mime="application/json",
        use_container_width=True,
        type="primary",
    )

    st.markdown("---")
    st.info("💡 导出的配置文件可以在其他项目中导入使用")
    st.caption("⚠️ 注意：导出功能不需要保存，它会导出当前编辑状态的配置")


def render_bridge_editor(config: Dict):
    """渲染桥接点编辑器"""
    st.subheader("🔗 桥接点配置")
    st.caption("桥接点是连接所有领域的公共概念，如'问题类型'、'风险等级'等")

    bridges = config.get("bridge_definitions", [])

    # 显示现有桥接点
    if bridges:
        for idx, bridge in enumerate(bridges):
            with st.expander(f"🔗 {bridge['name']} ({bridge['key']})", expanded=False):
                col1, col2 = st.columns([4, 1])

                with col1:
                    st.text_input("名称", value=bridge["name"], key=f"bridge_name_{idx}", disabled=True)
                    st.text_area(
                        "描述", value=bridge["description"], key=f"bridge_desc_{idx}", height=80, disabled=True
                    )

                    if bridge.get("examples"):
                        st.caption(f"示例：{', '.join(bridge['examples'])}")

                    if bridge.get("is_enum_restricted") and bridge.get("enum_values"):
                        st.caption(f"枚举值：{', '.join(bridge['enum_values'])}")

                with col2:
                    if st.button("🗑️", key=f"del_bridge_{idx}", help="删除此桥接点"):
                        deleted_name = bridges[idx].get("name", "未命名")
                        bridges.pop(idx)
                        config["bridge_definitions"] = bridges
                        st.success(f"✅ 桥接点 '{deleted_name}' 已删除")
                        st.info("💡 请点击下方「💾 保存配置」按钮保存修改")
                        st.rerun()
    else:
        st.info("暂无桥接点，点击下方按钮添加")

    # 添加新桥接点
    st.markdown("---")
    with st.expander("➕ 添加新桥接点", expanded=False):
        bridge_name = st.text_input("桥接点名称", placeholder="例如：问题类型")
        bridge_key = st.text_input("桥接点 Key", placeholder="例如：bridge_issue_type")
        bridge_desc = st.text_area("描述", placeholder="例如：连接所有文档的核心问题分类")
        bridge_examples = st.text_input("示例（逗号分隔）", placeholder="例如：投诉,咨询,建议")

        is_enum = st.checkbox("限制为枚举值")
        enum_values = ""
        if is_enum:
            enum_values = st.text_input("枚举值（逗号分隔）", placeholder="例如：投诉,咨询,建议,举报")

        if st.button("✅ 添加桥接点"):
            if not bridge_name or not bridge_key:
                st.error("名称和 Key 不能为空")
            else:
                new_bridge = {
                    "name": bridge_name,
                    "key": bridge_key,
                    "description": bridge_desc,
                    "examples": [e.strip() for e in bridge_examples.split(",")] if bridge_examples else [],
                    "is_enum_restricted": is_enum,
                    "enum_values": [e.strip() for e in enum_values.split(",")] if is_enum and enum_values else None,
                }
                bridges.append(new_bridge)
                config["bridge_definitions"] = bridges
                st.success(f"✅ 桥接点 '{bridge_name}' 已添加")
                st.info("💡 请点击下方「💾 保存配置」按钮保存修改")
                st.rerun()

    # 渲染保存按钮
    render_save_button(config)


def render_domain_editor(config: Dict):
    """渲染领域编辑器"""
    st.subheader("📦 领域配置")
    st.caption("领域是业务子图，定义特定业务场景下的实体和关系")

    domains = config.get("domain_definitions", [])
    bridges = config.get("bridge_definitions", [])

    # 显示现有领域
    if domains:
        for idx, domain in enumerate(domains):
            with st.expander(f"📦 {domain['domain_name']}", expanded=False):
                col1, col2 = st.columns([4, 1])

                with col1:
                    st.text_input("领域名称", value=domain["domain_name"], key=f"domain_name_{idx}", disabled=True)
                    st.text_area(
                        "描述", value=domain["description"], key=f"domain_desc_{idx}", height=80, disabled=True
                    )
                    st.text_area(
                        "触发条件",
                        value=domain["trigger_condition"],
                        key=f"domain_trigger_{idx}",
                        height=80,
                        disabled=True,
                    )

                    # 显示 Schema
                    schema = domain.get("schema", {})
                    st.caption(f"实体类型：{', '.join(schema.get('entities', []))}")
                    st.caption(f"关系类型：{', '.join(schema.get('relations', []))}")

                    # 显示桥接点映射
                    mappings = domain.get("bridge_mappings", [])
                    if mappings:
                        st.caption("桥接点映射：")
                        for mapping in mappings:
                            st.caption(f"  - {mapping['bridge_key']} → {mapping['role']}")

                with col2:
                    if st.button("🗑️", key=f"del_domain_{idx}", help="删除此领域"):
                        deleted_name = domains[idx].get("domain_name", "未命名")
                        domains.pop(idx)
                        config["domain_definitions"] = domains
                        st.success(f"✅ 领域 '{deleted_name}' 已删除")
                        st.info("💡 请点击下方「💾 保存配置」按钮保存修改")
                        st.rerun()
    else:
        st.info("暂无领域，点击下方按钮添加")

    # 添加新领域
    st.markdown("---")
    with st.expander("➕ 添加新领域", expanded=False):
        domain_name = st.text_input("领域名称", placeholder="例如：规则库")
        domain_desc = st.text_area("描述", placeholder="例如：法律法规、政策文件、规章制度")
        domain_trigger = st.text_area("触发条件", placeholder="例如：文档包含法律条款、政策规定、规章制度")

        st.markdown("**领域 Schema**")
        entities_input = st.text_input("实体类型（逗号分隔）", placeholder="例如：法条,政策,条款,部门")
        relations_input = st.text_input("关系类型（逗号分隔）", placeholder="例如：规定,依据,负责,管辖")

        # 桥接点映射
        st.markdown("**桥接点映射**")
        if bridges:
            selected_bridges = st.multiselect(
                "选择要映射的桥接点",
                options=[b["key"] for b in bridges],
                format_func=lambda key: next((b["name"] for b in bridges if b["key"] == key), key),
            )

            bridge_roles = {}
            for bridge_key in selected_bridges:
                bridge_name = next((b["name"] for b in bridges if b["key"] == bridge_key), bridge_key)
                role = st.text_input(f"{bridge_name} 的角色", placeholder="例如：适用场景", key=f"role_{bridge_key}")
                bridge_roles[bridge_key] = role
        else:
            st.warning("请先添加桥接点")
            selected_bridges = []
            bridge_roles = {}

        if st.button("✅ 添加领域"):
            if not domain_name:
                st.error("领域名称不能为空")
            else:
                new_domain = {
                    "domain_name": domain_name,
                    "description": domain_desc,
                    "trigger_condition": domain_trigger,
                    "schema": {
                        "entities": [e.strip() for e in entities_input.split(",")] if entities_input else [],
                        "relations": [r.strip() for r in relations_input.split(",")] if relations_input else [],
                    },
                    "bridge_mappings": [
                        {"bridge_key": bridge_key, "role": bridge_roles.get(bridge_key, ""), "field_name": None}
                        for bridge_key in selected_bridges
                    ],
                }
                domains.append(new_domain)
                config["domain_definitions"] = domains
                st.success(f"✅ 领域 '{domain_name}' 已添加")
                st.info("💡 请点击下方「💾 保存配置」按钮保存修改")
                st.rerun()

    # 渲染保存按钮
    render_save_button(config)


def render_config_overview(config: Dict, has_unsaved_changes: bool = False):
    """渲染配置概览"""
    st.subheader("📊 当前配置概览")

    # 显示保存状态
    if has_unsaved_changes:
        st.warning("⚠️ 有未保存的修改 - 请点击任意 Tab 底部的「💾 保存配置」按钮")
    else:
        st.success("✅ 所有修改已保存（重新构建知识图谱后应用）")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("项目名称", config.get("project_name", "N/A"))

    with col2:
        st.metric("行业", config.get("industry", "N/A"))

    with col3:
        bridge_count = len(config.get("bridge_definitions", []))
        st.metric("桥接点数量", bridge_count)

    with col4:
        domain_count = len(config.get("domain_definitions", []))
        st.metric("领域数量", domain_count)

    if config.get("description"):
        st.info(f"📝 {config['description']}")


def render_json_editor(config: Dict) -> Optional[Dict]:
    """
    渲染 JSON 源码编辑器（高级用户模式）

    Returns:
        updated_config if user updated, else None
    """
    st.subheader("📝 JSON 源码编辑")
    st.caption("⚠️ 高级模式：直接编辑配置 JSON，需要熟悉配置格式")

    # 将字典转为 JSON 字符串供编辑器使用
    config_str = json.dumps(config, indent=2, ensure_ascii=False)

    # 使用 text_area 让用户编辑
    new_config_str = st.text_area(
        "配置 JSON", value=config_str, height=600, help="直接编辑配置的 JSON 表示。修改后点击「校验并应用」按钮。"
    )

    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        if st.button("✅ 校验并应用", type="primary", use_container_width=True):
            try:
                # 解析 JSON
                new_config = json.loads(new_config_str)

                # 校验配置
                is_valid, error_msg = validate_config(new_config)
                if not is_valid:
                    st.error(f"❌ 配置校验失败: {error_msg}")
                    return None

                # 更新 session state
                st.success("✅ JSON 格式校验通过！")
                st.info("💡 配置已更新到当前编辑状态，请点击下方「💾 保存配置」按钮保存")

                return new_config

            except json.JSONDecodeError as e:
                st.error(f"❌ JSON 格式错误: {str(e)}")
                st.code(new_config_str[max(0, e.pos - 50) : e.pos + 50], language="json")
                return None

    with col2:
        # 格式化按钮
        if st.button("🔧 格式化 JSON", use_container_width=True):
            try:
                formatted = json.dumps(json.loads(new_config_str), indent=2, ensure_ascii=False)
                st.code(formatted, language="json")
                st.caption("复制上面的格式化结果到编辑器中")
            except json.JSONDecodeError as e:
                st.error(f"❌ JSON 格式错误，无法格式化: {str(e)}")

    with col3:
        # 重置按钮
        if st.button("🔄 重置", use_container_width=True):
            st.rerun()

    # 显示 Diff 预览
    with st.expander("👀 查看变更 (Diff)", expanded=False):
        try:
            new_config_parsed = json.loads(new_config_str)

            # 简单的 diff 显示
            original_keys = set(config.keys())
            new_keys = set(new_config_parsed.keys())

            added_keys = new_keys - original_keys
            removed_keys = original_keys - new_keys
            common_keys = original_keys & new_keys

            if added_keys:
                st.success(f"➕ 新增字段: {', '.join(added_keys)}")
            if removed_keys:
                st.error(f"➖ 删除字段: {', '.join(removed_keys)}")

            changed_keys = []
            for key in common_keys:
                if config.get(key) != new_config_parsed.get(key):
                    changed_keys.append(key)

            if changed_keys:
                st.warning(f"📝 修改字段: {', '.join(changed_keys)}")

            if not added_keys and not removed_keys and not changed_keys:
                st.info("无变更")

        except:
            st.caption("无法解析 JSON 进行 Diff 比较")

    # 渲染保存按钮
    render_save_button(config)

    return None


def render_config_list_selector():
    """
    渲染配置列表选择器（侧边栏）

    Returns:
        selected_config_id: 选中的配置ID，None表示创建新配置
    """
    with st.sidebar:
        st.markdown("### 📂 我的配置")

        # 获取配置列表
        success, configs, error = list_all_configs()

        if not success:
            st.error(f"获取配置列表失败: {error}")
            return None

        if not configs:
            st.info("暂无配置，请创建新配置")
            if st.button("➕ 创建新配置", use_container_width=True, type="primary"):
                st.session_state.selected_config_id = "new"
                st.rerun()
            return "new"

        # 配置列表
        for idx, config_meta in enumerate(configs):
            config_id = config_meta["id"]
            name = config_meta["name"]
            is_default = config_meta.get("is_default", False)
            updated_at = config_meta.get("updated_at", "")

            # 默认配置标记
            name_display = f"⭐ {name}" if is_default else name

            # 按钮选择配置
            col1, col2 = st.columns([4, 1])
            with col1:
                if st.button(
                    name_display,
                    key=f"select_{config_id}",
                    use_container_width=True,
                    type="primary" if st.session_state.get("selected_config_id") == config_id else "secondary",
                ):
                    st.session_state.selected_config_id = config_id
                    st.session_state.config_reload_trigger = True
                    st.rerun()

            with col2:
                # 删除按钮
                if st.button("🗑️", key=f"delete_{config_id}", help="删除此配置"):
                    if is_default and len(configs) > 1:
                        st.error("无法删除默认配置，请先设置其他配置为默认")
                    else:
                        success_del, error_del = delete_config(config_id)
                        if success_del:
                            st.success(f"已删除配置: {name}")
                            if st.session_state.get("selected_config_id") == config_id:
                                st.session_state.selected_config_id = None
                            st.rerun()
                        else:
                            st.error(error_del)

            # 显示更新时间
            if updated_at:
                try:
                    from datetime import datetime
                    updated_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    st.caption(f"更新于: {updated_dt.strftime('%Y-%m-%d %H:%M')}")
                except:
                    st.caption(f"更新于: {updated_at[:16]}")

        st.markdown("---")

        # 新建配置按钮
        if st.button("➕ 创建新配置", use_container_width=True, type="primary"):
            st.session_state.selected_config_id = "new"
            st.session_state.config_reload_trigger = True
            st.rerun()

        # 返回选中的配置ID
        return st.session_state.get("selected_config_id")


def render_create_config_form():
    """渲染创建配置表单"""
    st.title("➕ 创建新配置")
    st.markdown("---")

    st.info("💡 您可以从空白配置开始，或加载预置的行业模板")

    # Tab选择：空白配置 vs 加载模板
    tab1, tab2 = st.tabs(["🆕 空白配置", "📋 从模板创建"])

    with tab1:
        st.subheader("创建空白配置")
        name = st.text_input("配置名称*", placeholder="例如：学生管理系统 - 生产版")
        description = st.text_area("配置描述", placeholder="简要描述此配置的用途")
        set_as_default = st.checkbox("设为默认配置", value=False)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 创建空白配置", use_container_width=True, type="primary"):
                if not name:
                    st.error("配置名称不能为空")
                else:
                    # 创建空白配置
                    blank_config = {
                        "project_name": name,
                        "version": "1.0",
                        "description": description or "",
                        "industry": "",
                        "bridge_definitions": [],
                        "domain_definitions": [],
                    }

                    success, config_id, error = create_config(blank_config, name, description, set_as_default)
                    if success:
                        st.success(f"✅ 配置已创建: {name}")
                        st.session_state.selected_config_id = config_id
                        st.session_state.config_reload_trigger = True
                        st.rerun()
                    else:
                        st.error(error)

        with col2:
            if st.button("❌ 取消", use_container_width=True):
                st.session_state.selected_config_id = None
                st.rerun()

    with tab2:
        st.subheader("从模板创建")
        render_template_selector(is_create_mode=True)


def config_manager_page():
    """配置管理主页面（支持多配置管理）"""
    st.title("⚙️ 图谱配置管理")
    st.markdown("---")

    # 🔥 渲染配置列表选择器（侧边栏）
    selected_config_id = render_config_list_selector()

    # 如果选中"创建新配置"
    if selected_config_id == "new":
        render_create_config_form()
        return

    # 如果没有选中任何配置
    if not selected_config_id:
        st.info("👈 请在左侧选择一个配置进行编辑，或创建新配置")
        return

    # 🔥 加载选中的配置
    success, config, metadata, error = get_config_detail(selected_config_id)

    if not success:
        st.error(f"加载配置失败: {error}")
        return

    if not config:
        st.error("配置内容为空")
        return

    # 🔥 显示当前配置名称和元数据
    st.subheader(f"正在编辑: {metadata.get('name', '未命名配置')}")
    if metadata.get('description'):
        st.caption(f"📝 {metadata['description']}")
    if metadata.get('is_default'):
        st.success("⭐ 这是默认配置")

    # 🔥 配置操作按钮
    col1, col2, col3 = st.columns(3)
    with col1:
        if not metadata.get('is_default'):
            if st.button("⭐ 设为默认", use_container_width=True):
                success_default, error_default = set_default_config(selected_config_id)
                if success_default:
                    st.success("已设为默认配置")
                    st.rerun()
                else:
                    st.error(error_default)
    with col2:
        if st.button("📋 复制配置", use_container_width=True):
            new_name = f"{metadata['name']} - 副本"
            success_dup, new_id, error_dup = duplicate_config(selected_config_id, new_name)
            if success_dup:
                st.success(f"已复制配置: {new_name}")
                st.session_state.selected_config_id = new_id
                st.rerun()
            else:
                st.error(error_dup)

    st.markdown("---")

    # 🔥 使用 session state 管理配置（支持 JSON 编辑器更新）
    if "current_config" not in st.session_state or st.session_state.get("config_reload_trigger"):
        st.session_state.current_config = config.copy()
        # 同时初始化saved_config_snapshot
        if "saved_config_snapshot" not in st.session_state:
            st.session_state.saved_config_snapshot = config.copy()
        if "config_reload_trigger" in st.session_state:
            del st.session_state.config_reload_trigger

    working_config = st.session_state.current_config

    # 🔥 保存时使用配置仓库API而不是旧的save_graph_config
    def save_current_config():
        """保存当前配置到配置仓库"""
        success, error = update_config(
            selected_config_id,
            working_config,
            name=metadata.get('name'),
            description=metadata.get('description')
        )
        if success:
            st.session_state.saved_config_snapshot = working_config.copy()
            st.session_state.config_reload_trigger = True
            return True
        else:
            st.error(error)
            return False

    # 将保存函数存储到session_state供Tab使用
    st.session_state.save_current_config = save_current_config

    # 检查是否有未保存的修改
    saved_config = st.session_state.get("saved_config_snapshot")
    has_unsaved_changes = check_config_modified(working_config, saved_config)

    # 显示配置概览（带保存状态）
    render_config_overview(working_config, has_unsaved_changes)

    # 🔥 添加快速操作指南
    with st.expander("📖 使用指南（首次使用请阅读）", expanded=False):
        st.markdown("""
        ### 配置管理工作流程

        **1️⃣ 选择起点（二选一）：**
        - **方式A：从模板开始** → 点击 "📋 加载行业模板" 标签，选择一个行业模板作为基础
        - **方式B：从头开始** → 直接在 "🔗 桥接点配置" 和 "📦 领域配置" 标签中创建自定义配置

        **2️⃣ 编辑配置：**
        - 在 "🔗 桥接点配置" 标签添加桥接点（连接所有领域的公共概念）
        - 在 "📦 领域配置" 标签添加领域（不同类型文档的专属 schema）
        - ⚠️ **编辑后需要保存**：点击任意 Tab 底部的「💾 保存配置」按钮

        **3️⃣ 高级编辑（可选）：**
        - "📝 JSON 编辑器" 标签可直接编辑完整配置
        - "💼 项目信息" 标签可更新项目名称、描述等元数据

        **4️⃣ 导出配置（可选）：**
        - 在 "📥 导出配置" 标签可导出为 JSON 文件备份

        **5️⃣ 应用配置：**
        - 保存配置后，前往「🏗️ 构建管理」页面
        - 在下拉框选择"当前配置"
        - 点击"完整构建"或"增量构建"应用新配置

        ---

        ### 常见问题

        **❓ 我的配置什么时候会保存？**
        - 任何添加/删除/修改操作后，点击Tab底部的「💾 保存配置」按钮才会保存

        **❓ "加载行业模板" 会覆盖我的配置吗？**
        - 是的！加载模板会替换当前所有配置，建议先导出备份

        **❓ 如何应用我保存的配置到构建？**
        - 保存后，去「🏗️ 构建管理」页面，选择"当前配置"，然后点击构建
        """)

    st.markdown("---")

    # 🔥 创建标签页（6个tab，拆分项目信息和导出）
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        ["🔗 桥接点配置", "📦 领域配置", "📝 JSON 编辑器", "📋 加载行业模板", "💼 项目信息", "📥 导出配置"]
    )

    with tab1:
        st.session_state.active_tab = "tab1"
        render_bridge_editor(working_config)

    with tab2:
        st.session_state.active_tab = "tab2"
        render_domain_editor(working_config)

    with tab3:
        st.session_state.active_tab = "tab3"
        # 🔥 JSON 源码编辑模式
        updated_config = render_json_editor(working_config)
        if updated_config:
            st.session_state.current_config = updated_config
            st.rerun()

    with tab4:
        st.session_state.active_tab = "tab4"
        render_template_tab(working_config)

    with tab5:
        st.session_state.active_tab = "tab5"
        render_project_info_tab(working_config)

    with tab6:
        st.session_state.active_tab = "tab6"
        render_export_tab(working_config)

    # 预览模板
    if st.session_state.get("preview_template"):
        template_key = st.session_state.preview_template
        template_config = fetch_template_detail(template_key)

        if template_config:
            with st.expander(f"👁️ 模板预览：{template_config.get('project_name')}", expanded=True):
                st.json(template_config)

                if st.button("关闭预览"):
                    del st.session_state.preview_template
                    st.rerun()

    # 帮助信息
    with st.expander("❓ 详细说明"):
        st.markdown(
            """
        ### 什么是通用图谱构建器？

        传统的 GraphRAG 需要预先定义实体类型和关系类型。通用图谱构建器允许你：
        - 定义**桥接点（Bridge）**：跨领域的公共概念
        - 定义**领域（Domain）**：特定业务场景的子图
        - 使用行业模板快速开始

        ### 桥接点 (Bridge)
        - 连接不同领域的公共概念
        - 例如："问题类型"可以连接"规则库"和"案件库"
        - 可以设置为枚举值以限制取值范围
        - 示例：问题类型、风险等级、优先级

        ### 领域 (Domain)
        - 定义业务子图，如"规则库"、"案件库"、"经验库"
        - 每个领域有自己的实体类型和关系类型
        - 通过桥接点映射连接到其他领域
        - 系统会根据文档内容自动路由到对应领域

        ### 配置生效机制
        - ⚠️ 配置编辑后需要**点击保存按钮**才会保存（每个Tab底部都有保存按钮）
        - ⚠️ 配置保存后需要**重新构建知识图谱**才会应用到提取流程
        - 💡 在 "知识图谱构建" 页面选择"当前配置"，点击"完整构建"应用新配置

        ### 三种使用方式
        1. **从模板开始**：加载预置的行业模板（法务/电商/医疗），然后根据需求调整，最后保存
        2. **从头开始**：直接添加桥接点和领域，完全自定义，最后保存
        3. **AI 辅助**：使用 "AI 配置向导" 自动分析文档并生成配置建议

        ### 注意事项
        - 所有修改需点击「💾 保存配置」按钮才会保存
        - 加载模板会覆盖当前配置，请先导出备份
        - 建议定期导出配置文件作为备份
        """
        )
