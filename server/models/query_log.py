"""
问答查询日志模型

使用 SQLite 存储问答查询的历史记录，支持性能监控、Token 统计和用户反馈跟踪。
"""

import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel


class QueryLog(BaseModel):
    """查询日志模型"""
    id: str
    question: str
    agent_type: str
    session_id: str
    message_id: Optional[str] = None
    response_time: float  # 秒
    token_usage: Optional[Dict[str, int]] = None  # {"prompt": 100, "completion": 50, "total": 150}
    feedback_score: Optional[int] = None  # 1 (positive) or -1 (negative)
    retriever_type: Optional[str] = None  # naive, graph, hybrid, deep_research
    search_time: Optional[float] = None  # 秒
    llm_time: Optional[float] = None  # 秒
    cache_hit: Optional[bool] = None
    created_at: str
    updated_at: Optional[str] = None


class QueryLogDB:
    """查询日志数据库管理器"""

    def __init__(self, db_path: str = "./data/query_log.db"):
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
                CREATE TABLE IF NOT EXISTS query_logs (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    message_id TEXT,
                    response_time REAL NOT NULL,
                    token_usage TEXT,
                    feedback_score INTEGER,
                    retriever_type TEXT,
                    search_time REAL,
                    llm_time REAL,
                    cache_hit INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP
                )
            """)
            # 创建索引以加速查询
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at
                ON query_logs(created_at DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_type
                ON query_logs(agent_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_id
                ON query_logs(session_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_feedback_score
                ON query_logs(feedback_score)
            """)
            conn.commit()

    def create_log(
        self,
        question: str,
        agent_type: str,
        session_id: str,
        response_time: float,
        message_id: Optional[str] = None,
        token_usage: Optional[Dict[str, int]] = None,
        retriever_type: Optional[str] = None,
        search_time: Optional[float] = None,
        llm_time: Optional[float] = None,
        cache_hit: Optional[bool] = None
    ) -> str:
        """
        创建新的查询日志

        Args:
            question: 用户问题
            agent_type: 代理类型
            session_id: 会话ID
            response_time: 响应时间（秒）
            message_id: 消息ID
            token_usage: Token 使用情况
            retriever_type: 检索器类型
            search_time: 搜索时间
            llm_time: LLM 生成时间
            cache_hit: 缓存命中

        Returns:
            日志ID
        """
        log_id = str(uuid.uuid4())
        created_at = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO query_logs
                (id, question, agent_type, session_id, message_id, response_time,
                 token_usage, retriever_type, search_time, llm_time, cache_hit, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log_id,
                    question,
                    agent_type,
                    session_id,
                    message_id,
                    response_time,
                    json.dumps(token_usage) if token_usage else None,
                    retriever_type,
                    search_time,
                    llm_time,
                    1 if cache_hit else 0 if cache_hit is not None else None,
                    created_at
                )
            )
            conn.commit()

        return log_id

    def update_feedback(
        self,
        log_id: Optional[str] = None,
        message_id: Optional[str] = None,
        feedback_score: int = 1
    ):
        """
        更新查询的反馈评分

        Args:
            log_id: 日志ID（可选，如果提供 message_id）
            message_id: 消息ID（可选，如果提供 log_id）
            feedback_score: 反馈评分 (1 为正面, -1 为负面)
        """
        if not log_id and not message_id:
            raise ValueError("Must provide either log_id or message_id")

        updated_at = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            if log_id:
                conn.execute(
                    """
                    UPDATE query_logs
                    SET feedback_score = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (feedback_score, updated_at, log_id)
                )
            else:
                conn.execute(
                    """
                    UPDATE query_logs
                    SET feedback_score = ?, updated_at = ?
                    WHERE message_id = ?
                    """,
                    (feedback_score, updated_at, message_id)
                )
            conn.commit()

    def get_log(self, log_id: str) -> Optional[QueryLog]:
        """
        获取单条查询日志

        Args:
            log_id: 日志ID

        Returns:
            查询日志或None
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM query_logs WHERE id = ?",
                (log_id,)
            )
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_log(row)

    def list_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        agent_type: Optional[str] = None,
        session_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> List[QueryLog]:
        """
        列出查询日志

        Args:
            limit: 返回数量限制
            offset: 偏移量
            agent_type: 过滤代理类型
            session_id: 过滤会话ID
            start_time: 开始时间（ISO格式）
            end_time: 结束时间（ISO格式）

        Returns:
            查询日志列表
        """
        query = "SELECT * FROM query_logs WHERE 1=1"
        params = []

        if agent_type:
            query += " AND agent_type = ?"
            params.append(agent_type)

        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)

        if start_time:
            query += " AND created_at >= ?"
            params.append(start_time)

        if end_time:
            query += " AND created_at <= ?"
            params.append(end_time)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_log(row) for row in rows]

    def get_statistics(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        agent_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取查询统计信息

        Args:
            start_time: 开始时间（ISO格式）
            end_time: 结束时间（ISO格式）
            agent_type: 过滤代理类型

        Returns:
            统计数据字典
        """
        with sqlite3.connect(self.db_path) as conn:
            # 构建WHERE子句
            where_clause = "WHERE 1=1"
            params = []

            if start_time:
                where_clause += " AND created_at >= ?"
                params.append(start_time)

            if end_time:
                where_clause += " AND created_at <= ?"
                params.append(end_time)

            if agent_type:
                where_clause += " AND agent_type = ?"
                params.append(agent_type)

            # 总查询数
            total = conn.execute(
                f"SELECT COUNT(*) FROM query_logs {where_clause}",
                params
            ).fetchone()[0]

            # 平均响应时间
            avg_response_time = conn.execute(
                f"SELECT AVG(response_time) FROM query_logs {where_clause}",
                params
            ).fetchone()[0]

            # 平均搜索时间
            avg_search_time = conn.execute(
                f"SELECT AVG(search_time) FROM query_logs {where_clause} AND search_time IS NOT NULL",
                params
            ).fetchone()[0]

            # 平均LLM时间
            avg_llm_time = conn.execute(
                f"SELECT AVG(llm_time) FROM query_logs {where_clause} AND llm_time IS NOT NULL",
                params
            ).fetchone()[0]

            # 缓存命中率
            cache_hits = conn.execute(
                f"SELECT COUNT(*) FROM query_logs {where_clause} AND cache_hit = 1",
                params
            ).fetchone()[0]

            cache_total = conn.execute(
                f"SELECT COUNT(*) FROM query_logs {where_clause} AND cache_hit IS NOT NULL",
                params
            ).fetchone()[0]

            cache_hit_rate = (cache_hits / cache_total * 100) if cache_total > 0 else 0

            # 反馈统计
            positive_feedback = conn.execute(
                f"SELECT COUNT(*) FROM query_logs {where_clause} AND feedback_score = 1",
                params
            ).fetchone()[0]

            negative_feedback = conn.execute(
                f"SELECT COUNT(*) FROM query_logs {where_clause} AND feedback_score = -1",
                params
            ).fetchone()[0]

            feedback_total = positive_feedback + negative_feedback
            positive_rate = (positive_feedback / feedback_total * 100) if feedback_total > 0 else 0

            # 代理类型分布
            cursor = conn.execute(
                f"SELECT agent_type, COUNT(*) as count FROM query_logs {where_clause} GROUP BY agent_type",
                params
            )
            agent_distribution = {row[0]: row[1] for row in cursor}

            # 检索器类型分布
            cursor = conn.execute(
                f"SELECT retriever_type, COUNT(*) as count FROM query_logs {where_clause} AND retriever_type IS NOT NULL GROUP BY retriever_type",
                params
            )
            retriever_distribution = {row[0]: row[1] for row in cursor}

            # Token 统计
            cursor = conn.execute(
                f"SELECT token_usage FROM query_logs {where_clause} AND token_usage IS NOT NULL",
                params
            )
            total_tokens = 0
            for row in cursor:
                if row[0]:
                    usage = json.loads(row[0])
                    total_tokens += usage.get("total", 0)

            avg_tokens = total_tokens / total if total > 0 else 0

            return {
                "total_queries": total,
                "avg_response_time": round(avg_response_time, 3) if avg_response_time else 0,
                "avg_search_time": round(avg_search_time, 3) if avg_search_time else 0,
                "avg_llm_time": round(avg_llm_time, 3) if avg_llm_time else 0,
                "cache_hit_rate": round(cache_hit_rate, 2),
                "positive_feedback_count": positive_feedback,
                "negative_feedback_count": negative_feedback,
                "positive_feedback_rate": round(positive_rate, 2),
                "agent_distribution": agent_distribution,
                "retriever_distribution": retriever_distribution,
                "avg_tokens_per_query": round(avg_tokens, 2),
                "total_tokens": total_tokens
            }

    def get_time_series(
        self,
        metric: str = "response_time",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        interval: str = "hour",  # hour, day, week
        agent_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取时间序列数据

        Args:
            metric: 指标名称 (response_time, search_time, llm_time, token_usage)
            start_time: 开始时间
            end_time: 结束时间
            interval: 时间间隔 (hour, day, week)
            agent_type: 过滤代理类型

        Returns:
            时间序列数据
        """
        # SQLite 时间格式化
        if interval == "hour":
            time_format = "%Y-%m-%d %H:00:00"
        elif interval == "day":
            time_format = "%Y-%m-%d"
        else:  # week
            time_format = "%Y-W%W"

        where_clause = "WHERE 1=1"
        params = []

        if start_time:
            where_clause += " AND created_at >= ?"
            params.append(start_time)

        if end_time:
            where_clause += " AND created_at <= ?"
            params.append(end_time)

        if agent_type:
            where_clause += " AND agent_type = ?"
            params.append(agent_type)

        # 根据指标选择聚合函数
        if metric == "token_usage":
            # 特殊处理 JSON 字段
            query = f"""
                SELECT strftime('{time_format}', created_at) as time_bucket,
                       COUNT(*) as count
                FROM query_logs
                {where_clause}
                GROUP BY time_bucket
                ORDER BY time_bucket
            """
        else:
            query = f"""
                SELECT strftime('{time_format}', created_at) as time_bucket,
                       AVG({metric}) as avg_value,
                       MIN({metric}) as min_value,
                       MAX({metric}) as max_value,
                       COUNT(*) as count
                FROM query_logs
                {where_clause} AND {metric} IS NOT NULL
                GROUP BY time_bucket
                ORDER BY time_bucket
            """

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            results = []

            for row in cursor:
                if metric == "token_usage":
                    results.append({
                        "time": row[0],
                        "count": row[1]
                    })
                else:
                    results.append({
                        "time": row[0],
                        "avg": round(row[1], 3) if row[1] else 0,
                        "min": round(row[2], 3) if row[2] else 0,
                        "max": round(row[3], 3) if row[3] else 0,
                        "count": row[4]
                    })

            return results

    def _row_to_log(self, row: sqlite3.Row) -> QueryLog:
        """
        将数据库行转换为QueryLog对象

        Args:
            row: 数据库行

        Returns:
            QueryLog对象
        """
        return QueryLog(
            id=row["id"],
            question=row["question"],
            agent_type=row["agent_type"],
            session_id=row["session_id"],
            message_id=row["message_id"],
            response_time=row["response_time"],
            token_usage=json.loads(row["token_usage"]) if row["token_usage"] else None,
            feedback_score=row["feedback_score"],
            retriever_type=row["retriever_type"],
            search_time=row["search_time"],
            llm_time=row["llm_time"],
            cache_hit=bool(row["cache_hit"]) if row["cache_hit"] is not None else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"]
        )


# 全局单例
_query_log_db: Optional[QueryLogDB] = None


def get_query_log_db() -> QueryLogDB:
    """
    获取全局查询日志数据库实例

    Returns:
        QueryLogDB 单例
    """
    global _query_log_db
    if _query_log_db is None:
        _query_log_db = QueryLogDB()
    return _query_log_db
