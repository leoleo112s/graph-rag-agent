"""
精细化反馈系统数据模型

支持多种反馈类型：整体评分、实体合并、关系纠错、缺失实体、幻觉检测等。
包含完整的审核工作流：提交 → 待审核 → 批准/拒绝 → 应用。
"""

import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field


class FeedbackType(str, Enum):
    """反馈类型枚举"""
    ANSWER_RATING = "answer_rating"  # 回答评分（原有的点赞/点踩）
    ENTITY_MERGE = "entity_merge"  # 实体合并建议
    RELATION_CORRECTION = "relation_correction"  # 关系纠错
    MISSING_ENTITY = "missing_entity"  # 缺失实体报告
    HALLUCINATION = "hallucination"  # 幻觉实体检测
    ENTITY_ERROR = "entity_error"  # 实体信息错误
    CONFIG_SUGGESTION = "config_suggestion"  # 配置优化建议


class FeedbackStatus(str, Enum):
    """反馈状态枚举"""
    PENDING = "pending"  # 待审核
    APPROVED = "approved"  # 已批准
    REJECTED = "rejected"  # 已拒绝
    APPLIED = "applied"  # 已应用到图谱


class DetailedFeedbackRequest(BaseModel):
    """详细反馈请求模型"""
    type: FeedbackType
    target_id: Optional[str] = None  # MessageID 或 EntityID 或 RelationKey
    content: Dict[str, Any] = Field(default_factory=dict)  # 类型相关的内容
    description: str  # 用户描述
    user_id: str = "anonymous"
    thread_id: Optional[str] = None  # 会话ID
    agent_type: Optional[str] = None


class FeedbackReviewRequest(BaseModel):
    """反馈审核请求模型"""
    action: str  # "approve" 或 "reject"
    note: Optional[str] = None  # 审核备注
    reviewer_id: str = "admin"


class FeedbackRecord(BaseModel):
    """反馈记录模型"""
    id: str
    type: FeedbackType
    target_id: Optional[str] = None
    content: Dict[str, Any]
    description: str
    status: FeedbackStatus
    user_id: str
    thread_id: Optional[str] = None
    agent_type: Optional[str] = None
    created_at: str
    reviewed_at: Optional[str] = None
    reviewer_id: Optional[str] = None
    review_note: Optional[str] = None
    applied_at: Optional[str] = None


class FeedbackDB:
    """反馈数据库管理器"""

    def __init__(self, db_path: str = "./data/feedback.db"):
        """
        初始化数据库

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback_records (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    target_id TEXT,
                    content TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    thread_id TEXT,
                    agent_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TIMESTAMP,
                    reviewer_id TEXT,
                    review_note TEXT,
                    applied_at TIMESTAMP
                )
            """)
            # 创建索引以加速查询
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status
                ON feedback_records(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_type
                ON feedback_records(type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at
                ON feedback_records(created_at DESC)
            """)
            conn.commit()

    def create_record(
        self,
        feedback_type: FeedbackType,
        description: str,
        content: Dict[str, Any],
        user_id: str = "anonymous",
        target_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        agent_type: Optional[str] = None
    ) -> str:
        """
        创建新的反馈记录

        Args:
            feedback_type: 反馈类型
            description: 用户描述
            content: 反馈内容（JSON）
            user_id: 用户ID
            target_id: 目标ID
            thread_id: 会话ID
            agent_type: 代理类型

        Returns:
            反馈记录ID
        """
        record_id = str(uuid.uuid4())
        created_at = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO feedback_records
                (id, type, target_id, content, description, status, user_id,
                 thread_id, agent_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    feedback_type.value,
                    target_id,
                    json.dumps(content, ensure_ascii=False),
                    description,
                    FeedbackStatus.PENDING.value,
                    user_id,
                    thread_id,
                    agent_type,
                    created_at
                )
            )
            conn.commit()

        return record_id

    def update_status(
        self,
        record_id: str,
        status: FeedbackStatus,
        reviewer_id: Optional[str] = None,
        review_note: Optional[str] = None
    ):
        """
        更新反馈状态

        Args:
            record_id: 记录ID
            status: 新状态
            reviewer_id: 审核人ID
            review_note: 审核备注
        """
        fields = ["status = ?"]
        values = [status.value]

        # 如果状态变为批准或拒绝，记录审核时间
        if status in [FeedbackStatus.APPROVED, FeedbackStatus.REJECTED]:
            reviewed_at = datetime.now().isoformat()
            fields.append("reviewed_at = ?")
            values.append(reviewed_at)

        if reviewer_id:
            fields.append("reviewer_id = ?")
            values.append(reviewer_id)

        if review_note:
            fields.append("review_note = ?")
            values.append(review_note)

        # 如果状态变为已应用，记录应用时间
        if status == FeedbackStatus.APPLIED:
            applied_at = datetime.now().isoformat()
            fields.append("applied_at = ?")
            values.append(applied_at)

        query = f"UPDATE feedback_records SET {', '.join(fields)} WHERE id = ?"
        values.append(record_id)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(query, values)
            conn.commit()

    def get_record(self, record_id: str) -> Optional[FeedbackRecord]:
        """
        获取单条反馈记录

        Args:
            record_id: 记录ID

        Returns:
            反馈记录或None
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM feedback_records WHERE id = ?",
                (record_id,)
            )
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_record(row)

    def list_records(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[FeedbackStatus] = None,
        feedback_type: Optional[FeedbackType] = None,
        user_id: Optional[str] = None
    ) -> List[FeedbackRecord]:
        """
        列出反馈记录

        Args:
            limit: 返回数量限制
            offset: 偏移量
            status: 过滤状态
            feedback_type: 过滤反馈类型
            user_id: 过滤用户ID

        Returns:
            反馈记录列表
        """
        query = "SELECT * FROM feedback_records WHERE 1=1"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status.value)

        if feedback_type:
            query += " AND type = ?"
            params.append(feedback_type.value)

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_record(row) for row in rows]

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取反馈统计信息

        Returns:
            统计数据字典
        """
        with sqlite3.connect(self.db_path) as conn:
            # 总反馈数
            total = conn.execute("SELECT COUNT(*) FROM feedback_records").fetchone()[0]

            # 各状态统计
            pending = conn.execute(
                "SELECT COUNT(*) FROM feedback_records WHERE status = ?",
                (FeedbackStatus.PENDING.value,)
            ).fetchone()[0]

            approved = conn.execute(
                "SELECT COUNT(*) FROM feedback_records WHERE status = ?",
                (FeedbackStatus.APPROVED.value,)
            ).fetchone()[0]

            rejected = conn.execute(
                "SELECT COUNT(*) FROM feedback_records WHERE status = ?",
                (FeedbackStatus.REJECTED.value,)
            ).fetchone()[0]

            applied = conn.execute(
                "SELECT COUNT(*) FROM feedback_records WHERE status = ?",
                (FeedbackStatus.APPLIED.value,)
            ).fetchone()[0]

            # 各类型统计
            type_stats = {}
            cursor = conn.execute(
                "SELECT type, COUNT(*) as count FROM feedback_records GROUP BY type"
            )
            for row in cursor:
                type_stats[row[0]] = row[1]

            return {
                "total_feedbacks": total,
                "pending_feedbacks": pending,
                "approved_feedbacks": approved,
                "rejected_feedbacks": rejected,
                "applied_feedbacks": applied,
                "approval_rate": round(approved / total * 100, 2) if total > 0 else 0,
                "type_distribution": type_stats
            }

    def count_by_status(self, status: FeedbackStatus) -> int:
        """
        统计指定状态的反馈数量

        Args:
            status: 状态

        Returns:
            数量
        """
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM feedback_records WHERE status = ?",
                (status.value,)
            ).fetchone()[0]
            return count

    def _row_to_record(self, row: sqlite3.Row) -> FeedbackRecord:
        """
        将数据库行转换为FeedbackRecord对象

        Args:
            row: 数据库行

        Returns:
            FeedbackRecord对象
        """
        return FeedbackRecord(
            id=row["id"],
            type=row["type"],
            target_id=row["target_id"],
            content=json.loads(row["content"]) if row["content"] else {},
            description=row["description"],
            status=row["status"],
            user_id=row["user_id"],
            thread_id=row["thread_id"],
            agent_type=row["agent_type"],
            created_at=row["created_at"],
            reviewed_at=row["reviewed_at"],
            reviewer_id=row["reviewer_id"],
            review_note=row["review_note"],
            applied_at=row["applied_at"]
        )


# 全局单例
_feedback_db: Optional[FeedbackDB] = None


def get_feedback_db() -> FeedbackDB:
    """
    获取全局反馈数据库实例

    Returns:
        FeedbackDB 单例
    """
    global _feedback_db
    if _feedback_db is None:
        _feedback_db = FeedbackDB()
    return _feedback_db
