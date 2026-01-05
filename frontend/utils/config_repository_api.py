"""
配置仓库API调用辅助函数
用于配置管理页面调用用户配置仓库API
"""

import requests
import streamlit as st
from typing import Dict, List, Optional

from frontend_config.settings import API_URL


def list_all_configs() -> tuple[bool, List[Dict], Optional[str]]:
    """
    获取所有用户配置列表

    Returns:
        (success, configs, error_message)
    """
    try:
        response = requests.get(f"{API_URL}/admin/configs/list", timeout=10)
        if response.status_code == 200:
            data = response.json()
            return True, data.get("configs", []), None
        else:
            return False, [], f"API返回错误: {response.status_code}"
    except Exception as e:
        return False, [], f"请求失败: {str(e)}"


def get_config_detail(config_id: str) -> tuple[bool, Optional[Dict], Optional[Dict], Optional[str]]:
    """
    获取指定配置的完整内容

    Returns:
        (success, config, metadata, error_message)
    """
    try:
        response = requests.get(f"{API_URL}/admin/configs/{config_id}", timeout=10)
        if response.status_code == 200:
            data = response.json()
            return True, data.get("config"), data.get("metadata"), None
        else:
            return False, None, None, f"API返回错误: {response.status_code}"
    except Exception as e:
        return False, None, None, f"请求失败: {str(e)}"


def get_default_config() -> tuple[bool, Optional[Dict], Optional[Dict], Optional[str]]:
    """
    获取默认配置

    Returns:
        (success, config, metadata, error_message)
    """
    try:
        response = requests.get(f"{API_URL}/admin/configs/default/get", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("exists"):
                return True, data.get("config"), data.get("metadata"), None
            else:
                return True, None, None, None  # 无默认配置，不算错误
        else:
            return False, None, None, f"API返回错误: {response.status_code}"
    except Exception as e:
        return False, None, None, f"请求失败: {str(e)}"


def create_config(config: Dict, name: str, description: Optional[str] = None, set_as_default: bool = False) -> tuple[bool, Optional[str], Optional[str]]:
    """
    创建新配置

    Returns:
        (success, config_id, error_message)
    """
    try:
        payload = {
            "config": config,
            "name": name,
            "description": description,
            "set_as_default": set_as_default
        }
        response = requests.post(f"{API_URL}/admin/configs/create", json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            return True, data.get("config_id"), None
        else:
            error_text = response.text
            return False, None, f"创建失败: {error_text}"
    except Exception as e:
        return False, None, f"请求失败: {str(e)}"


def update_config(config_id: str, config: Dict, name: Optional[str] = None, description: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """
    更新配置

    Returns:
        (success, error_message)
    """
    try:
        payload = {
            "config": config,
            "name": name,
            "description": description
        }
        response = requests.put(f"{API_URL}/admin/configs/{config_id}", json=payload, timeout=30)
        if response.status_code == 200:
            return True, None
        else:
            error_text = response.text
            return False, f"更新失败: {error_text}"
    except Exception as e:
        return False, f"请求失败: {str(e)}"


def delete_config(config_id: str) -> tuple[bool, Optional[str]]:
    """
    删除配置

    Returns:
        (success, error_message)
    """
    try:
        response = requests.delete(f"{API_URL}/admin/configs/{config_id}", timeout=10)
        if response.status_code == 200:
            return True, None
        else:
            error_text = response.text
            return False, f"删除失败: {error_text}"
    except Exception as e:
        return False, f"请求失败: {str(e)}"


def set_default_config(config_id: str) -> tuple[bool, Optional[str]]:
    """
    设置默认配置

    Returns:
        (success, error_message)
    """
    try:
        response = requests.post(f"{API_URL}/admin/configs/{config_id}/set-default", timeout=10)
        if response.status_code == 200:
            return True, None
        else:
            error_text = response.text
            return False, f"设置失败: {error_text}"
    except Exception as e:
        return False, f"请求失败: {str(e)}"


def duplicate_config(config_id: str, new_name: str) -> tuple[bool, Optional[str], Optional[str]]:
    """
    复制配置

    Returns:
        (success, new_config_id, error_message)
    """
    try:
        payload = {"new_name": new_name}
        response = requests.post(f"{API_URL}/admin/configs/{config_id}/duplicate", json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            return True, data.get("config_id"), None
        else:
            error_text = response.text
            return False, None, f"复制失败: {error_text}"
    except Exception as e:
        return False, None, f"请求失败: {str(e)}"
