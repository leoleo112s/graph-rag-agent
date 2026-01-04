"""
反馈管理 API

提供反馈的提交、审核、应用等管理功能。
支持实体合并、关系纠错等多种反馈类型的自动化应用。
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from server.models.feedback_models import (
    DetailedFeedbackRequest,
    FeedbackDB,
    FeedbackRecord,
    FeedbackReviewRequest,
    FeedbackStatus,
    FeedbackType,
    get_feedback_db,
)
from server.services.kg_service import get_neo4j_driver

router = APIRouter(prefix="/admin/feedback", tags=["feedback_admin"])
logger = logging.getLogger(__name__)


@router.post("/detailed")
async def submit_detailed_feedback(request: DetailedFeedbackRequest) -> Dict[str, Any]:
    """
    提交详细反馈

    支持多种反馈类型：
    - answer_rating: 回答评分
    - entity_merge: 实体合并建议
    - relation_correction: 关系纠错
    - missing_entity: 缺失实体报告
    - hallucination: 幻觉实体检测
    - entity_error: 实体信息错误
    - config_suggestion: 配置优化建议
    """
    try:
        db = get_feedback_db()
        record_id = db.create_record(
            feedback_type=request.type,
            description=request.description,
            content=request.content,
            user_id=request.user_id,
            target_id=request.target_id,
            thread_id=request.thread_id,
            agent_type=request.agent_type,
        )

        return {"status": "success", "feedback_id": record_id, "message": "反馈已提交，等待审核"}

    except Exception as e:
        logger.error(f"Failed to submit feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pending")
async def get_pending_feedback(limit: int = 50, offset: int = 0, feedback_type: Optional[str] = None) -> Dict[str, Any]:
    """
    获取待审核反馈列表

    Args:
        limit: 返回数量限制
        offset: 偏移量
        feedback_type: 过滤反馈类型
    """
    try:
        db = get_feedback_db()

        # 转换类型过滤参数
        type_filter = None
        if feedback_type:
            try:
                type_filter = FeedbackType(feedback_type)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid feedback type: {feedback_type}")

        records = db.list_records(limit=limit, offset=offset, status=FeedbackStatus.PENDING, feedback_type=type_filter)

        # 获取总数
        total_pending = db.count_by_status(FeedbackStatus.PENDING)

        return {
            "records": [record.model_dump() for record in records],
            "total": total_pending,
            "limit": limit,
            "offset": offset,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get pending feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_all_feedback(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    feedback_type: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    列出所有反馈（支持过滤）

    Args:
        limit: 返回数量限制
        offset: 偏移量
        status: 过滤状态
        feedback_type: 过滤反馈类型
        user_id: 过滤用户ID
    """
    try:
        db = get_feedback_db()

        # 转换枚举参数
        status_filter = None
        if status:
            try:
                status_filter = FeedbackStatus(status)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

        type_filter = None
        if feedback_type:
            try:
                type_filter = FeedbackType(feedback_type)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid feedback type: {feedback_type}")

        records = db.list_records(
            limit=limit, offset=offset, status=status_filter, feedback_type=type_filter, user_id=user_id
        )

        return {"records": [record.model_dump() for record in records], "limit": limit, "offset": offset}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics")
async def get_feedback_statistics() -> Dict[str, Any]:
    """
    获取反馈统计信息
    """
    try:
        db = get_feedback_db()
        stats = db.get_statistics()
        return stats

    except Exception as e:
        logger.error(f"Failed to get feedback statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{feedback_id}")
async def get_feedback_detail(feedback_id: str) -> Dict[str, Any]:
    """
    获取反馈详情

    Args:
        feedback_id: 反馈ID
    """
    try:
        db = get_feedback_db()
        record = db.get_record(feedback_id)

        if not record:
            raise HTTPException(status_code=404, detail="Feedback not found")

        return record.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get feedback detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{feedback_id}/review")
async def review_feedback(feedback_id: str, request: FeedbackReviewRequest) -> Dict[str, Any]:
    """
    审核反馈

    Args:
        feedback_id: 反馈ID
        request: 审核请求（action: approve/reject, note: 审核备注）
    """
    try:
        db = get_feedback_db()

        # 验证反馈是否存在
        record = db.get_record(feedback_id)
        if not record:
            raise HTTPException(status_code=404, detail="Feedback not found")

        # 验证状态
        if record.status != FeedbackStatus.PENDING:
            raise HTTPException(status_code=400, detail=f"Cannot review feedback with status: {record.status}")

        # 更新状态
        if request.action == "approve":
            new_status = FeedbackStatus.APPROVED
        elif request.action == "reject":
            new_status = FeedbackStatus.REJECTED
        else:
            raise HTTPException(
                status_code=400, detail=f"Invalid action: {request.action}. Must be 'approve' or 'reject'"
            )

        db.update_status(
            record_id=feedback_id, status=new_status, reviewer_id=request.reviewer_id, review_note=request.note
        )

        return {
            "status": "success",
            "feedback_id": feedback_id,
            "action": request.action,
            "new_status": new_status.value,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to review feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{feedback_id}/apply")
async def apply_feedback(feedback_id: str) -> Dict[str, Any]:
    """
    应用反馈到知识图谱

    根据反馈类型执行相应的图谱操作：
    - entity_merge: 合并实体（使用 APOC）
    - relation_correction: 修正关系
    - entity_error: 更新实体信息
    - hallucination: 删除幻觉实体

    注意：只能应用已批准的反馈
    """
    try:
        db = get_feedback_db()

        # 验证反馈是否存在
        record = db.get_record(feedback_id)
        if not record:
            raise HTTPException(status_code=404, detail="Feedback not found")

        # 验证状态
        if record.status != FeedbackStatus.APPROVED:
            raise HTTPException(
                status_code=400, detail=f"Cannot apply feedback with status: {record.status}. Must be APPROVED first."
            )

        # 根据类型应用反馈
        driver = get_neo4j_driver()
        result = None

        if record.type == FeedbackType.ENTITY_MERGE:
            result = _apply_entity_merge(driver, record)

        elif record.type == FeedbackType.RELATION_CORRECTION:
            result = _apply_relation_correction(driver, record)

        elif record.type == FeedbackType.ENTITY_ERROR:
            result = _apply_entity_update(driver, record)

        elif record.type == FeedbackType.HALLUCINATION:
            result = _apply_entity_deletion(driver, record)

        else:
            raise HTTPException(status_code=400, detail=f"Cannot auto-apply feedback type: {record.type}")

        # 更新状态为已应用
        db.update_status(record_id=feedback_id, status=FeedbackStatus.APPLIED)

        return {"status": "success", "feedback_id": feedback_id, "applied_action": record.type.value, "result": result}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to apply feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 反馈应用辅助函数 ==========


def _apply_entity_merge(driver, record: FeedbackRecord) -> Dict[str, Any]:
    """
    应用实体合并反馈

    使用 Neo4j APOC 的 apoc.refactor.mergeNodes 功能
    """
    content = record.content
    from_id = content.get("merge_from")
    to_id = content.get("merge_to")

    if not from_id or not to_id:
        raise HTTPException(status_code=400, detail="Missing merge_from or merge_to in content")

    # 使用 APOC 合并节点（如果可用）
    # 如果不可用，则手动合并
    query = """
    MATCH (from:__Entity__ {id: $from_id})
    MATCH (to:__Entity__ {id: $to_id})

    // 复制所有关系到目标节点
    WITH from, to
    OPTIONAL MATCH (from)-[r]->(other)
    WHERE NOT (to)-[]->(other)
    WITH from, to, r, other, type(r) as relType, properties(r) as relProps
    FOREACH (_ IN CASE WHEN other IS NOT NULL THEN [1] ELSE [] END |
        CREATE (to)-[new_rel:relType]->(other)
        SET new_rel = relProps
    )

    WITH from, to
    OPTIONAL MATCH (other)-[r]->(from)
    WHERE NOT (other)-[]->(to)
    WITH from, to, r, other, type(r) as relType, properties(r) as relProps
    FOREACH (_ IN CASE WHEN other IS NOT NULL THEN [1] ELSE [] END |
        CREATE (other)-[new_rel:relType]->(to)
        SET new_rel = relProps
    )

    // 删除源节点
    WITH from, to
    DETACH DELETE from

    RETURN to.id as merged_id, to.name as merged_name
    """

    with driver.session() as session:
        result = session.run(query, from_id=from_id, to_id=to_id)
        record_result = result.single()

        if record_result:
            return {
                "merged_id": record_result["merged_id"],
                "merged_name": record_result["merged_name"],
                "message": f"Successfully merged {from_id} into {to_id}",
            }
        else:
            return {"message": "Merge completed but no result returned"}


def _apply_relation_correction(driver, record: FeedbackRecord) -> Dict[str, Any]:
    """
    应用关系纠错反馈

    删除错误关系，创建正确关系
    """
    content = record.content
    source = content.get("source")
    target = content.get("target")
    old_type = content.get("old_type")
    new_type = content.get("new_type")
    new_description = content.get("description", "")
    new_weight = content.get("weight", 0.5)

    if not all([source, target, old_type, new_type]):
        raise HTTPException(status_code=400, detail="Missing required fields: source, target, old_type, new_type")

    query = """
    MATCH (s:__Entity__ {id: $source})
    MATCH (t:__Entity__ {id: $target})
    MATCH (s)-[old_rel]->(t)
    WHERE type(old_rel) = $old_type

    DELETE old_rel

    WITH s, t
    CALL apoc.create.relationship(s, $new_type, {
        description: $description,
        weight: $weight
    }, t) YIELD rel

    RETURN s.id as source_id, t.id as target_id, type(rel) as new_relation_type
    """

    with driver.session() as session:
        result = session.run(
            query,
            source=source,
            target=target,
            old_type=old_type,
            new_type=new_type,
            description=new_description,
            weight=new_weight,
        )
        record_result = result.single()

        if record_result:
            return {
                "source": record_result["source_id"],
                "target": record_result["target_id"],
                "new_relation_type": record_result["new_relation_type"],
                "message": f"Successfully corrected relation from {old_type} to {new_type}",
            }
        else:
            return {"message": "Relation correction completed"}


def _apply_entity_update(driver, record: FeedbackRecord) -> Dict[str, Any]:
    """
    应用实体信息更新反馈
    """
    content = record.content
    entity_id = record.target_id or content.get("entity_id")
    updates = content.get("updates", {})

    if not entity_id or not updates:
        raise HTTPException(status_code=400, detail="Missing entity_id or updates in content")

    # 构建 SET 子句
    set_clauses = []
    params = {"entity_id": entity_id}

    for key, value in updates.items():
        if key in ["name", "type", "description"]:
            set_clauses.append(f"e.{key} = ${key}")
            params[key] = value

    if not set_clauses:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    query = f"""
    MATCH (e:__Entity__ {{id: $entity_id}})
    SET {', '.join(set_clauses)}
    RETURN e.id as id, e.name as name, e.type as type
    """

    with driver.session() as session:
        result = session.run(query, **params)
        record_result = result.single()

        if record_result:
            return {
                "entity_id": record_result["id"],
                "name": record_result["name"],
                "type": record_result["type"],
                "message": "Successfully updated entity",
            }
        else:
            raise HTTPException(status_code=404, detail="Entity not found")


def _apply_entity_deletion(driver, record: FeedbackRecord) -> Dict[str, Any]:
    """
    应用实体删除反馈（幻觉实体）
    """
    entity_id = record.target_id or record.content.get("entity_id")

    if not entity_id:
        raise HTTPException(status_code=400, detail="Missing entity_id")

    query = """
    MATCH (e:__Entity__ {id: $entity_id})
    DETACH DELETE e
    RETURN $entity_id as deleted_id
    """

    with driver.session() as session:
        result = session.run(query, entity_id=entity_id)
        record_result = result.single()

        if record_result:
            return {"deleted_id": record_result["deleted_id"], "message": "Successfully deleted hallucination entity"}
        else:
            raise HTTPException(status_code=404, detail="Entity not found")
