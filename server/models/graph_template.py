"""
图谱模板数据模型

用于模板市场的模板存储、评分、下载追踪。
"""

import json
import sqlite3
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TemplateDomain(str, Enum):
    """模板领域枚举"""

    LEGAL = "legal"  # 法务
    MEDICAL = "medical"  # 医疗
    ECOMMERCE = "ecommerce"  # 电商
    EDUCATION = "education"  # 教育
    FINANCE = "finance"  # 金融
    GOVERNMENT = "government"  # 政府
    MANUFACTURING = "manufacturing"  # 制造业
    CUSTOM = "custom"  # 自定义


class GraphTemplate(BaseModel):
    """图谱模板模型"""

    id: str
    name: str
    domain: str  # 领域
    description: str
    config_json: Dict[str, Any]  # GraphConfig的JSON表示
    schema_definition: Optional[Dict[str, Any]] = None  # 可选的schema定义
    author_id: str = "system"
    author_name: str = "System"
    downloads: int = 0
    rating: float = 0.0  # 平均评分 (0-5)
    rating_count: int = 0  # 评分次数
    tags: List[str] = Field(default_factory=list)  # 标签
    is_official: bool = False  # 是否官方模板
    is_public: bool = True  # 是否公开
    created_at: str
    updated_at: str


class TemplateRating(BaseModel):
    """模板评分记录"""

    id: str
    template_id: str
    user_id: str
    rating: int  # 1-5星
    comment: Optional[str] = None
    created_at: str


class GraphTemplateDB:
    """图谱模板数据库管理器"""

    def __init__(self, db_path: str = "./data/templates.db"):
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
            # 模板表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    description TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    schema_definition TEXT,
                    author_id TEXT NOT NULL,
                    author_name TEXT NOT NULL,
                    downloads INTEGER DEFAULT 0,
                    rating REAL DEFAULT 0.0,
                    rating_count INTEGER DEFAULT 0,
                    tags TEXT,
                    is_official INTEGER DEFAULT 0,
                    is_public INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # 评分表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS template_ratings (
                    id TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    comment TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE CASCADE
                )
            """
            )

            # 创建索引
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_domain
                ON templates(domain)
            """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rating
                ON templates(rating DESC)
            """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_downloads
                ON templates(downloads DESC)
            """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_user_template_rating
                ON template_ratings(user_id, template_id)
            """
            )

            conn.commit()

    def create_template(
        self,
        name: str,
        domain: str,
        description: str,
        config_json: Dict[str, Any],
        author_id: str = "system",
        author_name: str = "System",
        schema_definition: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        is_official: bool = False,
        is_public: bool = True,
    ) -> str:
        """
        创建新模板

        Args:
            name: 模板名称
            domain: 领域
            description: 描述
            config_json: 配置JSON
            author_id: 作者ID
            author_name: 作者名称
            schema_definition: Schema定义
            tags: 标签
            is_official: 是否官方
            is_public: 是否公开

        Returns:
            模板ID
        """
        template_id = str(uuid.uuid4())
        created_at = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO templates
                (id, name, domain, description, config_json, schema_definition,
                 author_id, author_name, tags, is_official, is_public, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template_id,
                    name,
                    domain,
                    description,
                    json.dumps(config_json, ensure_ascii=False),
                    json.dumps(schema_definition, ensure_ascii=False) if schema_definition else None,
                    author_id,
                    author_name,
                    json.dumps(tags or [], ensure_ascii=False),
                    1 if is_official else 0,
                    1 if is_public else 0,
                    created_at,
                    created_at,
                ),
            )
            conn.commit()

        return template_id

    def get_template(self, template_id: str) -> Optional[GraphTemplate]:
        """
        获取模板详情

        Args:
            template_id: 模板ID

        Returns:
            GraphTemplate或None
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_template(row)

    def list_templates(
        self,
        domain: Optional[str] = None,
        author_id: Optional[str] = None,
        is_official: Optional[bool] = None,
        is_public: bool = True,
        sort_by: str = "rating",  # rating, downloads, created_at
        limit: int = 50,
        offset: int = 0,
    ) -> List[GraphTemplate]:
        """
        列出模板

        Args:
            domain: 过滤领域
            author_id: 过滤作者
            is_official: 过滤官方/非官方
            is_public: 是否公开
            sort_by: 排序字段
            limit: 返回数量
            offset: 偏移量

        Returns:
            模板列表
        """
        query = "SELECT * FROM templates WHERE is_public = ?"
        params = [1 if is_public else 0]

        if domain:
            query += " AND domain = ?"
            params.append(domain)

        if author_id:
            query += " AND author_id = ?"
            params.append(author_id)

        if is_official is not None:
            query += " AND is_official = ?"
            params.append(1 if is_official else 0)

        # 排序
        if sort_by == "rating":
            query += " ORDER BY rating DESC, rating_count DESC"
        elif sort_by == "downloads":
            query += " ORDER BY downloads DESC"
        elif sort_by == "created_at":
            query += " ORDER BY created_at DESC"
        else:
            query += " ORDER BY rating DESC"

        query += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_template(row) for row in rows]

    def increment_downloads(self, template_id: str):
        """
        增加下载次数

        Args:
            template_id: 模板ID
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE templates SET downloads = downloads + 1 WHERE id = ?", (template_id,))
            conn.commit()

    def rate_template(self, template_id: str, user_id: str, rating: int, comment: Optional[str] = None) -> str:
        """
        为模板评分

        Args:
            template_id: 模板ID
            user_id: 用户ID
            rating: 评分 (1-5)
            comment: 评论

        Returns:
            评分记录ID
        """
        if not 1 <= rating <= 5:
            raise ValueError("Rating must be between 1 and 5")

        rating_id = str(uuid.uuid4())
        created_at = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            # 检查是否已评分
            existing = conn.execute(
                "SELECT id, rating FROM template_ratings WHERE template_id = ? AND user_id = ?", (template_id, user_id)
            ).fetchone()

            if existing:
                # 更新评分
                old_rating = existing[1]
                conn.execute(
                    "UPDATE template_ratings SET rating = ?, comment = ?, created_at = ? WHERE id = ?",
                    (rating, comment, created_at, existing[0]),
                )
                rating_id = existing[0]

                # 更新模板平均分
                self._update_template_rating(conn, template_id, rating - old_rating, delta_count=0)
            else:
                # 新增评分
                conn.execute(
                    """
                    INSERT INTO template_ratings (id, template_id, user_id, rating, comment, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (rating_id, template_id, user_id, rating, comment, created_at),
                )

                # 更新模板平均分
                self._update_template_rating(conn, template_id, rating, delta_count=1)

            conn.commit()

        return rating_id

    def _update_template_rating(self, conn, template_id: str, rating_delta: int, delta_count: int):
        """
        更新模板平均评分

        Args:
            conn: 数据库连接
            template_id: 模板ID
            rating_delta: 评分变化量
            delta_count: 评分次数变化量
        """
        # 获取当前评分信息
        row = conn.execute("SELECT rating, rating_count FROM templates WHERE id = ?", (template_id,)).fetchone()

        if not row:
            return

        current_rating, current_count = row

        # 计算新的评分
        new_count = current_count + delta_count
        if new_count > 0:
            total_rating = current_rating * current_count + rating_delta
            new_rating = total_rating / new_count
        else:
            new_rating = 0.0

        # 更新
        conn.execute(
            "UPDATE templates SET rating = ?, rating_count = ?, updated_at = ? WHERE id = ?",
            (new_rating, new_count, datetime.now().isoformat(), template_id),
        )

    def get_template_ratings(self, template_id: str, limit: int = 50) -> List[TemplateRating]:
        """
        获取模板的所有评分

        Args:
            template_id: 模板ID
            limit: 返回数量

        Returns:
            评分列表
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM template_ratings
                WHERE template_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (template_id, limit),
            )
            rows = cursor.fetchall()

            ratings = []
            for row in rows:
                ratings.append(
                    TemplateRating(
                        id=row["id"],
                        template_id=row["template_id"],
                        user_id=row["user_id"],
                        rating=row["rating"],
                        comment=row["comment"],
                        created_at=row["created_at"],
                    )
                )

            return ratings

    def delete_template(self, template_id: str) -> bool:
        """
        删除模板

        Args:
            template_id: 模板ID

        Returns:
            是否成功
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
                conn.commit()
            return True
        except Exception as e:
            print(f"删除模板失败: {e}")
            return False

    def _row_to_template(self, row: sqlite3.Row) -> GraphTemplate:
        """
        将数据库行转换为GraphTemplate对象

        Args:
            row: 数据库行

        Returns:
            GraphTemplate对象
        """
        return GraphTemplate(
            id=row["id"],
            name=row["name"],
            domain=row["domain"],
            description=row["description"],
            config_json=json.loads(row["config_json"]),
            schema_definition=json.loads(row["schema_definition"]) if row["schema_definition"] else None,
            author_id=row["author_id"],
            author_name=row["author_name"],
            downloads=row["downloads"],
            rating=row["rating"],
            rating_count=row["rating_count"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            is_official=bool(row["is_official"]),
            is_public=bool(row["is_public"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# 全局单例
_template_db: Optional[GraphTemplateDB] = None


def get_template_db() -> GraphTemplateDB:
    """
    获取全局模板数据库实例

    Returns:
        GraphTemplateDB 单例
    """
    global _template_db
    if _template_db is None:
        _template_db = GraphTemplateDB()
    return _template_db
