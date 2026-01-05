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


def render_template_selector():
    """渲染模板选择器"""
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

            if st.button(f"📥 加载", key=f"load_{template_key}"):
                with st.spinner("正在加载模板..."):
                    if load_template(template_key):
                        st.success(f"✅ 模板 '{template_info['project_name']}' 加载成功！")
                        st.rerun()

            if st.button(f"👁️ 预览", key=f"preview_{template_key}"):
                st.session_state.preview_template = template_key


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

                        # 🔥 立即自动保存
                        success, _ = save_graph_config(config, show_feedback=False)
                        if success:
                            st.success(f"✅ 桥接点 '{deleted_name}' 已删除并保存")
                        else:
                            st.error(f"❌ 桥接点删除失败，请手动保存")
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

                # 🔥 立即自动保存
                success, _ = save_graph_config(config, show_feedback=False)
                if success:
                    st.success(f"✅ 桥接点 '{bridge_name}' 已添加并保存")
                else:
                    st.error(f"❌ 桥接点添加失败，请手动保存")
                st.rerun()


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

                        # 🔥 立即自动保存
                        success, _ = save_graph_config(config, show_feedback=False)
                        if success:
                            st.success(f"✅ 领域 '{deleted_name}' 已删除并保存")
                        else:
                            st.error(f"❌ 领域删除失败，请手动保存")
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

                # 🔥 立即自动保存
                success, _ = save_graph_config(config, show_feedback=False)
                if success:
                    st.success(f"✅ 领域 '{domain_name}' 已添加并保存")
                else:
                    st.error(f"❌ 领域添加失败，请手动保存")
                st.rerun()


def render_config_overview(config: Dict):
    """渲染配置概览"""
    st.subheader("📊 当前配置概览")
    st.success("✅ 以下是当前生效的配置（重新构建知识图谱后应用）")

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
                st.info("💡 配置已更新到当前编辑状态，请点击「💾 保存配置」标签页保存")

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

    return None


def config_manager_page():
    """配置管理主页面"""
    st.title("⚙️ 图谱配置管理")
    st.markdown("---")

    # 获取当前配置
    config = fetch_graph_config()

    # 如果没有配置，显示模板选择器
    if config is None:
        st.info("💡 当前无配置，请选择一个模板开始，或创建自定义配置")
        render_template_selector()

        st.markdown("---")
        st.subheader("🆕 或创建空白配置")

        project_name = st.text_input("项目名称", placeholder="例如：我的知识图谱项目")
        industry = st.text_input("所属行业", placeholder="例如：法务、电商、医疗")
        description = st.text_area("项目描述", placeholder="简要描述此知识图谱的用途")

        if st.button("✅ 创建空白配置"):
            if not project_name:
                st.error("项目名称不能为空")
            else:
                new_config = {
                    "project_name": project_name,
                    "version": "1.0",
                    "description": description,
                    "industry": industry,
                    "bridge_definitions": [],
                    "domain_definitions": [],
                }
                success, _ = save_graph_config(new_config, show_feedback=True)
                if success:
                    st.rerun()

        return

    # 🔥 使用 session state 管理配置（支持 JSON 编辑器更新）
    if "current_config" not in st.session_state or st.session_state.get("config_reload_trigger"):
        st.session_state.current_config = config.copy()
        if "config_reload_trigger" in st.session_state:
            del st.session_state.config_reload_trigger

    working_config = st.session_state.current_config

    # 显示配置概览
    render_config_overview(working_config)

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
        - ✅ **配置会自动保存**，无需手动保存

        **3️⃣ 高级编辑（可选）：**
        - "📝 JSON 编辑器" 标签可直接编辑完整配置
        - "💾 修改项目信息" 标签可更新项目名称、描述等元数据

        **4️⃣ 导出配置（可选）：**
        - 在 "💾 修改项目信息" 标签点击 "📥 导出配置"，可保存为 JSON 文件备份

        ---

        ### 常见问题

        **❓ 我添加的配置刷新后不见了怎么办？**
        - 已修复！现在所有添加/删除操作都会自动保存

        **❓ "加载行业模板" 和我的配置有什么关系？**
        - "加载行业模板" 是加载预置的行业模板，会**覆盖**你当前的配置
        - 你的自定义配置就是当前正在编辑的配置，**已经在使用**，无需额外"应用"

        **❓ 如何知道我的配置生效了？**
        - 上方的 "📊 配置概览" 显示的就是当前生效的配置
        - 重新构建知识图谱后，新配置才会应用到提取过程
        """)

    st.markdown("---")

    # 🔥 创建标签页（调整顺序和命名）
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["🔗 桥接点配置", "📦 领域配置", "📝 JSON 编辑器", "📋 加载行业模板", "💾 修改项目信息"]
    )

    with tab1:
        render_bridge_editor(working_config)

    with tab2:
        render_domain_editor(working_config)

    with tab3:
        # 🔥 JSON 源码编辑模式
        updated_config = render_json_editor(working_config)
        if updated_config:
            st.session_state.current_config = updated_config
            st.rerun()

    with tab4:
        st.subheader("📋 加载预置行业模板")
        st.info("💡 这里提供 3 个预置的行业模板作为快速起点，适合首次使用或重新开始项目时使用")
        st.warning("⚠️ **重要提示**：加载模板会**完全覆盖**你当前的所有配置（包括桥接点和领域），请先导出备份！")

        # 添加确认开关
        confirm_load = st.checkbox("我已了解风险，允许覆盖当前配置", key="confirm_template_load")

        if confirm_load:
            render_template_selector()
        else:
            st.info("👆 请先勾选上方确认框，才能加载模板")

    with tab5:
        st.subheader("💾 修改项目信息与导出")
        st.caption("修改项目的元数据信息，或导出配置文件作为备份")

        # 修改项目信息
        project_name = st.text_input("项目名称", value=working_config.get("project_name", ""), key="edit_project_name")
        industry = st.text_input("所属行业", value=working_config.get("industry", ""), key="edit_industry")
        description = st.text_area("项目描述", value=working_config.get("description", ""), key="edit_description")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("💾 保存配置", type="primary", use_container_width=True):
                # 🔥 更新配置并使用增强版 save_graph_config
                working_config["project_name"] = project_name
                working_config["industry"] = industry
                working_config["description"] = description

                success, response_data = save_graph_config(working_config, show_feedback=True)
                if success:
                    # 触发配置重载
                    st.session_state.config_reload_trigger = True

        with col2:
            # 导出配置
            config_json = json.dumps(working_config, ensure_ascii=False, indent=2)
            st.download_button(
                label="📥 导出配置 (JSON)",
                data=config_json,
                file_name=f"{working_config.get('project_name', 'config')}.json",
                mime="application/json",
                use_container_width=True,
            )

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
        - ✅ 配置编辑后会**自动保存**
        - ⚠️ 配置修改后需要**重新构建知识图谱**才会应用到提取流程
        - 💡 在 "知识图谱构建" 页面点击 "全量构建" 或 "增量构建" 应用新配置

        ### 三种使用方式
        1. **从模板开始**：加载预置的行业模板（法务/电商/医疗），然后根据需求调整
        2. **从头开始**：直接添加桥接点和领域，完全自定义
        3. **AI 辅助**：使用 "AI 配置向导" 自动分析文档并生成配置建议

        ### 注意事项
        - 配置会自动保存，无需手动操作
        - 加载模板会覆盖当前配置，请先导出备份
        - 建议定期导出配置文件作为备份
        """
        )
