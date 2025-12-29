"""
模型中心页面

提供LLM和Embedding模型的查看、注册、切换功能。
"""

import json
from typing import Any, Dict, List, Optional

import requests
import streamlit as st

# API 基础 URL
API_URL = "http://localhost:8000"


def render_model_hub():
    """渲染模型中心主页"""
    st.title("🤖 模型中心")
    st.markdown("管理您的LLM和Embedding模型配置")

    st.divider()

    # 标签页
    tab1, tab2 = st.tabs(["🧠 LLM 模型", "🔢 Embedding 模型"])

    with tab1:
        render_llm_models()

    with tab2:
        render_embedding_models()


def render_llm_models():
    """渲染LLM模型管理"""
    st.subheader("LLM 模型")

    # 获取当前活跃模型
    try:
        response = requests.get(f"{API_URL}/admin/models/active/llm")
        if response.status_code == 200:
            active_model = response.json()["model"]
            st.success(f"✅ 当前活跃模型: **{active_model['name']}** ({active_model['config'].get('model', 'N/A')})")
        else:
            st.warning("⚠️ 没有活跃的LLM模型")
    except Exception as e:
        st.error(f"获取活跃模型失败: {e}")

    st.divider()

    # 操作按钮
    col1, col2 = st.columns(2)
    with col1:
        if st.button("➕ 注册新LLM模型", use_container_width=True):
            st.session_state.show_register_llm_dialog = True

    with col2:
        if st.button("🔄 重新加载模型", use_container_width=True):
            reload_models()

    # 注册对话框
    if st.session_state.get("show_register_llm_dialog", False):
        render_register_model_dialog("llm")

    st.divider()

    # 获取LLM模型列表
    try:
        response = requests.get(f"{API_URL}/admin/models/", params={"model_type": "llm"})
        if response.status_code == 200:
            data = response.json()
            models = data.get("models", [])

            if not models:
                st.info("暂无LLM模型，请注册一个")
            else:
                render_model_list(models, "llm")

        else:
            st.error(f"获取模型列表失败: {response.text}")

    except Exception as e:
        st.error(f"获取模型列表失败: {e}")


def render_embedding_models():
    """渲染Embedding模型管理"""
    st.subheader("Embedding 模型")

    # 获取当前活跃模型
    try:
        response = requests.get(f"{API_URL}/admin/models/active/embedding")
        if response.status_code == 200:
            active_model = response.json()["model"]
            st.success(f"✅ 当前活跃模型: **{active_model['name']}** ({active_model['config'].get('model', 'N/A')})")
        else:
            st.warning("⚠️ 没有活跃的Embedding模型")
    except Exception as e:
        st.error(f"获取活跃模型失败: {e}")

    st.divider()

    # 操作按钮
    col1, col2 = st.columns(2)
    with col1:
        if st.button("➕ 注册新Embedding模型", use_container_width=True):
            st.session_state.show_register_embedding_dialog = True

    with col2:
        if st.button("🔄 重新加载模型", use_container_width=True, key="reload_embedding"):
            reload_models()

    # 注册对话框
    if st.session_state.get("show_register_embedding_dialog", False):
        render_register_model_dialog("embedding")

    st.divider()

    # 获取Embedding模型列表
    try:
        response = requests.get(f"{API_URL}/admin/models/", params={"model_type": "embedding"})
        if response.status_code == 200:
            data = response.json()
            models = data.get("models", [])

            if not models:
                st.info("暂无Embedding模型，请注册一个")
            else:
                render_model_list(models, "embedding")

        else:
            st.error(f"获取模型列表失败: {response.text}")

    except Exception as e:
        st.error(f"获取模型列表失败: {e}")


def render_model_list(models: List[Dict[str, Any]], model_type: str):
    """渲染模型列表"""
    for model in models:
        with st.container():
            # 卡片头部
            col1, col2, col3 = st.columns([4, 1, 1])

            with col1:
                # 模型名称和标签
                name_display = f"**{model['name']}**"
                if model.get("is_default"):
                    name_display += " 🏅"
                if model.get("is_active"):
                    name_display += " ✅"

                st.markdown(name_display)
                st.caption(f"🔧 {model['provider']} • 📦 {model['config'].get('model', 'N/A')}")

            with col2:
                # 激活按钮
                if not model.get("is_active"):
                    if st.button("激活", key=f"activate_{model['id']}", use_container_width=True):
                        activate_model(model["id"], model["name"])

            with col3:
                # 删除按钮
                if not model.get("is_default"):
                    if st.button("🗑️", key=f"delete_{model['id']}", use_container_width=True):
                        delete_model(model["id"], model["name"])

            # 描述
            if model.get("description"):
                st.markdown(f"*{model['description']}*")

            # 配置详情
            with st.expander("查看配置", expanded=False):
                # 隐藏API key
                config_display = model["config"].copy()
                if "api_key" in config_display:
                    config_display["api_key"] = (
                        "***" + config_display["api_key"][-4:] if len(config_display["api_key"]) > 4 else "***"
                    )

                st.json(config_display)

            # 标签
            if model.get("tags"):
                tags_html = " ".join(
                    [
                        f'<span style="background-color: #e1e4e8; padding: 2px 6px; border-radius: 3px; font-size: 12px; margin-right: 4px;">{tag}</span>'
                        for tag in model["tags"]
                    ]
                )
                st.markdown(tags_html, unsafe_allow_html=True)

            st.divider()


def render_register_model_dialog(model_type: str):
    """渲染注册模型对话框"""
    st.subheader(f"注册新{model_type.upper()}模型")

    with st.form(f"register_{model_type}_form"):
        name = st.text_input("模型名称*", placeholder=f"例如: GPT-4o")

        # 提供商选择
        providers_response = requests.get(f"{API_URL}/admin/models/providers/list")
        if providers_response.status_code == 200:
            providers_data = providers_response.json()
            provider_options = providers_data["providers"]
            provider = st.selectbox(
                "提供商*",
                options=[p["value"] for p in provider_options],
                format_func=lambda x: next(p["label"] for p in provider_options if p["value"] == x),
            )
        else:
            provider = "openai"

        st.markdown("**模型配置:**")

        # 模型标识
        model_name = st.text_input(
            "模型标识*", placeholder="例如: gpt-4o, text-embedding-3-large", help="模型的API标识符"
        )

        # API配置
        api_key = st.text_input("API Key", type="password", placeholder="sk-...", help="留空则使用环境变量")

        base_url = st.text_input(
            "Base URL", placeholder="https://api.openai.com/v1", help="API端点URL，留空则使用默认值"
        )

        # LLM特有参数
        if model_type == "llm":
            col1, col2 = st.columns(2)
            with col1:
                temperature = st.slider("Temperature", 0.0, 2.0, 0.7, 0.1)
            with col2:
                max_tokens = st.number_input("Max Tokens", min_value=1, value=4096)

        description = st.text_area("描述", placeholder="描述此模型的用途和特点", height=80)

        tags_input = st.text_input("标签", placeholder="用逗号分隔，例如: gpt,openai,production")

        set_active = st.checkbox("立即激活此模型", value=False)

        col1, col2 = st.columns(2)
        with col1:
            submit = st.form_submit_button("✅ 注册", use_container_width=True, type="primary")
        with col2:
            cancel = st.form_submit_button("❌ 取消", use_container_width=True)

        if cancel:
            if model_type == "llm":
                st.session_state.show_register_llm_dialog = False
            else:
                st.session_state.show_register_embedding_dialog = False
            st.rerun()

        if submit:
            if not name or not model_name:
                st.error("请填写所有必填字段（标*）")
            else:
                # 构建配置
                config = {"model": model_name}

                if api_key:
                    config["api_key"] = api_key

                if base_url:
                    config["base_url"] = base_url

                if model_type == "llm":
                    config["temperature"] = temperature
                    config["max_tokens"] = max_tokens

                tags = [tag.strip() for tag in tags_input.split(",")] if tags_input else []

                # 注册模型
                payload = {
                    "name": name,
                    "model_type": model_type,
                    "provider": provider,
                    "config": config,
                    "description": description,
                    "tags": tags,
                    "set_active": set_active,
                }

                try:
                    response = requests.post(f"{API_URL}/admin/models/register", json=payload)
                    if response.status_code == 200:
                        st.success(f"✅ 模型 '{name}' 注册成功！")
                        if model_type == "llm":
                            st.session_state.show_register_llm_dialog = False
                        else:
                            st.session_state.show_register_embedding_dialog = False
                        st.rerun()
                    else:
                        st.error(f"注册失败: {response.text}")
                except Exception as e:
                    st.error(f"注册失败: {e}")


def activate_model(model_id: str, model_name: str):
    """激活模型"""
    try:
        response = requests.post(f"{API_URL}/admin/models/activate", json={"model_id": model_id})

        if response.status_code == 200:
            st.success(f"✅ 模型 '{model_name}' 已激活！")
            st.rerun()
        else:
            st.error(f"激活失败: {response.text}")

    except Exception as e:
        st.error(f"激活失败: {e}")


def delete_model(model_id: str, model_name: str):
    """删除模型"""
    try:
        response = requests.delete(f"{API_URL}/admin/models/{model_id}")

        if response.status_code == 200:
            st.success(f"✅ 模型 '{model_name}' 已删除！")
            st.rerun()
        else:
            st.error(f"删除失败: {response.text}")

    except Exception as e:
        st.error(f"删除失败: {e}")


def reload_models():
    """重新加载模型"""
    try:
        response = requests.post(f"{API_URL}/admin/models/reload")

        if response.status_code == 200:
            st.success("✅ 模型已重新加载！")
            st.rerun()
        else:
            st.error(f"重新加载失败: {response.text}")

    except Exception as e:
        st.error(f"重新加载失败: {e}")
