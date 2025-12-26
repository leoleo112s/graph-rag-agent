import sys
from pathlib import Path

import streamlit as st

# Ensure the project root is on sys.path so `graphrag_agent` can be imported
ROOT_PATH = Path(__file__).resolve().parents[1]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

from utils.state import init_session_state
from components.styles import custom_css
from components.chat import display_chat_interface
from components.sidebar import display_sidebar
from components.debug import display_debug_panel
from utils.performance import init_performance_monitoring

# 导入管理页面
from page_components.document_manager import document_manager_page
from page_components.config_manager import config_manager_page
from page_components.build_manager import build_manager_page
from page_components.ai_config_wizard import ai_config_wizard_page
from page_components.admin_feedback import render_feedback_admin
from page_components.metrics_dashboard import render_metrics_dashboard
from page_components.template_marketplace import render_template_marketplace
from page_components.model_hub import render_model_hub


def main():
    """主应用入口函数"""
    # 页面配置
    st.set_page_config(
        page_title="GraphRAG 智能问答系统",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # 初始化会话状态
    init_session_state()

    # 初始化性能监控
    init_performance_monitoring()

    # 添加自定义CSS
    custom_css()

    # ===== 页面导航 =====
    with st.sidebar:
        st.title("🤖 GraphRAG 系统")
        st.markdown("---")

        # 页面选择器
        # 检查是否有页面切换请求
        if "page_switch" in st.session_state:
            page = st.session_state.page_switch
            del st.session_state.page_switch
        else:
            page = st.radio(
                "导航菜单",
                options=["💬 智能问答", "📚 文档管理", "🤖 AI 配置向导", "⚙️ 配置管理", "🏗️ 构建管理", "🏪 模板市场", "🧠 模型中心", "📋 反馈管理", "📊 指标监控"],
                label_visibility="collapsed"
            )

        st.markdown("---")

    # 根据选择显示不同页面
    if page == "💬 智能问答":
        # 显示原有的侧边栏（agent选择等）
        display_sidebar()

        # 主区域布局
        if st.session_state.debug_mode:
            # 调试模式下的布局（左侧聊天，右侧调试信息）
            col1, col2 = st.columns([5, 4])

            with col1:
                display_chat_interface()

            with col2:
                display_debug_panel()
        else:
            # 非调试模式下的布局（仅聊天界面）
            display_chat_interface()

    elif page == "📚 文档管理":
        document_manager_page()

    elif page == "🤖 AI 配置向导":
        ai_config_wizard_page()

    elif page == "⚙️ 配置管理":
        config_manager_page()

    elif page == "🏗️ 构建管理":
        build_manager_page()

    elif page == "🏪 模板市场":
        render_template_marketplace()

    elif page == "🧠 模型中心":
        render_model_hub()

    elif page == "📋 反馈管理":
        render_feedback_admin()

    elif page == "📊 指标监控":
        render_metrics_dashboard()

if __name__ == "__main__":
    import shutup
    shutup.please()
    main()