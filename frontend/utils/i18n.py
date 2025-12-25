"""
国际化（i18n）工具

提供多语言支持功能，支持中英文切换。

✅ 改进：解决硬编码中文字符串问题

使用方法：
    from utils.i18n import init_i18n, t, set_language

    # 初始化（在 app.py 中调用）
    init_i18n()

    # 使用翻译函数
    st.title(t("title"))

    # 切换语言
    set_language("en")
"""

import streamlit as st

# ============================================================================
# 语言包定义
# ============================================================================

TRANSLATIONS = {
    "zh": {
        # 通用
        "title": "GraphRAG 智能问答系统",
        "system_title": "🤖 GraphRAG 系统",
        "welcome": "欢迎使用",

        # 导航菜单
        "nav_chat": "💬 智能问答",
        "nav_docs": "📚 文档管理",
        "nav_ai_wizard": "🤖 AI 配置向导",
        "nav_config": "⚙️ 配置管理",
        "nav_build": "🏗️ 构建管理",

        # 设置
        "language": "语言",
        "zh_cn": "中文",
        "en_us": "English",

        # 聊天界面
        "chat_input_placeholder": "请输入您的问题...",
        "chat_send": "发送",
        "chat_clear": "清空对话",

        # Agent 选择
        "agent_selector": "选择 Agent",
        "agent_naive": "Naive RAG",
        "agent_graph": "Graph Agent",
        "agent_hybrid": "Hybrid Agent",
        "agent_deep": "Deep Research",
        "agent_fusion": "Fusion Agent",

        # 调试模式
        "debug_mode": "调试模式",
        "debug_panel": "调试信息",

        # 文档管理
        "docs_upload": "上传文档",
        "docs_list": "文档列表",
        "docs_delete": "删除",

        # 构建管理
        "build_mode": "构建模式",
        "build_full": "全量构建",
        "build_incremental": "增量构建",
        "build_start": "开始构建",
        "build_status": "构建状态",

        # 状态提示
        "status_success": "成功",
        "status_error": "错误",
        "status_warning": "警告",
        "status_info": "信息",

        # 按钮
        "btn_confirm": "确认",
        "btn_cancel": "取消",
        "btn_save": "保存",
        "btn_reset": "重置",

        # 错误提示
        "error_network": "网络错误",
        "error_server": "服务器错误",
        "error_timeout": "请求超时",
    },
    "en": {
        # General
        "title": "GraphRAG AI Q&A System",
        "system_title": "🤖 GraphRAG System",
        "welcome": "Welcome",

        # Navigation
        "nav_chat": "💬 Chat Assistant",
        "nav_docs": "📚 Documents",
        "nav_ai_wizard": "🤖 AI Wizard",
        "nav_config": "⚙️ Settings",
        "nav_build": "🏗️ Build",

        # Settings
        "language": "Language",
        "zh_cn": "中文",
        "en_us": "English",

        # Chat Interface
        "chat_input_placeholder": "Enter your question...",
        "chat_send": "Send",
        "chat_clear": "Clear Chat",

        # Agent Selection
        "agent_selector": "Select Agent",
        "agent_naive": "Naive RAG",
        "agent_graph": "Graph Agent",
        "agent_hybrid": "Hybrid Agent",
        "agent_deep": "Deep Research",
        "agent_fusion": "Fusion Agent",

        # Debug Mode
        "debug_mode": "Debug Mode",
        "debug_panel": "Debug Info",

        # Document Management
        "docs_upload": "Upload",
        "docs_list": "Document List",
        "docs_delete": "Delete",

        # Build Management
        "build_mode": "Build Mode",
        "build_full": "Full Build",
        "build_incremental": "Incremental Build",
        "build_start": "Start Build",
        "build_status": "Build Status",

        # Status Messages
        "status_success": "Success",
        "status_error": "Error",
        "status_warning": "Warning",
        "status_info": "Info",

        # Buttons
        "btn_confirm": "Confirm",
        "btn_cancel": "Cancel",
        "btn_save": "Save",
        "btn_reset": "Reset",

        # Error Messages
        "error_network": "Network Error",
        "error_server": "Server Error",
        "error_timeout": "Request Timeout",
    }
}


# ============================================================================
# 核心函数
# ============================================================================

def init_i18n():
    """
    初始化语言状态

    在 app.py 的 main() 函数开头调用一次即可。
    """
    if "language" not in st.session_state:
        # 默认使用中文
        st.session_state.language = "zh"


def t(key: str, lang: str = None) -> str:
    """
    翻译函数

    Args:
        key: 翻译键（如 "title", "nav_chat"）
        lang: 可选的语言代码，默认使用 session_state 中的语言

    Returns:
        str: 翻译后的文本，如果找不到则返回 key 本身

    使用示例：
        st.title(t("title"))
        st.write(t("welcome"))
    """
    # 确定使用的语言
    if lang is None:
        lang = st.session_state.get("language", "zh")

    # 获取对应语言的字典，默认为中文
    lang_dict = TRANSLATIONS.get(lang, TRANSLATIONS["zh"])

    # 返回对应 key 的值，如果找不到则返回 key 本身（方便调试）
    return lang_dict.get(key, key)


def set_language(lang_code: str):
    """
    切换语言

    Args:
        lang_code: 语言代码（"zh" 或 "en"）

    使用示例：
        if st.button("English"):
            set_language("en")
            st.rerun()
    """
    if lang_code in TRANSLATIONS:
        st.session_state.language = lang_code
    else:
        # 无效的语言代码，默认使用中文
        st.session_state.language = "zh"


def get_current_language() -> str:
    """
    获取当前语言代码

    Returns:
        str: 当前语言代码（"zh" 或 "en"）
    """
    return st.session_state.get("language", "zh")


def add_translation(lang_code: str, translations: dict):
    """
    动态添加翻译内容

    Args:
        lang_code: 语言代码
        translations: 翻译字典

    使用示例：
        # 为特定功能添加翻译
        add_translation("en", {
            "custom_feature": "Custom Feature",
            "custom_button": "Click Me"
        })
    """
    if lang_code in TRANSLATIONS:
        TRANSLATIONS[lang_code].update(translations)
    else:
        TRANSLATIONS[lang_code] = translations


# ============================================================================
# 语言切换组件
# ============================================================================

def render_language_switcher():
    """
    渲染语言切换按钮（放在侧边栏）

    使用示例（in app.py）:
        with st.sidebar:
            render_language_switcher()
    """
    current_lang = get_current_language()

    st.markdown("---")
    st.markdown(f"**{t('language')}**")

    col1, col2 = st.columns(2)

    with col1:
        # 中文按钮
        if st.button(
            "🇨🇳 中文",
            use_container_width=True,
            type="primary" if current_lang == "zh" else "secondary"
        ):
            set_language("zh")
            st.rerun()

    with col2:
        # 英文按钮
        if st.button(
            "🇺🇸 EN",
            use_container_width=True,
            type="primary" if current_lang == "en" else "secondary"
        ):
            set_language("en")
            st.rerun()
