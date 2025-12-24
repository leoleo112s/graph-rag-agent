import sys
from pathlib import Path

# 添加项目根目录到 Python 路径，以便能找到 graphrag_agent 模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn
import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from routers import api_router
from server_config.database import get_db_manager
from server_config.settings import UVICORN_CONFIG
from services.agent_service import agent_manager
from models.schemas import BaseResponse, ErrorCode
from utils.exceptions import BusinessException
from utils.logger import setup_logging, get_logger
import traceback

# 配置结构化日志系统
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
setup_logging(
    log_level="DEBUG" if DEBUG else "INFO",
    log_dir=Path("logs") if not DEBUG else None,  # 开发环境不写文件
    use_json=not DEBUG  # 生产环境使用 JSON 格式
)

# 获取日志器
logger = get_logger(__name__)

# 初始化 FastAPI 应用
app = FastAPI(
    title="知识图谱问答系统",
    description="基于知识图谱的智能问答系统后端API",
    version="1.0.0"
)

# ============================================================================
# 全局异常处理 (Global Exception Handler)
# ============================================================================

@app.exception_handler(BusinessException)
async def business_exception_handler(request: Request, exc: BusinessException):
    """
    处理业务异常

    业务异常通常返回 200 状态码，通过 code 字段区分错误类型
    """
    logger.warning(
        f"业务异常: {exc.message}",
        code=exc.code,
        details=exc.details,
        path=request.url.path
    )

    return JSONResponse(
        status_code=200,  # 业务异常返回 200
        content=BaseResponse(
            code=exc.code,
            msg=exc.message,
            data=exc.details if exc.details else None
        ).dict()
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """处理 FastAPI HTTPException，返回统一的错误响应"""
    logger.warning(
        f"HTTP异常: {exc.detail}",
        status_code=exc.status_code,
        path=request.url.path
    )

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
    全局异常处理器（兜底）

    捕获所有未被处理的系统异常：
    - ConnectionError/TimeoutError → DB_CONNECTION_ERROR
    - ValueError/KeyError → PARAM_ERROR
    - 其他 → SERVER_ERROR

    生产环境（DEBUG=false）隐藏详细错误信息，仅显示通用错误消息
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
    logger.error(
        f"系统异常捕获: {error_msg}",
        exc_info=True,
        path=request.url.path,
        method=request.method
    )

    # DEBUG 模式显示详细错误，生产环境隐藏
    if DEBUG:
        response_msg = error_msg
        response_data = {"traceback": traceback.format_exc()}
    else:
        response_msg = "服务器内部错误，请联系管理员"
        response_data = None

    return JSONResponse(
        status_code=500,
        content=BaseResponse(
            code=error_code,
            msg=response_msg,
            data=response_data
        ).dict()
    )


# ============================================================================
# 添加路由（带版本前缀）
# ============================================================================
app.include_router(api_router, prefix="/api/v1")

# 获取数据库连接
db_manager = get_db_manager()
driver = db_manager.driver


@app.on_event("startup")
async def startup_event():
    """应用启动时初始化"""
    logger.info("知识图谱问答系统启动", version="1.0.0", debug=DEBUG)


@app.on_event("shutdown")
def shutdown_event():
    """应用关闭时清理资源"""
    # 关闭所有Agent资源
    agent_manager.close_all()
    logger.info("已关闭所有 Agent 资源")

    # 关闭Neo4j连接
    if driver:
        driver.close()
        logger.info("已关闭 Neo4j 连接")


# 启动服务器
if __name__ == "__main__":
    uvicorn.run("main:app", **UVICORN_CONFIG)
