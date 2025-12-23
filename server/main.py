import sys
from pathlib import Path

# 添加项目根目录到 Python 路径，以便能找到 graphrag_agent 模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from routers import api_router
from server_config.database import get_db_manager
from server_config.settings import UVICORN_CONFIG
from services.agent_service import agent_manager
from models.schemas import BaseResponse, ErrorCode
import traceback
import logging

# 配置日志
logger = logging.getLogger(__name__)

# 初始化 FastAPI 应用
app = FastAPI(
    title="知识图谱问答系统",
    description="基于知识图谱的智能问答系统后端API",
    version="1.0.0"
)

# ============================================================================
# 全局异常处理 (Global Exception Handler)
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """处理 HTTPException，返回统一的错误响应"""
    return JSONResponse(
        status_code=exc.status_code,
        content=BaseResponse(
            code=exc.status_code,
            msg=exc.detail,
            data=None
        ).dict()
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    全局异常处理器

    根据异常类型返回不同的错误码：
    - ConnectionError/TimeoutError → DB_CONNECTION_ERROR
    - ValueError/KeyError → PARAM_ERROR
    - 其他 → SERVER_ERROR
    """
    error_msg = str(exc)
    error_code = ErrorCode.SERVER_ERROR

    # 根据异常类型分类
    if isinstance(exc, (ConnectionError, TimeoutError)):
        error_code = ErrorCode.DB_CONNECTION_ERROR
    elif isinstance(exc, (ValueError, KeyError)):
        error_code = ErrorCode.PARAM_ERROR
    elif "LLM" in error_msg or "llm" in error_msg:
        error_code = ErrorCode.LLM_ERROR
    elif "database" in error_msg.lower() or "neo4j" in error_msg.lower():
        error_code = ErrorCode.DB_ERROR

    # 记录详细的异常堆栈到日志
    logger.error(f"全局异常捕获: {error_msg}\n{traceback.format_exc()}")

    return JSONResponse(
        status_code=500,
        content=BaseResponse(
            code=error_code,
            msg=error_msg,
            data=None
        ).dict()
    )


# ============================================================================
# 添加路由（带版本前缀）
# ============================================================================
app.include_router(api_router, prefix="/api/v1")

# 获取数据库连接
db_manager = get_db_manager()
driver = db_manager.driver


@app.on_event("shutdown")
def shutdown_event():
    """应用关闭时清理资源"""
    # 关闭所有Agent资源
    agent_manager.close_all()
    
    # 关闭Neo4j连接
    if driver:
        driver.close()
        print("已关闭Neo4j连接")


# 启动服务器
if __name__ == "__main__":
    uvicorn.run("main:app", **UVICORN_CONFIG)
