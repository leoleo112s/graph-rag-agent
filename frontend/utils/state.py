import streamlit as st
import uuid
import json
import os
from pathlib import Path
from frontend_config.settings import (
    DEFAULT_KG_SETTINGS,
    DEFAULT_AGENT_TYPE,
    DEFAULT_DEBUG_MODE,
    DEFAULT_SHOW_THINKING,
    DEFAULT_USE_DEEPER_TOOL,
    DEFAULT_USE_STREAM,
    DEFAULT_CHAIN_EXPLORATION,
)

# 对话历史保存目录
CHAT_HISTORY_DIR = Path("./cache/chat_history")
CHAT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

def save_chat_history(session_id: str, messages: list):
    """保存对话历史到本地文件"""
    try:
        history_file = CHAT_HISTORY_DIR / f"{session_id}.json"
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存对话历史失败: {e}")

def load_chat_history(session_id: str) -> list:
    """从本地文件加载对话历史"""
    try:
        history_file = CHAT_HISTORY_DIR / f"{session_id}.json"
        if history_file.exists():
            with open(history_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"加载对话历史失败: {e}")
    return []

def init_session_state():
    """初始化会话状态变量"""
    if 'session_id' not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if 'messages' not in st.session_state:
        # 尝试从持久化存储加载历史对话
        loaded_messages = load_chat_history(st.session_state.session_id)
        st.session_state.messages = loaded_messages if loaded_messages else []
    if 'debug_mode' not in st.session_state:
        st.session_state.debug_mode = DEFAULT_DEBUG_MODE
    if 'execution_log' not in st.session_state:
        st.session_state.execution_log = []
    if 'agent_type' not in st.session_state:
        st.session_state.agent_type = DEFAULT_AGENT_TYPE
    if 'show_thinking' not in st.session_state:
        st.session_state.show_thinking = DEFAULT_SHOW_THINKING
    if 'use_deeper_tool' not in st.session_state:
        st.session_state.use_deeper_tool = DEFAULT_USE_DEEPER_TOOL
    
    # 流式响应设置 - 默认启用，但调试模式下自动禁用
    if 'use_stream' not in st.session_state:
        st.session_state.use_stream = DEFAULT_USE_STREAM
    if st.session_state.debug_mode:
        # 确保调试模式下禁用流式响应
        st.session_state.use_stream = False
        
    if 'kg_data' not in st.session_state:
        st.session_state.kg_data = None
    if 'source_content' not in st.session_state:
        st.session_state.source_content = None
    if 'current_tab' not in st.session_state:
        st.session_state.current_tab = "执行轨迹"
    if 'kg_display_settings' not in st.session_state:
        st.session_state.kg_display_settings = DEFAULT_KG_SETTINGS
    if 'feedback_given' not in st.session_state:
        st.session_state.feedback_given = set()
    if 'feedback_in_progress' not in st.session_state:
        st.session_state.feedback_in_progress = False
    if 'processing_lock' not in st.session_state:
        st.session_state.processing_lock = False
    if 'current_kg_message' not in st.session_state:
        st.session_state.current_kg_message = None
    
    # 知识图谱管理相关状态
    if 'entity_to_update' not in st.session_state:
        st.session_state.entity_to_update = None
    if 'found_relations' not in st.session_state:
        st.session_state.found_relations = None
    if 'relation_to_update' not in st.session_state:
        st.session_state.relation_to_update = None
    if 'use_chain_exploration' not in st.session_state:
        st.session_state.use_chain_exploration = DEFAULT_CHAIN_EXPLORATION

    if 'cache' not in st.session_state:
        st.session_state.cache = {
            'source_info': {},  # 源文件信息缓存
            'knowledge_graphs': {},  # 知识图谱缓存
            'vector_search_results': {},  # 向量搜索结果缓存
            'api_responses': {},  # API响应缓存
        }
