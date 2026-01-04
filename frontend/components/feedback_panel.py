"""
精细化反馈组件

提供多种反馈类型：实体合并、关系纠错、缺失实体、幻觉检测等。
"""

from typing import Any, Dict, Optional

import requests
import streamlit as st

# API 基础 URL
from frontend_config.settings import API_URL


def render_detailed_feedback_button(message_id: str, user_query: str, thread_id: str, agent_type: str):
    """
    渲染详细反馈按钮

    Args:
        message_id: 消息ID
        user_query: 用户查询
        thread_id: 会话ID
        agent_type: 代理类型
    """
    if st.button("📝 详细反馈", key=f"detailed_feedback_{message_id}"):
        # 设置一个 session state 来触发模态对话框
        st.session_state[f"show_feedback_modal_{message_id}"] = True
        st.rerun()

    # 如果需要显示反馈表单
    if st.session_state.get(f"show_feedback_modal_{message_id}", False):
        render_feedback_form(message_id, user_query, thread_id, agent_type)


def render_feedback_form(message_id: str, user_query: str, thread_id: str, agent_type: str):
    """
    渲染反馈表单

    Args:
        message_id: 消息ID
        user_query: 用户查询
        thread_id: 会话ID
        agent_type: 代理类型
    """
    with st.expander("🔍 提交详细反馈", expanded=True):
        feedback_type = st.selectbox(
            "反馈类型",
            ["实体信息错误", "建议合并实体", "关系类型错误", "缺失重要实体", "发现幻觉实体"],
            key=f"feedback_type_{message_id}",
        )

        description = st.text_area("详细描述", placeholder="请描述您发现的问题...", key=f"feedback_desc_{message_id}")

        # 根据反馈类型显示不同的表单字段
        content = {}

        if feedback_type == "建议合并实体":
            col1, col2 = st.columns(2)
            with col1:
                merge_from = st.text_input(
                    "要合并的实体", placeholder="例如: 学生管理办法", key=f"merge_from_{message_id}"
                )
            with col2:
                merge_to = st.text_input("合并到", placeholder="例如: 学生管理规定", key=f"merge_to_{message_id}")

            content = {"merge_from": merge_from, "merge_to": merge_to}

        elif feedback_type == "关系类型错误":
            col1, col2 = st.columns(2)
            with col1:
                source = st.text_input("源实体", placeholder="例如: 学生", key=f"rel_source_{message_id}")
                old_type = st.text_input("错误的关系类型", placeholder="例如: 申请", key=f"rel_old_type_{message_id}")
            with col2:
                target = st.text_input("目标实体", placeholder="例如: 奖学金", key=f"rel_target_{message_id}")
                new_type = st.text_input("正确的关系类型", placeholder="例如: 获得", key=f"rel_new_type_{message_id}")

            content = {"source": source, "target": target, "old_type": old_type, "new_type": new_type}

        elif feedback_type == "实体信息错误":
            entity_id = st.text_input("实体ID或名称", placeholder="例如: 学生管理办法", key=f"entity_id_{message_id}")

            updates = {}
            if st.checkbox("更新名称", key=f"update_name_{message_id}"):
                updates["name"] = st.text_input("新名称", key=f"new_name_{message_id}")

            if st.checkbox("更新类型", key=f"update_type_{message_id}"):
                updates["type"] = st.text_input("新类型", key=f"new_type_{message_id}")

            if st.checkbox("更新描述", key=f"update_desc_{message_id}"):
                updates["description"] = st.text_area("新描述", key=f"new_desc_{message_id}")

            content = {"entity_id": entity_id, "updates": updates}

        elif feedback_type == "缺失重要实体":
            missing_entity = st.text_input(
                "缺失的实体名称", placeholder="例如: 国家励志奖学金", key=f"missing_entity_{message_id}"
            )

            entity_type = st.text_input(
                "实体类型", placeholder="例如: 奖学金类型", key=f"missing_entity_type_{message_id}"
            )

            content = {"entity_name": missing_entity, "entity_type": entity_type}

        elif feedback_type == "发现幻觉实体":
            hallucination_entity = st.text_input(
                "幻觉实体ID或名称", placeholder="例如: 虚构的奖学金", key=f"hallucination_entity_{message_id}"
            )

            content = {"entity_id": hallucination_entity}

        # 提交按钮
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 提交反馈", key=f"submit_feedback_{message_id}", use_container_width=True):
                submit_detailed_feedback(feedback_type, description, content, message_id, thread_id, agent_type)
                # 关闭模态对话框
                st.session_state[f"show_feedback_modal_{message_id}"] = False
                st.rerun()

        with col2:
            if st.button("❌ 取消", key=f"cancel_feedback_{message_id}", use_container_width=True):
                # 关闭模态对话框
                st.session_state[f"show_feedback_modal_{message_id}"] = False
                st.rerun()


def submit_detailed_feedback(
    feedback_type: str, description: str, content: Dict[str, Any], message_id: str, thread_id: str, agent_type: str
):
    """
    提交详细反馈到后端

    Args:
        feedback_type: 反馈类型
        description: 描述
        content: 反馈内容
        message_id: 消息ID
        thread_id: 会话ID
        agent_type: 代理类型
    """
    # 映射反馈类型到后端枚举
    type_mapping = {
        "实体信息错误": "entity_error",
        "建议合并实体": "entity_merge",
        "关系类型错误": "relation_correction",
        "缺失重要实体": "missing_entity",
        "发现幻觉实体": "hallucination",
    }

    backend_type = type_mapping.get(feedback_type, "entity_error")

    try:
        response = requests.post(
            f"{API_URL}/admin/feedback/detailed",
            json={
                "type": backend_type,
                "target_id": message_id,
                "content": content,
                "description": description,
                "user_id": "anonymous",
                "thread_id": thread_id,
                "agent_type": agent_type,
            },
        )

        if response.status_code == 200:
            st.success("反馈提交成功！管理员会尽快审核。")
        else:
            st.error(f"提交失败: {response.text}")

    except Exception as e:
        st.error(f"提交失败: {e}")


def render_entity_feedback_menu(entity_id: str, entity_name: str):
    """
    在知识图谱节点上渲染右键菜单

    Args:
        entity_id: 实体ID
        entity_name: 实体名称
    """
    st.write(f"**实体:** {entity_name}")

    feedback_type = st.radio(
        "快速反馈", ["报告实体错误", "建议合并实体", "标记为幻觉"], key=f"entity_feedback_type_{entity_id}"
    )

    description = st.text_area("说明", key=f"entity_feedback_desc_{entity_id}")

    content = {"entity_id": entity_id}

    if feedback_type == "建议合并实体":
        merge_to = st.text_input("合并到哪个实体？", key=f"entity_merge_to_{entity_id}")
        content["merge_to"] = merge_to
        backend_type = "entity_merge"
    elif feedback_type == "标记为幻觉":
        backend_type = "hallucination"
    else:
        backend_type = "entity_error"

    if st.button("提交", key=f"entity_feedback_submit_{entity_id}"):
        try:
            response = requests.post(
                f"{API_URL}/admin/feedback/detailed",
                json={
                    "type": backend_type,
                    "target_id": entity_id,
                    "content": content,
                    "description": description,
                    "user_id": "anonymous",
                },
            )

            if response.status_code == 200:
                st.success("反馈已提交")
            else:
                st.error(f"提交失败: {response.text}")

        except Exception as e:
            st.error(f"提交失败: {e}")
