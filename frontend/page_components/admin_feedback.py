"""
反馈管理页面组件

提供反馈审核、批准/拒绝、应用到图谱等功能的管理界面。
"""

import streamlit as st
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime
import json

# API 基础 URL
API_URL = "http://localhost:8000"


def render_feedback_admin():
    """渲染反馈管理主页面"""
    st.title("📋 反馈审核台")

    # 显示统计信息
    render_statistics()

    st.divider()

    # 过滤器
    render_filters()

    st.divider()

    # 反馈列表
    render_feedback_list()


def render_statistics():
    """渲染反馈统计信息"""
    try:
        response = requests.get(f"{API_URL}/admin/feedback/statistics")
        if response.status_code == 200:
            stats = response.json()

            col1, col2, col3, col4, col5 = st.columns(5)

            with col1:
                st.metric("总反馈数", stats.get("total_feedbacks", 0))

            with col2:
                st.metric("待审核", stats.get("pending_feedbacks", 0), delta_color="inverse")

            with col3:
                st.metric("已批准", stats.get("approved_feedbacks", 0))

            with col4:
                st.metric("已应用", stats.get("applied_feedbacks", 0))

            with col5:
                approval_rate = stats.get("approval_rate", 0)
                st.metric("批准率", f"{approval_rate}%")

            # 类型分布
            type_dist = stats.get("type_distribution", {})
            if type_dist:
                st.caption("**反馈类型分布:**")
                dist_text = " | ".join([f"{k}: {v}" for k, v in type_dist.items()])
                st.caption(dist_text)

    except Exception as e:
        st.error(f"获取统计信息失败: {e}")


def render_filters():
    """渲染过滤器"""
    st.subheader("🔍 筛选条件")

    col1, col2 = st.columns(2)

    with col1:
        status_options = ["全部", "待审核", "已批准", "已拒绝", "已应用"]
        status_display_to_value = {
            "全部": None,
            "待审核": "pending",
            "已批准": "approved",
            "已拒绝": "rejected",
            "已应用": "applied"
        }
        selected_status = st.selectbox("状态", status_options, index=1)  # 默认选择"待审核"
        st.session_state.filter_status = status_display_to_value[selected_status]

    with col2:
        type_options = [
            "全部",
            "回答评分",
            "实体合并",
            "关系纠错",
            "缺失实体",
            "幻觉检测",
            "实体错误",
            "配置建议"
        ]
        type_display_to_value = {
            "全部": None,
            "回答评分": "answer_rating",
            "实体合并": "entity_merge",
            "关系纠错": "relation_correction",
            "缺失实体": "missing_entity",
            "幻觉检测": "hallucination",
            "实体错误": "entity_error",
            "配置建议": "config_suggestion"
        }
        selected_type = st.selectbox("类型", type_options)
        st.session_state.filter_type = type_display_to_value[selected_type]


def render_feedback_list():
    """渲染反馈列表"""
    st.subheader("📝 反馈列表")

    # 获取过滤参数
    status = st.session_state.get("filter_status")
    feedback_type = st.session_state.get("filter_type")

    # 分页参数
    if "feedback_page" not in st.session_state:
        st.session_state.feedback_page = 0

    limit = 20
    offset = st.session_state.feedback_page * limit

    try:
        # 构建请求参数
        params = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if feedback_type:
            params["feedback_type"] = feedback_type

        response = requests.get(f"{API_URL}/admin/feedback/list", params=params)

        if response.status_code == 200:
            data = response.json()
            records = data.get("records", [])

            if not records:
                st.info("暂无反馈记录")
                return

            # 显示每条反馈
            for record in records:
                render_feedback_card(record)

            # 分页控制
            col1, col2, col3 = st.columns([1, 2, 1])
            with col1:
                if st.session_state.feedback_page > 0:
                    if st.button("⬅️ 上一页"):
                        st.session_state.feedback_page -= 1
                        st.rerun()

            with col2:
                st.write(f"第 {st.session_state.feedback_page + 1} 页")

            with col3:
                if len(records) == limit:
                    if st.button("下一页 ➡️"):
                        st.session_state.feedback_page += 1
                        st.rerun()

        else:
            st.error(f"获取反馈列表失败: {response.text}")

    except Exception as e:
        st.error(f"获取反馈列表失败: {e}")


def render_feedback_card(record: Dict[str, Any]):
    """渲染单个反馈卡片"""
    feedback_id = record["id"]
    feedback_type = record["type"]
    status = record["status"]
    description = record["description"]
    created_at = record["created_at"]
    user_id = record.get("user_id", "匿名")

    # 状态图标
    status_icons = {
        "pending": "🟡",
        "approved": "🟢",
        "rejected": "🔴",
        "applied": "✅"
    }
    status_names = {
        "pending": "待审核",
        "approved": "已批准",
        "rejected": "已拒绝",
        "applied": "已应用"
    }

    # 类型图标
    type_icons = {
        "answer_rating": "⭐",
        "entity_merge": "🔗",
        "relation_correction": "🔧",
        "missing_entity": "❓",
        "hallucination": "👻",
        "entity_error": "⚠️",
        "config_suggestion": "⚙️"
    }
    type_names = {
        "answer_rating": "回答评分",
        "entity_merge": "实体合并",
        "relation_correction": "关系纠错",
        "missing_entity": "缺失实体",
        "hallucination": "幻觉检测",
        "entity_error": "实体错误",
        "config_suggestion": "配置建议"
    }

    status_icon = status_icons.get(status, "⚪")
    status_name = status_names.get(status, status)
    type_icon = type_icons.get(feedback_type, "📋")
    type_name = type_names.get(feedback_type, feedback_type)

    # 格式化时间
    try:
        dt = datetime.fromisoformat(created_at)
        time_str = dt.strftime("%Y-%m-%d %H:%M")
    except:
        time_str = created_at

    # 使用 expander 展示反馈卡片
    with st.expander(f"{status_icon} {type_icon} {type_name} - {time_str} - {user_id}"):
        # 基本信息
        st.write(f"**描述:** {description}")
        st.write(f"**状态:** {status_name}")

        # 详细内容
        content = record.get("content", {})
        if content:
            st.write("**详细信息:**")
            st.json(content)

        # 审核信息
        if record.get("reviewed_at"):
            st.write(f"**审核时间:** {record['reviewed_at']}")
            st.write(f"**审核人:** {record.get('reviewer_id', 'N/A')}")
            if record.get("review_note"):
                st.write(f"**审核备注:** {record['review_note']}")

        # 操作按钮
        if status == "pending":
            col1, col2, col3 = st.columns(3)

            with col1:
                if st.button("✅ 批准", key=f"approve_{feedback_id}"):
                    review_feedback(feedback_id, "approve")

            with col2:
                if st.button("❌ 拒绝", key=f"reject_{feedback_id}"):
                    review_feedback(feedback_id, "reject")

            with col3:
                if st.button("🔍 查看详情", key=f"detail_{feedback_id}"):
                    show_feedback_detail(record)

        elif status == "approved":
            # 显示应用按钮（仅支持特定类型）
            applicable_types = ["entity_merge", "relation_correction", "entity_error", "hallucination"]
            if feedback_type in applicable_types:
                if st.button("🚀 应用到图谱", key=f"apply_{feedback_id}"):
                    apply_feedback(feedback_id)


def review_feedback(feedback_id: str, action: str):
    """审核反馈"""
    note = st.text_input(f"审核备注 ({action})", key=f"note_{feedback_id}_{action}")

    try:
        response = requests.post(
            f"{API_URL}/admin/feedback/{feedback_id}/review",
            json={
                "action": action,
                "note": note,
                "reviewer_id": "admin"
            }
        )

        if response.status_code == 200:
            st.success(f"反馈已{action}成功")
            st.rerun()
        else:
            st.error(f"审核失败: {response.text}")

    except Exception as e:
        st.error(f"审核失败: {e}")


def apply_feedback(feedback_id: str):
    """应用反馈到图谱"""
    try:
        with st.spinner("正在应用反馈到知识图谱..."):
            response = requests.post(
                f"{API_URL}/admin/feedback/{feedback_id}/apply"
            )

            if response.status_code == 200:
                result = response.json()
                st.success("反馈已成功应用到知识图谱!")
                st.json(result)
                st.rerun()
            else:
                st.error(f"应用失败: {response.text}")

    except Exception as e:
        st.error(f"应用失败: {e}")


def show_feedback_detail(record: Dict[str, Any]):
    """显示反馈详情（模态对话框）"""
    st.write("---")
    st.subheader("反馈详情")
    st.json(record)


# 初始化 session state
if "filter_status" not in st.session_state:
    st.session_state.filter_status = "pending"
if "filter_type" not in st.session_state:
    st.session_state.filter_type = None
if "feedback_page" not in st.session_state:
    st.session_state.feedback_page = 0
