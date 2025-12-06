"""
前端页面模块
包含文档管理、配置管理和构建管理等管理界面
"""

from .document_manager import document_manager_page
from .config_manager import config_manager_page
from .build_manager import build_manager_page

__all__ = [
    'document_manager_page',
    'config_manager_page',
    'build_manager_page',
]
