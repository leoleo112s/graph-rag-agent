"""
REST API 分页和过滤工具

提供通用的分页和过滤功能，用于改进 REST API 性能。
"""

from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    """分页参数"""

    page: int = Field(default=1, ge=1, description="页码（从1开始）")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量（1-100）")
    sort_by: Optional[str] = Field(default=None, description="排序字段")
    sort_order: str = Field(default="desc", description="排序方向 (asc/desc)")

    @property
    def offset(self) -> int:
        """计算偏移量"""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """获取限制数量"""
        return self.page_size


class FilterParams(BaseModel):
    """过滤参数"""

    search: Optional[str] = Field(default=None, description="搜索关键词")
    tags: Optional[List[str]] = Field(default=None, description="标签过滤")
    date_from: Optional[str] = Field(default=None, description="开始日期 (ISO格式)")
    date_to: Optional[str] = Field(default=None, description="结束日期 (ISO格式)")


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应"""

    items: List[T] = Field(..., description="数据项列表")
    total: int = Field(..., description="总数")
    page: int = Field(..., description="当前页码")
    page_size: int = Field(..., description="每页数量")
    total_pages: int = Field(..., description="总页数")
    has_next: bool = Field(..., description="是否有下一页")
    has_prev: bool = Field(..., description="是否有上一页")

    @classmethod
    def create(cls, items: List[T], total: int, pagination: PaginationParams) -> "PaginatedResponse[T]":
        """
        创建分页响应

        Args:
            items: 当前页数据项
            total: 总数
            pagination: 分页参数

        Returns:
            分页响应对象
        """
        total_pages = (total + pagination.page_size - 1) // pagination.page_size

        return cls(
            items=items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            total_pages=total_pages,
            has_next=pagination.page < total_pages,
            has_prev=pagination.page > 1,
        )


def build_cypher_filters(filters: FilterParams) -> tuple[str, Dict[str, Any]]:
    """
    构建 Cypher 查询的过滤条件

    Args:
        filters: 过滤参数

    Returns:
        (where_clause, params_dict) 元组

    Example:
        >>> filters = FilterParams(search="学生", tags=["教育"])
        >>> where_clause, params = build_cypher_filters(filters)
        >>> # where_clause = "WHERE n.name CONTAINS $search AND 'education' IN n.tags"
        >>> # params = {"search": "学生"}
    """
    conditions = []
    params = {}

    if filters.search:
        conditions.append("n.name CONTAINS $search OR n.description CONTAINS $search")
        params["search"] = filters.search

    if filters.tags:
        # 检查节点是否包含任一标签
        tag_conditions = [f"'{tag}' IN n.tags" for tag in filters.tags]
        conditions.append(f"({' OR '.join(tag_conditions)})")

    if filters.date_from:
        conditions.append("n.created_at >= $date_from")
        params["date_from"] = filters.date_from

    if filters.date_to:
        conditions.append("n.created_at <= $date_to")
        params["date_to"] = filters.date_to

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    return where_clause, params


def build_cypher_sort(sort_by: Optional[str], sort_order: str) -> str:
    """
    构建 Cypher 排序子句

    Args:
        sort_by: 排序字段
        sort_order: 排序方向 (asc/desc)

    Returns:
        ORDER BY 子句

    Example:
        >>> build_cypher_sort("created_at", "desc")
        "ORDER BY n.created_at DESC"
    """
    if not sort_by:
        return ""

    order = "DESC" if sort_order.lower() == "desc" else "ASC"
    return f"ORDER BY n.{sort_by} {order}"


# 便捷函数


def paginate(items: List[T], pagination: PaginationParams) -> List[T]:
    """
    对内存中的列表进行分页

    Args:
        items: 完整数据列表
        pagination: 分页参数

    Returns:
        当前页的数据项

    Example:
        >>> all_items = list(range(100))
        >>> pagination = PaginationParams(page=2, page_size=10)
        >>> page_items = paginate(all_items, pagination)
        >>> # 返回第 11-20 项
    """
    start = pagination.offset
    end = start + pagination.page_size
    return items[start:end]


def filter_items(items: List[Dict[str, Any]], filters: FilterParams) -> List[Dict[str, Any]]:
    """
    过滤内存中的数据项

    Args:
        items: 数据项列表
        filters: 过滤参数

    Returns:
        过滤后的数据项

    Example:
        >>> items = [{"name": "学生", "tags": ["教育"]}, {"name": "教师", "tags": ["教育"]}]
        >>> filters = FilterParams(search="学生")
        >>> filtered = filter_items(items, filters)
        >>> # 返回 [{"name": "学生", "tags": ["教育"]}]
    """
    result = items

    # 搜索过滤
    if filters.search:
        search_lower = filters.search.lower()
        result = [
            item
            for item in result
            if search_lower in str(item.get("name", "")).lower()
            or search_lower in str(item.get("description", "")).lower()
        ]

    # 标签过滤
    if filters.tags:
        result = [item for item in result if any(tag in item.get("tags", []) for tag in filters.tags)]

    # 日期过滤
    if filters.date_from:
        result = [item for item in result if item.get("created_at", "") >= filters.date_from]

    if filters.date_to:
        result = [item for item in result if item.get("created_at", "") <= filters.date_to]

    return result


# 使用示例
"""
# 在 FastAPI 路由中使用:

from fastapi import APIRouter, Depends
from server.utils.pagination import PaginationParams, FilterParams, PaginatedResponse

router = APIRouter()

@router.get("/items")
async def list_items(
    pagination: PaginationParams = Depends(),
    filters: FilterParams = Depends()
) -> PaginatedResponse[ItemModel]:
    # 构建查询
    where_clause, params = build_cypher_filters(filters)
    sort_clause = build_cypher_sort(pagination.sort_by, pagination.sort_order)

    # 查询总数
    count_query = f\"\"\"
    MATCH (n:Item)
    {where_clause}
    RETURN count(n) AS total
    \"\"\"
    total = graph.query(count_query, params)[0]["total"]

    # 查询分页数据
    items_query = f\"\"\"
    MATCH (n:Item)
    {where_clause}
    RETURN n
    {sort_clause}
    SKIP {pagination.offset}
    LIMIT {pagination.limit}
    \"\"\"
    items = graph.query(items_query, params)

    return PaginatedResponse.create(items, total, pagination)
"""
