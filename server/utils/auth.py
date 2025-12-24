"""
身份验证和授权依赖

用途：
- 提供 FastAPI 依赖注入函数，用于保护敏感API端点
- 支持多种认证方式：API Key、JWT Token（可扩展）
- 区分读写权限

安全级别：
- verify_api_key: 基础API Key验证（适合内部服务）
- verify_admin_token: 管理员权限验证（适合知识图谱CRUD）
- verify_jwt_token: JWT Token验证（适合多用户场景，可选）

使用方法：
    from server.utils.auth import verify_admin_token
    from fastapi import Depends

    @router.post("/entity/create", dependencies=[Depends(verify_admin_token)])
    def create_entity(...):
        ...

配置：
    在 .env 中设置：
    ADMIN_API_KEY=your_secret_admin_key_here
    READ_API_KEY=your_read_only_key_here  # 可选，用于只读访问
"""

import os
from fastapi import Header, HTTPException, Depends
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# 配置常量
# ============================================================================

# 从环境变量读取API Key（生产环境必须设置）
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
READ_API_KEY = os.getenv("READ_API_KEY", "")

# 默认密钥警告（仅开发环境使用）
DEFAULT_DEV_KEY = "dev-mode-insecure-key-change-in-production"

# 是否启用认证（默认启用，开发环境可设置为False）
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() == "true"


# ============================================================================
# 依赖函数
# ============================================================================

async def verify_admin_token(
    x_admin_token: Optional[str] = Header(None, description="管理员API密钥")
) -> str:
    """
    验证管理员权限（用于知识图谱CRUD等写操作）

    ✅ 改进：防止未授权访问知识图谱写操作

    Args:
        x_admin_token: HTTP Header中的 X-Admin-Token

    Returns:
        str: 验证通过的token

    Raises:
        HTTPException: 401 (未提供token) 或 403 (token无效)

    使用示例：
        @router.post("/entity/create", dependencies=[Depends(verify_admin_token)])
        def create_entity(...):
            ...
    """
    # 如果禁用认证（仅开发环境），直接通过
    if not AUTH_ENABLED:
        logger.warning("⚠️ 认证已禁用（开发模式），跳过权限检查")
        return "dev-mode"

    # 检查是否提供token
    if not x_admin_token:
        logger.warning("❌ 未提供管理员Token")
        raise HTTPException(
            status_code=401,
            detail={
                "error": "未授权",
                "message": "需要提供管理员API密钥",
                "hint": "在HTTP Header中添加 X-Admin-Token"
            }
        )

    # 获取有效的Admin Key
    valid_key = ADMIN_API_KEY if ADMIN_API_KEY else DEFAULT_DEV_KEY

    # 警告：使用默认密钥
    if valid_key == DEFAULT_DEV_KEY:
        logger.warning(
            "⚠️ 使用默认开发密钥！生产环境请设置环境变量 ADMIN_API_KEY"
        )

    # 验证token
    if x_admin_token != valid_key:
        logger.warning(
            f"❌ 管理员Token验证失败: 提供的token不匹配",
            extra={"provided": x_admin_token[:8] + "..." if len(x_admin_token) > 8 else x_admin_token}
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error": "权限不足",
                "message": "管理员API密钥无效"
            }
        )

    logger.info("✅ 管理员权限验证通过")
    return x_admin_token


async def verify_read_token(
    x_api_key: Optional[str] = Header(None, description="API密钥（读权限）")
) -> str:
    """
    验证读权限（用于查询知识图谱）

    ✅ 可选：区分读写权限，读操作可使用更宽松的密钥

    Args:
        x_api_key: HTTP Header中的 X-API-Key

    Returns:
        str: 验证通过的token

    Raises:
        HTTPException: 401 (未提供token) 或 403 (token无效)

    使用示例：
        @router.get("/entities", dependencies=[Depends(verify_read_token)])
        def list_entities(...):
            ...
    """
    # 如果禁用认证，直接通过
    if not AUTH_ENABLED:
        return "dev-mode"

    # 检查是否提供token
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "未授权",
                "message": "需要提供API密钥",
                "hint": "在HTTP Header中添加 X-API-Key"
            }
        )

    # 获取有效的Read Key（如果未设置，允许Admin Key通用）
    valid_keys = [
        READ_API_KEY if READ_API_KEY else None,
        ADMIN_API_KEY if ADMIN_API_KEY else DEFAULT_DEV_KEY
    ]
    valid_keys = [k for k in valid_keys if k]  # 过滤None

    # 验证token
    if x_api_key not in valid_keys:
        logger.warning(
            f"❌ API密钥验证失败: 提供的key不匹配",
            extra={"provided": x_api_key[:8] + "..." if len(x_api_key) > 8 else x_api_key}
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error": "权限不足",
                "message": "API密钥无效"
            }
        )

    logger.debug("✅ 读权限验证通过")
    return x_api_key


def get_current_user(
    token: str = Depends(verify_admin_token)
) -> dict:
    """
    获取当前用户信息（可扩展为JWT解析）

    ✅ 未来可扩展：集成OAuth2/JWT，返回真实用户信息

    Args:
        token: 验证通过的token（由verify_admin_token提供）

    Returns:
        dict: 用户信息
    """
    # 简化版本：仅返回token标识
    # 生产环境：解析JWT，返回 {"user_id": "...", "role": "admin", ...}
    return {
        "token": token,
        "role": "admin"
    }


# ============================================================================
# 辅助函数
# ============================================================================

def is_auth_configured() -> bool:
    """
    检查认证是否已配置（用于健康检查）

    Returns:
        bool: 是否已设置非默认的Admin Key
    """
    if not AUTH_ENABLED:
        return False

    return ADMIN_API_KEY != "" and ADMIN_API_KEY != DEFAULT_DEV_KEY


def get_auth_status() -> dict:
    """
    获取认证配置状态（用于调试和监控）

    Returns:
        dict: 认证状态信息
    """
    return {
        "auth_enabled": AUTH_ENABLED,
        "admin_key_configured": bool(ADMIN_API_KEY),
        "read_key_configured": bool(READ_API_KEY),
        "using_default_key": ADMIN_API_KEY == "" or ADMIN_API_KEY == DEFAULT_DEV_KEY,
        "warning": "使用默认密钥不安全！" if (ADMIN_API_KEY == "" or ADMIN_API_KEY == DEFAULT_DEV_KEY) else None
    }
