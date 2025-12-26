"""
模板市场页面

提供图谱配置模板的浏览、下载、评分、一键应用功能。
"""

import streamlit as st
import requests
from typing import Dict, Any, List, Optional
import json
from datetime import datetime

# API 基础 URL
API_URL = "http://localhost:8000"


def render_template_marketplace():
    """渲染模板市场主页"""
    st.title("🏪 模板市场")
    st.markdown("浏览和应用行业领域的图谱配置模板，快速开始您的知识图谱构建")

    st.divider()

    # 顶部控制栏
    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        # 领域筛选
        domains_response = requests.get(f"{API_URL}/admin/templates/domains/list")
        if domains_response.status_code == 200:
            domains_data = domains_response.json()
            domain_options = [{"value": "", "label_zh": "全部领域"}] + domains_data["domains"]
            selected_domain = st.selectbox(
                "领域筛选",
                options=[d["value"] for d in domain_options],
                format_func=lambda x: next(d["label_zh"] for d in domain_options if d["value"] == x),
                index=0
            )
        else:
            selected_domain = None

    with col2:
        # 排序方式
        sort_options = {
            "rating": "⭐ 按评分",
            "downloads": "📥 按下载量",
            "created_at": "🕐 按创建时间"
        }
        sort_by = st.selectbox(
            "排序方式",
            options=list(sort_options.keys()),
            format_func=lambda x: sort_options[x],
            index=0
        )

    with col3:
        # 发布按钮
        if st.button("➕ 发布模板", use_container_width=True):
            st.session_state.show_publish_dialog = True

    st.divider()

    # 发布模板对话框
    if st.session_state.get("show_publish_dialog", False):
        render_publish_dialog()

    # 获取模板列表
    try:
        params = {
            "sort_by": sort_by,
            "limit": 50,
            "offset": 0
        }
        if selected_domain:
            params["domain"] = selected_domain

        response = requests.get(f"{API_URL}/admin/templates/", params=params)

        if response.status_code == 200:
            data = response.json()
            templates = data.get("templates", [])

            if not templates:
                st.info("暂无可用模板，您可以发布第一个模板！")
            else:
                # 显示模板总数
                st.caption(f"共找到 {data['total']} 个模板")

                # 渲染模板卡片网格
                render_template_grid(templates)

        else:
            st.error(f"获取模板列表失败: {response.text}")

    except Exception as e:
        st.error(f"获取模板列表失败: {e}")


def render_template_grid(templates: List[Dict[str, Any]]):
    """渲染模板卡片网格"""
    # 每行3个模板卡片
    num_cols = 3
    rows = [templates[i:i + num_cols] for i in range(0, len(templates), num_cols)]

    for row in rows:
        cols = st.columns(num_cols)
        for idx, template in enumerate(row):
            with cols[idx]:
                render_template_card(template)


def render_template_card(template: Dict[str, Any]):
    """渲染单个模板卡片"""
    # 卡片容器
    with st.container():
        # 官方徽章
        if template.get("is_official", False):
            st.markdown("🏅 **官方模板**")

        # 模板名称和领域
        st.subheader(template["name"])
        st.caption(f"🏷️ {get_domain_label(template['domain'])}")

        # 描述
        st.markdown(template["description"][:100] + ("..." if len(template["description"]) > 100 else ""))

        # 统计信息
        col1, col2 = st.columns(2)
        with col1:
            # 评分显示
            rating = template.get("rating", 0)
            rating_count = template.get("rating_count", 0)
            st.metric("评分", f"⭐ {rating:.1f} ({rating_count})")

        with col2:
            # 下载量
            downloads = template.get("downloads", 0)
            st.metric("下载量", f"📥 {downloads}")

        # 标签
        if template.get("tags"):
            tags_html = " ".join([f'<span style="background-color: #e1e4e8; padding: 2px 6px; border-radius: 3px; font-size: 12px; margin-right: 4px;">{tag}</span>' for tag in template["tags"][:3]])
            st.markdown(tags_html, unsafe_allow_html=True)

        # 作者和时间
        st.caption(f"👤 {template['author_name']} • 📅 {format_date(template['created_at'])}")

        # 操作按钮
        col_view, col_apply = st.columns(2)
        with col_view:
            if st.button("📖 详情", key=f"view_{template['id']}", use_container_width=True):
                st.session_state.selected_template_id = template["id"]
                st.session_state.show_template_detail = True

        with col_apply:
            if st.button("✨ 应用", key=f"apply_{template['id']}", use_container_width=True, type="primary"):
                apply_template(template["id"], template["name"])

        st.divider()


def render_publish_dialog():
    """渲染发布模板对话框"""
    st.subheader("发布模板")

    with st.form("publish_template_form"):
        name = st.text_input("模板名称*", placeholder="例如: 学生管理知识图谱")

        # 领域选择
        domains_response = requests.get(f"{API_URL}/admin/templates/domains/list")
        if domains_response.status_code == 200:
            domains_data = domains_response.json()
            domain_options = domains_data["domains"]
            domain = st.selectbox(
                "领域*",
                options=[d["value"] for d in domain_options],
                format_func=lambda x: next(d["label_zh"] for d in domain_options if d["value"] == x)
            )
        else:
            domain = "custom"

        description = st.text_area("描述*", placeholder="详细描述模板的应用场景和特点", height=100)

        tags_input = st.text_input("标签", placeholder="用逗号分隔，例如: 教育,学生管理,政策")

        author_name = st.text_input("作者名称", value="Anonymous")

        is_public = st.checkbox("公开模板", value=True, help="是否对所有用户可见")

        col1, col2 = st.columns(2)
        with col1:
            submit = st.form_submit_button("✅ 发布", use_container_width=True, type="primary")
        with col2:
            cancel = st.form_submit_button("❌ 取消", use_container_width=True)

        if cancel:
            st.session_state.show_publish_dialog = False
            st.rerun()

        if submit:
            if not name or not domain or not description:
                st.error("请填写所有必填字段（标*）")
            else:
                # 发布模板
                tags = [tag.strip() for tag in tags_input.split(",")] if tags_input else []

                payload = {
                    "name": name,
                    "domain": domain,
                    "description": description,
                    "tags": tags,
                    "author_name": author_name,
                    "is_public": is_public
                }

                try:
                    response = requests.post(f"{API_URL}/admin/templates/publish", json=payload)
                    if response.status_code == 200:
                        st.success(f"✅ 模板 '{name}' 发布成功！")
                        st.session_state.show_publish_dialog = False
                        st.rerun()
                    else:
                        st.error(f"发布失败: {response.text}")
                except Exception as e:
                    st.error(f"发布失败: {e}")


def apply_template(template_id: str, template_name: str):
    """一键应用模板"""
    try:
        response = requests.post(
            f"{API_URL}/admin/templates/apply",
            json={"template_id": template_id}
        )

        if response.status_code == 200:
            st.success(f"✅ 模板 '{template_name}' 已成功应用到当前配置！")
            st.info("💡 提示：您可以在「配置管理」页面查看和调整配置")
        else:
            st.error(f"应用模板失败: {response.text}")

    except Exception as e:
        st.error(f"应用模板失败: {e}")


def get_domain_label(domain_value: str) -> str:
    """获取领域中文标签"""
    domain_labels = {
        "legal": "法务",
        "medical": "医疗",
        "ecommerce": "电商",
        "education": "教育",
        "finance": "金融",
        "government": "政府",
        "manufacturing": "制造业",
        "custom": "自定义"
    }
    return domain_labels.get(domain_value, domain_value)


def format_date(iso_string: str) -> str:
    """格式化ISO日期为可读格式"""
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except:
        return iso_string


# 模板详情页面（在侧边栏显示）
if st.session_state.get("show_template_detail", False):
    template_id = st.session_state.get("selected_template_id")
    if template_id:
        render_template_detail_sidebar(template_id)


def render_template_detail_sidebar(template_id: str):
    """在侧边栏渲染模板详情"""
    with st.sidebar:
        st.title("📖 模板详情")

        try:
            response = requests.get(f"{API_URL}/admin/templates/{template_id}")

            if response.status_code == 200:
                data = response.json()
                template = data["template"]
                ratings = data.get("ratings", [])

                # 关闭按钮
                if st.button("❌ 关闭", use_container_width=True):
                    st.session_state.show_template_detail = False
                    st.rerun()

                st.divider()

                # 基本信息
                st.subheader(template["name"])
                if template.get("is_official"):
                    st.markdown("🏅 **官方模板**")

                st.caption(f"🏷️ {get_domain_label(template['domain'])}")
                st.markdown(template["description"])

                # 统计
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("评分", f"⭐ {template['rating']:.1f}")
                with col2:
                    st.metric("下载", f"📥 {template['downloads']}")

                # 标签
                if template.get("tags"):
                    st.markdown("**标签:**")
                    tags_html = " ".join([f'<span style="background-color: #e1e4e8; padding: 4px 8px; border-radius: 3px; margin-right: 4px;">{tag}</span>' for tag in template["tags"]])
                    st.markdown(tags_html, unsafe_allow_html=True)

                st.divider()

                # 配置预览
                st.markdown("**配置预览:**")
                config_json = template.get("config_json", {})
                with st.expander("查看完整配置", expanded=False):
                    st.json(config_json)

                # 实体类型
                if config_json.get("entity_types"):
                    st.markdown("**实体类型:**")
                    st.code(", ".join(config_json["entity_types"]))

                # 关系类型
                if config_json.get("relationship_types"):
                    st.markdown("**关系类型:**")
                    st.code(", ".join(config_json["relationship_types"]))

                st.divider()

                # 应用按钮
                if st.button("✨ 应用此模板", use_container_width=True, type="primary"):
                    apply_template(template_id, template["name"])

                # 下载按钮
                if st.button("📥 下载配置", use_container_width=True):
                    download_template(template_id, template["name"])

                st.divider()

                # 评分
                st.subheader("⭐ 为模板评分")
                rating_value = st.slider("评分", 1, 5, 5, key=f"rating_slider_{template_id}")
                comment = st.text_area("评论（可选）", key=f"comment_{template_id}", height=80)

                if st.button("提交评分", use_container_width=True):
                    submit_rating(template_id, rating_value, comment)

                st.divider()

                # 用户评分列表
                st.subheader(f"💬 用户评价 ({template['rating_count']})")
                if ratings:
                    for rating in ratings[:5]:  # 显示前5条
                        with st.container():
                            col1, col2 = st.columns([3, 1])
                            with col1:
                                st.caption(f"👤 {rating['user_id']}")
                            with col2:
                                st.caption(f"⭐ {rating['rating']}")

                            if rating.get("comment"):
                                st.markdown(rating["comment"])

                            st.caption(format_date(rating["created_at"]))
                            st.divider()
                else:
                    st.info("暂无评价，成为第一个评价者！")

            else:
                st.error(f"获取模板详情失败: {response.text}")

        except Exception as e:
            st.error(f"获取模板详情失败: {e}")


def download_template(template_id: str, template_name: str):
    """下载模板配置"""
    try:
        response = requests.post(f"{API_URL}/admin/templates/{template_id}/download")

        if response.status_code == 200:
            data = response.json()
            config = data.get("config", {})

            # 提供下载
            st.download_button(
                label="💾 保存配置文件",
                data=json.dumps(config, ensure_ascii=False, indent=2),
                file_name=f"{template_name}_config.json",
                mime="application/json",
                use_container_width=True
            )
            st.success("✅ 配置已准备就绪，点击上方按钮下载")
        else:
            st.error(f"下载失败: {response.text}")

    except Exception as e:
        st.error(f"下载失败: {e}")


def submit_rating(template_id: str, rating: int, comment: Optional[str]):
    """提交评分"""
    try:
        payload = {
            "rating": rating,
            "comment": comment if comment else None,
            "user_id": "anonymous"  # TODO: 替换为实际用户ID
        }

        response = requests.post(
            f"{API_URL}/admin/templates/{template_id}/rate",
            json=payload
        )

        if response.status_code == 200:
            st.success("✅ 评分提交成功！")
            st.rerun()
        else:
            st.error(f"评分失败: {response.text}")

    except Exception as e:
        st.error(f"评分失败: {e}")
