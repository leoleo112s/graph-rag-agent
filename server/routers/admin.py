"""
管理路由
提供文档管理、配置管理、构建管理等管理 API
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import Dict, Optional
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from graphrag_agent.config.settings import FILES_DIR, BASE_DIR
from graphrag_agent.graph.core import connection_manager

router = APIRouter(prefix="/admin", tags=["admin"])

# 全局构建状态
build_status = {
    "status": "idle",  # idle, running, completed, failed
    "progress": 0,
    "current_stage": "",
    "processed": 0,
    "total": 0,
    "elapsed_time": 0,
    "start_time": None,
    "logs": [],
    "error": None
}

build_lock = threading.Lock()


def run_build_command(command: list, build_type: str):
    """在后台运行构建命令"""
    global build_status

    with build_lock:
        build_status["status"] = "running"
        build_status["progress"] = 0
        build_status["current_stage"] = "初始化"
        build_status["processed"] = 0
        build_status["total"] = 100
        build_status["start_time"] = time.time()
        build_status["logs"] = [f"开始{build_type}构建..."]
        build_status["error"] = None

    try:
        # 执行构建命令
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        # 读取输出
        for line in iter(process.stdout.readline, ''):
            if line:
                with build_lock:
                    build_status["logs"].append(line.strip())
                    # 简单的进度估算（可以根据实际日志解析更准确的进度）
                    if "文档读取" in line or "读取文件" in line:
                        build_status["current_stage"] = "文档读取"
                        build_status["progress"] = 10
                    elif "实体提取" in line or "提取实体" in line:
                        build_status["current_stage"] = "实体提取"
                        build_status["progress"] = 40
                    elif "实体消歧" in line or "对齐" in line:
                        build_status["current_stage"] = "实体消歧"
                        build_status["progress"] = 60
                    elif "图谱构建" in line or "构建图谱" in line:
                        build_status["current_stage"] = "图谱构建"
                        build_status["progress"] = 75
                    elif "向量索引" in line or "索引" in line:
                        build_status["current_stage"] = "向量索引"
                        build_status["progress"] = 85
                    elif "社区检测" in line:
                        build_status["current_stage"] = "社区检测"
                        build_status["progress"] = 95
                    elif "完成" in line:
                        build_status["progress"] = 100

                    build_status["elapsed_time"] = int(time.time() - build_status["start_time"])

        process.wait()

        with build_lock:
            if process.returncode == 0:
                build_status["status"] = "completed"
                build_status["progress"] = 100
                build_status["current_stage"] = "完成"
                build_status["logs"].append(f"{build_type}构建成功完成")
            else:
                build_status["status"] = "failed"
                build_status["error"] = f"构建失败，退出码: {process.returncode}"
                build_status["logs"].append(f"{build_type}构建失败")

    except Exception as e:
        with build_lock:
            build_status["status"] = "failed"
            build_status["error"] = str(e)
            build_status["logs"].append(f"构建异常: {e}")


@router.post("/build/full")
async def trigger_full_build(background_tasks: BackgroundTasks):
    """触发完整构建"""
    if build_status["status"] == "running":
        raise HTTPException(status_code=400, detail="已有构建任务正在运行")

    # 在后台启动构建
    command = ["python", "graphrag_agent/integrations/build/main.py"]
    thread = threading.Thread(target=run_build_command, args=(command, "完整"))
    thread.daemon = True
    thread.start()

    return {"message": "完整构建已启动", "status": "running"}


@router.post("/build/incremental")
async def trigger_incremental_build(background_tasks: BackgroundTasks):
    """触发增量构建"""
    if build_status["status"] == "running":
        raise HTTPException(status_code=400, detail="已有构建任务正在运行")

    # 在后台启动增量构建
    command = ["python", "graphrag_agent/integrations/build/incremental_update.py", "--once"]
    thread = threading.Thread(target=run_build_command, args=(command, "增量"))
    thread.daemon = True
    thread.start()

    return {"message": "增量构建已启动", "status": "running"}


@router.post("/build/stop")
async def stop_build():
    """停止构建"""
    with build_lock:
        if build_status["status"] == "running":
            build_status["status"] = "idle"
            build_status["logs"].append("构建已被用户停止")
            return {"message": "构建已停止"}
        else:
            return {"message": "没有正在运行的构建任务"}


@router.get("/build/status")
async def get_build_status():
    """获取构建状态"""
    with build_lock:
        return build_status.copy()


@router.get("/graph/stats")
async def get_graph_stats():
    """获取图谱统计信息"""
    try:
        # 查询实体数量
        entity_count_query = "MATCH (n) RETURN count(n) as count"
        entity_result = connection_manager.execute_query(entity_count_query)
        entity_count = entity_result[0]['count'] if entity_result else 0

        # 查询关系数量
        relationship_count_query = "MATCH ()-[r]->() RETURN count(r) as count"
        relationship_result = connection_manager.execute_query(relationship_count_query)
        relationship_count = relationship_result[0]['count'] if relationship_result else 0

        # 查询实体类型分布
        entity_type_query = """
        MATCH (n)
        WHERE n.entity_type IS NOT NULL
        RETURN n.entity_type as type, count(*) as count
        ORDER BY count DESC
        """
        entity_type_result = connection_manager.execute_query(entity_type_query)
        entity_type_distribution = {
            item['type']: item['count'] for item in entity_type_result
        } if entity_type_result else {}

        # 查询关系类型分布
        relationship_type_query = """
        MATCH ()-[r]->()
        RETURN type(r) as type, count(*) as count
        ORDER BY count DESC
        """
        relationship_type_result = connection_manager.execute_query(relationship_type_query)
        relationship_type_distribution = {
            item['type']: item['count'] for item in relationship_type_result
        } if relationship_type_result else {}

        # 查询社区数量
        community_count_query = """
        MATCH (n)
        WHERE n.community_id IS NOT NULL
        RETURN count(DISTINCT n.community_id) as count
        """
        community_result = connection_manager.execute_query(community_count_query)
        community_count = community_result[0]['count'] if community_result else 0

        # 统计文档数量
        files_dir = Path(FILES_DIR)
        document_count = len([f for f in files_dir.iterdir() if f.is_file()]) if files_dir.exists() else 0

        return {
            "entity_count": entity_count,
            "relationship_count": relationship_count,
            "community_count": community_count,
            "document_count": document_count,
            "entity_type_distribution": entity_type_distribution,
            "relationship_type_distribution": relationship_type_distribution,
            "last_build_time": datetime.now().isoformat() if entity_count > 0 else None
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取图谱统计失败: {str(e)}")


@router.get("/health")
async def health_check():
    """健康检查"""
    try:
        # 检查 Neo4j 连接
        connection_manager.execute_query("RETURN 1")
        neo4j_status = "healthy"
    except:
        neo4j_status = "unhealthy"

    return {
        "status": "ok",
        "neo4j": neo4j_status,
        "timestamp": datetime.now().isoformat()
    }
