"""
管理路由 (Admin Router)
提供文档管理、配置管理、构建管理 (V2集成) 等管理 API
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

# 引入配置
from graphrag_agent.config.settings import FILES_DIR
from graphrag_agent.config.neo4jdb import get_db_manager
from graphrag_agent.graph.core import connection_manager
from graphrag_agent.config.graph_config_model import GraphConfig
from graphrag_agent.config.graph_config_storage import get_storage

# 引入 V2 构建管理器和广播器
from graphrag_agent.integrations.build.incremental_update_v2 import IncrementalUpdateManagerV2
from utils.progress_broadcaster import get_broadcaster
from utils.progress_manager import get_progress_manager

# 配置日志
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# 全局构建锁，防止重复运行
_build_lock = asyncio.Lock()
_is_building = False


# ==================== 核心构建逻辑 (V2 集成) ====================

async def _run_full_build_task():
    """
    后台任务：执行全量构建 (清空库 -> 重建)
    """
    global _is_building
    broadcaster = get_broadcaster()
    progress_mgr = get_progress_manager()

    try:
        # 1. 初始化状态
        await broadcaster.emit_status("started", "全量构建任务已启动")
        await broadcaster.emit_log("=== 开始全量构建流程 ===", "INFO")
        await progress_mgr.update(percent=0, stage="init", details="初始化环境...")

        # 2. 🚨 清空 Neo4j 数据库 (全量构建的核心)
        await broadcaster.emit_log("正在清空现有知识图谱...", "WARNING")
        await progress_mgr.update(percent=5, stage="cleaning", details="正在清空数据库...")

        db_manager = get_db_manager()
        # 执行 Cypher 清空全库
        db_manager.execute_query("MATCH (n) DETACH DELETE n")

        await broadcaster.emit_log("✅ 数据库已清空", "INFO")
        await progress_mgr.update(percent=10, stage="cleaning_done", details="数据库已清空")

        # 3. 初始化 V2 管理器
        manager = IncrementalUpdateManagerV2(
            files_dir=FILES_DIR,
            broadcaster=broadcaster  # 注入广播器，让 V2 内部也能发消息
        )

        # 4. 执行完整流程 (L0 + L1)
        # 全量模式下，我们不传入 file_paths，让它扫描所有文件
        await broadcaster.emit_log("开始全量重新索引 (L0 + L1)...", "INFO")

        # 直接 await，因为 run_full_pipeline 已经是 async def
        result = await manager.run_full_pipeline()

        # 5. 完成
        await broadcaster.emit_log(f"✅ 全量构建完成，耗时: {result.get('total_duration', 0):.2f}s", "INFO")
        await broadcaster.emit_status("completed", "全量构建成功")
        await progress_mgr.update(percent=100, stage="completed", details="构建成功")

    except Exception as e:
        logger.exception("全量构建失败")
        error_msg = str(e)
        await broadcaster.emit_error(f"全量构建失败: {error_msg}")
        await broadcaster.emit_status("failed", error_msg)
        await progress_mgr.update(stage="error", details=f"失败: {error_msg}")

    finally:
        async with _build_lock:
            _is_building = False


async def _run_incremental_build_task():
    """
    后台任务：执行增量构建 (仅处理变更)
    """
    global _is_building
    broadcaster = get_broadcaster()
    progress_mgr = get_progress_manager()

    try:
        await broadcaster.emit_status("started", "增量构建任务已启动")
        await broadcaster.emit_log("=== 开始增量构建流程 ===", "INFO")

        # 初始化 V2 管理器
        manager = IncrementalUpdateManagerV2(
            files_dir=FILES_DIR,
            broadcaster=broadcaster
        )

        # 执行完整流程 (自动检测变更)
        # 直接 await，因为 run_full_pipeline 已经是 async def
        result = await manager.run_full_pipeline()

        # 检查是否有文件被处理
        l0_count = result.get('l0', {}).get('files_processed', 0)

        if l0_count == 0:
            await broadcaster.emit_log("未检测到文件变更，无需构建", "INFO")
        else:
            await broadcaster.emit_log(f"✅ 增量构建完成，处理了 {l0_count} 个文件", "INFO")

        await broadcaster.emit_status("completed", "构建完成")
        await progress_mgr.update(percent=100, stage="completed", details="构建完成")

    except Exception as e:
        logger.exception("增量构建失败")
        await broadcaster.emit_error(f"增量构建失败: {str(e)}")
        await broadcaster.emit_status("failed", str(e))

    finally:
        async with _build_lock:
            _is_building = False


# ==================== 构建 API ====================

@router.post("/build/full")
async def trigger_full_build(background_tasks: BackgroundTasks):
    """触发完整构建 (V2集成版)"""
    global _is_building
    logger.info("收到完整构建请求")

    async with _build_lock:
        if _is_building:
            raise HTTPException(status_code=400, detail="已有构建任务正在运行")
        _is_building = True

    # 启动后台任务
    background_tasks.add_task(_run_full_build_task)

    return {"message": "完整构建已在后台启动", "status": "running"}


@router.post("/build/incremental")
async def trigger_incremental_build(background_tasks: BackgroundTasks):
    """触发增量构建 (V2集成版)"""
    global _is_building
    logger.info("收到增量构建请求")

    async with _build_lock:
        if _is_building:
            raise HTTPException(status_code=400, detail="已有构建任务正在运行")
        _is_building = True

    # 启动后台任务
    background_tasks.add_task(_run_incremental_build_task)

    return {"message": "增量构建已在后台启动", "status": "running"}


@router.post("/build/stop")
async def stop_build():
    """停止构建"""
    # TODO: 实现优雅停止 (需要向 Manager 发送取消信号)
    # 目前只能重置状态标记，无法强行杀死线程
    global _is_building
    if _is_building:
        # 这里只是逻辑上的停止，实际后台任务可能还在跑
        # 真正的停止需要 V2 Manager 支持 CancelToken
        return {"message": "停止指令已发送 (注意：当前后台任务可能无法立即中断)"}
    return {"message": "没有正在运行的构建任务"}


@router.get("/build/status")
async def get_build_status():
    """获取构建状态 (从 ProgressManager 获取)"""
    # 结合全局锁状态和进度管理器的状态
    status = get_progress_manager().get_current_status()
    status["is_running"] = _is_building
    return status


# ==================== 统计与文件 API ====================

@router.get("/graph/stats")
async def get_graph_stats():
    """获取图谱统计信息"""
    logger.info("收到图谱统计请求")
    try:
        # 查询实体数量
        entity_count_query = "MATCH (n) RETURN count(n) as count"
        entity_result = connection_manager.execute_query(entity_count_query)
        entity_count = entity_result[0]['count'] if entity_result else 0

        # 查询关系数量
        relationship_count_query = "MATCH ()-[r]->() RETURN count(r) as count"
        relationship_result = connection_manager.execute_query(relationship_count_query)
        relationship_count = relationship_result[0]['count'] if relationship_result else 0

        # 查询社区数量
        community_count_query = "MATCH (n) WHERE n.community_id IS NOT NULL RETURN count(DISTINCT n.community_id) as count"
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
            "last_build_time": datetime.now().isoformat() if entity_count > 0 else None
        }
    except Exception as e:
        logger.error(f"获取图谱统计失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取图谱统计失败: {str(e)}")


@router.get("/health")
async def health_check():
    """健康检查"""
    try:
        connection_manager.execute_query("RETURN 1")
        neo4j_status = "healthy"
    except:
        neo4j_status = "unhealthy"
    return {"status": "ok", "neo4j": neo4j_status, "timestamp": datetime.now().isoformat()}


@router.get("/files/list")
async def list_files():
    """列出所有已上传的文档"""
    try:
        files_dir = Path(FILES_DIR)
        if not files_dir.exists():
            files_dir.mkdir(parents=True, exist_ok=True)
            return {"files": [], "count": 0}

        files = []
        for file_path in files_dir.iterdir():
            if file_path.is_file():
                stat = file_path.stat()
                files.append({
                    "name": file_path.name,
                    "path": str(file_path),
                    "size": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        files.sort(key=lambda x: x["modified_at"], reverse=True)
        return {"files": files, "count": len(files), "directory": str(files_dir)}
    except Exception as e:
        logger.error(f"获取文件列表失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取文件列表失败: {str(e)}")


# ==================== 图谱配置管理 API ====================

@router.get("/graph/config")
async def get_graph_config():
    """获取当前图谱配置"""
    logger.info("收到获取图谱配置请求")

    try:
        storage = get_storage()
        config = storage.load()

        if config is None:
            logger.info("当前无配置，返回空")
            return {"exists": False, "config": None}

        logger.info(f"返回配置: {config.project_name}")
        return {
            "exists": True,
            "config": config.model_dump(mode='json')
        }

    except Exception as e:
        logger.error(f"获取图谱配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.post("/graph/config")
async def save_graph_config(config: GraphConfig):
    """保存图谱配置"""
    logger.info(f"收到保存图谱配置请求: {config.project_name}")

    try:
        storage = get_storage()
        success = storage.save(config)

        if success:
            logger.info(f"配置保存成功: {config.project_name}")
            return {"message": "配置保存成功", "project_name": config.project_name}
        else:
            logger.error("配置保存失败")
            raise HTTPException(status_code=500, detail="配置保存失败")

    except Exception as e:
        logger.error(f"保存图谱配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存配置失败: {str(e)}")


@router.delete("/graph/config")
async def delete_graph_config():
    """删除图谱配置"""
    logger.info("收到删除图谱配置请求")

    try:
        storage = get_storage()
        success = storage.delete()

        if success:
            logger.info("配置删除成功")
            return {"message": "配置删除成功"}
        else:
            logger.error("配置删除失败")
            raise HTTPException(status_code=500, detail="配置删除失败")

    except Exception as e:
        logger.error(f"删除图谱配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除配置失败: {str(e)}")


@router.get("/graph/templates")
async def list_graph_templates():
    """列出所有可用的行业模板"""
    logger.info("收到列出模板请求")

    try:
        storage = get_storage()
        templates = storage.list_templates()

        logger.info(f"返回 {len(templates)} 个模板")
        return {"templates": templates}

    except Exception as e:
        logger.error(f"列出模板失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"列出模板失败: {str(e)}")


@router.get("/graph/templates/{template_name}")
async def get_graph_template(template_name: str):
    """获取指定模板的详细信息"""
    logger.info(f"收到获取模板请求: {template_name}")

    try:
        storage = get_storage()
        config = storage.load_template(template_name)

        if config is None:
            logger.warning(f"模板不存在: {template_name}")
            raise HTTPException(status_code=404, detail=f"模板 '{template_name}' 不存在")

        logger.info(f"返回模板: {template_name}")
        return {"config": config.model_dump(mode='json')}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取模板失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取模板失败: {str(e)}")


@router.post("/graph/config/from-template")
async def create_config_from_template(
    template_name: str,
    project_name: Optional[str] = None,
    created_by: Optional[str] = None
):
    """从模板创建并保存配置"""
    logger.info(f"收到从模板创建配置请求: {template_name}")

    try:
        storage = get_storage()
        success = storage.save_from_template(
            template_name=template_name,
            project_name=project_name,
            created_by=created_by
        )

        if success:
            logger.info(f"从模板创建配置成功: {template_name}")
            return {
                "message": "配置创建成功",
                "template_name": template_name,
                "project_name": project_name or f"{template_name}_project"
            }
        else:
            logger.error(f"模板不存在或保存失败: {template_name}")
            raise HTTPException(
                status_code=400,
                detail=f"模板 '{template_name}' 不存在或保存失败"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"从模板创建配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"从模板创建配置失败: {str(e)}")


# ==================== AI Copilot API ====================

@router.post("/ai-copilot/analyze-documents")
async def analyze_documents_for_config(
    industry_hint: Optional[str] = None,
    num_clusters: Optional[int] = None
):
    """
    分析已上传的文档，生成配置推荐

    Args:
        industry_hint: 行业提示（可选）
        num_clusters: 聚类数量（可选，默认自动确定）

    Returns:
        文档分析结果和配置推荐
    """
    logger.info("收到 AI Copilot 文档分析请求")

    try:
        from graphrag_agent.models.get_models import get_llm_model, get_embeddings_model
        from graphrag_agent.ai_copilot import DocumentAnalyzer
        from graphrag_agent.pipelines.ingestion.document_processor import DocumentProcessor
        from graphrag_agent.config.settings import FILES_DIR, CHUNK_SIZE, OVERLAP

        # 初始化模型
        llm = get_llm_model()
        embeddings = get_embeddings_model()

        # 创建文档分析器
        analyzer = DocumentAnalyzer(llm, embeddings)

        # 读取文档
        doc_processor = DocumentProcessor(FILES_DIR, CHUNK_SIZE, OVERLAP)
        processed_docs = doc_processor.process_directory()

        if not processed_docs:
            logger.warning("没有找到可分析的文档")
            raise HTTPException(status_code=400, detail="没有找到可分析的文档，请先上传文档")

        # 准备文档数据
        documents = [
            {
                "filename": doc["filename"],
                "content": doc["content"]
            }
            for doc in processed_docs
        ]

        logger.info(f"开始分析 {len(documents)} 个文档")

        # 分析文档
        analysis_result = analyzer.analyze_documents(documents, num_clusters)

        logger.info(f"文档分析完成，聚类数: {len(analysis_result['clusters'])}")

        # 生成推荐
        logger.info("开始生成配置推荐")
        recommendations = analyzer.recommend_domains_and_bridges(analysis_result, industry_hint)

        logger.info("配置推荐生成完成")

        return {
            "analysis": analysis_result,
            "recommendations": recommendations
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI Copilot 分析失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文档分析失败: {str(e)}")


@router.post("/ai-copilot/refine-config")
async def refine_configuration(
    user_feedback: str,
    current_config: Optional[Dict] = None
):
    """
    基于用户反馈优化配置

    Args:
        user_feedback: 用户反馈
        current_config: 当前配置（可选，如果为空则从存储加载）

    Returns:
        优化后的配置
    """
    logger.info("收到 AI Copilot 配置优化请求")

    try:
        from graphrag_agent.models.get_models import get_llm_model, get_embeddings_model
        from graphrag_agent.ai_copilot import DocumentAnalyzer

        # 初始化模型
        llm = get_llm_model()
        embeddings = get_embeddings_model()

        # 创建文档分析器
        analyzer = DocumentAnalyzer(llm, embeddings)

        # 获取当前配置
        if current_config is None:
            storage = get_storage()
            config_obj = storage.load()
            if config_obj is None:
                raise HTTPException(status_code=400, detail="当前无配置，请先创建配置")
            current_config = config_obj.model_dump(mode='json')

        logger.info(f"开始优化配置，用户反馈: {user_feedback[:100]}...")

        # 优化配置
        refined_config = analyzer.refine_recommendations(current_config, user_feedback)

        logger.info("配置优化完成")

        return refined_config

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI Copilot 配置优化失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"配置优化失败: {str(e)}")


@router.post("/ai-copilot/apply-recommendations")
async def apply_ai_recommendations(
    recommendations: Dict,
    project_name: str,
    industry: Optional[str] = None,
    description: Optional[str] = None
):
    """
    将 AI 推荐应用为新配置

    Args:
        recommendations: AI 推荐结果
        project_name: 项目名称
        industry: 行业
        description: 项目描述

    Returns:
        创建的配置
    """
    logger.info(f"收到应用 AI 推荐请求: {project_name}")

    try:
        # 构建配置
        config_dict = {
            "project_name": project_name,
            "version": "1.0",
            "description": description or "基于 AI 推荐创建",
            "industry": industry or "通用",
            "bridge_definitions": recommendations.get("recommended_bridges", []),
            "domain_definitions": recommendations.get("recommended_domains", [])
        }

        # 验证并保存
        config = GraphConfig(**config_dict)
        storage = get_storage()
        success = storage.save(config)

        if success:
            logger.info(f"AI 推荐配置已保存: {project_name}")
            return {
                "message": "配置创建成功",
                "config": config.model_dump(mode='json')
            }
        else:
            raise HTTPException(status_code=500, detail="配置保存失败")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"应用 AI 推荐失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"应用推荐失败: {str(e)}")
