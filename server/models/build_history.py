"""
构建历史记录模型

使用 SQLite 存储构建任务的历史记录，支持查询、统计和错误追踪。
"""

import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel


class BuildStatus(str, Enum):
    """构建状态枚举"""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BuildType(str, Enum):
    """构建类型枚举"""
    FULL = "full"
    INCREMENTAL = "incremental"


class BuildStage(str, Enum):
    """构建阶段枚举（标准化）"""
    IDLE = "idle"
    INITIALIZING = "initializing"
    DETECTING_CHANGES = "detecting_changes"
    CHUNKING = "chunking"
    ENTITY_EXTRACTION = "entity_extraction"
    ENTITY_DISAMBIGUATION = "entity_disambiguation"
    INDEXING = "indexing"
    COMMUNITY_DETECTION = "community_detection"
    COMPLETED = "completed"
    FAILED = "failed"


class BuildRecord(BaseModel):
    """构建记录模型"""
    id: str
    task_type: BuildType
    status: BuildStatus
    start_time: str
    end_time: Optional[str] = None
    duration: Optional[int] = None  # 秒
    config_snapshot: Optional[Dict[str, Any]] = None
    error_msg: Optional[str] = None
    stats: Optional[Dict[str, int]] = None
    final_stage: Optional[str] = None


class BuildHistoryDB:
    """构建历史数据库管理器"""

    def __init__(self, db_path: str = "./data/build_history.db"):
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
                CREATE TABLE IF NOT EXISTS build_records (
                    id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    duration INTEGER,
                    config_snapshot TEXT,
                    error_msg TEXT,
                    stats TEXT,
                    final_stage TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def create_record(
        self,
        task_type: BuildType,
        config_snapshot: Optional[Dict] = None
    ) -> str:
        """
        创建新的构建记录

        Args:
            task_type: 构建类型
            config_snapshot: 配置快照

        Returns:
            构建记录ID
        """
        record_id = str(uuid.uuid4())
        start_time = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO build_records
                (id, task_type, status, start_time, config_snapshot)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    task_type.value,
                    BuildStatus.RUNNING.value,
                    start_time,
                    json.dumps(config_snapshot) if config_snapshot else None
                )
            )
            conn.commit()

        return record_id

    def update_record(
        self,
        record_id: str,
        status: Optional[BuildStatus] = None,
        error_msg: Optional[str] = None,
        stats: Optional[Dict[str, int]] = None,
        final_stage: Optional[str] = None
    ):
        """
        更新构建记录

        Args:
            record_id: 记录ID
            status: 构建状态
            error_msg: 错误信息
            stats: 统计数据
            final_stage: 最终阶段
        """
        fields = []
        values = []

        if status:
            fields.append("status = ?")
            values.append(status.value)

            # 如果状态变为完成或失败，记录结束时间和持续时间
            if status in [BuildStatus.COMPLETED, BuildStatus.FAILED, BuildStatus.CANCELLED]:
                end_time = datetime.now().isoformat()
                fields.append("end_time = ?")
                values.append(end_time)

                # 计算持续时间
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute(
                        "SELECT start_time FROM build_records WHERE id = ?",
                        (record_id,)
                    )
                    row = cursor.fetchone()
                    if row:
                        start = datetime.fromisoformat(row[0])
                        end = datetime.fromisoformat(end_time)
                        duration = int((end - start).total_seconds())
                        fields.append("duration = ?")
                        values.append(duration)

        if error_msg:
            fields.append("error_msg = ?")
            values.append(error_msg)

        if stats:
            fields.append("stats = ?")
            values.append(json.dumps(stats))

        if final_stage:
            fields.append("final_stage = ?")
            values.append(final_stage)

        if not fields:
            return

        query = f"UPDATE build_records SET {', '.join(fields)} WHERE id = ?"
        values.append(record_id)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(query, values)
            conn.commit()

    def get_record(self, record_id: str) -> Optional[BuildRecord]:
        """
        获取单条构建记录

        Args:
            record_id: 记录ID

        Returns:
            构建记录或None
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM build_records WHERE id = ?",
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
        status: Optional[BuildStatus] = None,
        task_type: Optional[BuildType] = None
    ) -> List[BuildRecord]:
        """
        列出构建记录

        Args:
            limit: 返回数量限制
            offset: 偏移量
            status: 过滤状态
            task_type: 过滤构建类型

        Returns:
            构建记录列表
        """
        query = "SELECT * FROM build_records WHERE 1=1"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status.value)

        if task_type:
            query += " AND task_type = ?"
            params.append(task_type.value)

        query += " ORDER BY start_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_record(row) for row in rows]

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取构建统计信息

        Returns:
            统计数据字典
        """
        with sqlite3.connect(self.db_path) as conn:
            # 总构建次数
            total = conn.execute("SELECT COUNT(*) FROM build_records").fetchone()[0]

            # 成功/失败次数
            completed = conn.execute(
                "SELECT COUNT(*) FROM build_records WHERE status = ?",
                (BuildStatus.COMPLETED.value,)
            ).fetchone()[0]

            failed = conn.execute(
                "SELECT COUNT(*) FROM build_records WHERE status = ?",
                (BuildStatus.FAILED.value,)
            ).fetchone()[0]

            # 平均构建时长（秒）
            avg_duration = conn.execute(
                "SELECT AVG(duration) FROM build_records WHERE duration IS NOT NULL"
            ).fetchone()[0]

            # 最近一次构建
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM build_records ORDER BY start_time DESC LIMIT 1"
            )
            last_build_row = cursor.fetchone()
            last_build = self._row_to_record(last_build_row) if last_build_row else None

            return {
                "total_builds": total,
                "completed_builds": completed,
                "failed_builds": failed,
                "success_rate": round(completed / total * 100, 2) if total > 0 else 0,
                "avg_duration_seconds": int(avg_duration) if avg_duration else 0,
                "last_build": last_build.model_dump() if last_build else None
            }

    def _row_to_record(self, row: sqlite3.Row) -> BuildRecord:
        """
        将数据库行转换为BuildRecord对象

        Args:
            row: 数据库行

        Returns:
            BuildRecord对象
        """
        return BuildRecord(
            id=row["id"],
            task_type=row["task_type"],
            status=row["status"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            duration=row["duration"],
            config_snapshot=json.loads(row["config_snapshot"]) if row["config_snapshot"] else None,
            error_msg=row["error_msg"],
            stats=json.loads(row["stats"]) if row["stats"] else None,
            final_stage=row["final_stage"]
        )


# 全局单例
_build_history_db: Optional[BuildHistoryDB] = None


def get_build_history_db() -> BuildHistoryDB:
    """
    获取全局构建历史数据库实例

    Returns:
        BuildHistoryDB 单例
    """
    global _build_history_db
    if _build_history_db is None:
        _build_history_db = BuildHistoryDB()
    return _build_history_db
