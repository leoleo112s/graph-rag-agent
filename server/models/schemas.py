from pydantic import BaseModel
from typing import Optional, List, Dict, Any, TypeVar, Generic
from graphrag_agent.config.settings import community_algorithm

# 泛型类型变量
T = TypeVar('T')


class ChatRequest(BaseModel):
    """聊天请求模型"""
    message: str
    session_id: str
    debug: bool = False
    agent_type: str = "naive_rag_agent"
    use_deeper_tool: Optional[bool] = True
    show_thinking: Optional[bool] = False


class ChatResponse(BaseModel):
    """聊天响应模型"""
    answer: str
    execution_log: Optional[List[Dict]] = None
    kg_data: Optional[Dict] = None
    reference: Optional[Dict] = None
    iterations: Optional[List[Dict]] = None


class SourceRequest(BaseModel):
    """源内容请求模型"""
    source_id: str


class SourceResponse(BaseModel):
    """源内容响应模型"""
    content: str


class SourceInfoResponse(BaseModel):
    """源文件信息响应模型"""
    file_name: str


class ClearRequest(BaseModel):
    """清除聊天历史请求模型"""
    session_id: str


class ClearResponse(BaseModel):
    """清除聊天历史响应模型"""
    status: str
    remaining_messages: Optional[str] = None


class FeedbackRequest(BaseModel):
    """反馈请求模型"""
    message_id: str
    query: str
    is_positive: bool
    thread_id: str
    agent_type: Optional[str] = "naive_rag_agent"


class FeedbackResponse(BaseModel):
    """反馈响应模型"""
    status: str
    action: str

class SourceInfoBatchRequest(BaseModel):
    source_ids: List[str]

class ContentBatchRequest(BaseModel):
    chunk_ids: List[str]

class ReasoningRequest(BaseModel):
    reasoning_type: str
    entity_a: str
    entity_b: Optional[str] = None
    max_depth: Optional[int] = 3
    algorithm: Optional[str] = community_algorithm

class EntityData(BaseModel):
    id: str
    name: str
    type: str
    description: Optional[str] = ""
    properties: Optional[Dict[str, Any]] = {}

class EntityUpdateData(BaseModel):
    id: str
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None

class EntitySearchFilter(BaseModel):
    term: Optional[str] = None
    type: Optional[str] = None
    limit: Optional[int] = 100

class RelationData(BaseModel):
    source: str
    type: str
    target: str
    description: Optional[str] = ""
    weight: Optional[float] = 0.5
    properties: Optional[Dict[str, Any]] = {}

class RelationUpdateData(BaseModel):
    source: str
    original_type: str
    target: str
    new_type: Optional[str] = None
    description: Optional[str] = None
    weight: Optional[float] = None
    properties: Optional[Dict[str, Any]] = None

class RelationSearchFilter(BaseModel):
    source: Optional[str] = None
    target: Optional[str] = None
    type: Optional[str] = None
    limit: Optional[int] = 100

class EntityDeleteData(BaseModel):
    id: str

class RelationDeleteData(BaseModel):
    source: str
    type: str
    target: str


# ============================================================================
# 统一响应模型 (Unified Response Model)
# ============================================================================

class BaseResponse(BaseModel, Generic[T]):
    """
    统一响应结构

    Examples:
        # 成功响应
        BaseResponse[Dict](code=200, msg="success", data={"key": "value"})

        # 错误响应
        BaseResponse[None](code=5001, msg="LLM service unavailable", data=None)
    """
    code: int = 200
    msg: str = "success"
    data: Optional[T] = None


class ErrorCode:
    """
    业务错误码定义

    分类规则：
    - 2xx: 成功类
    - 4xx: 客户端错误
    - 5xxx: 服务端错误
        - 50xx: 通用错误
        - 51xx: LLM相关错误
        - 52xx: 数据库相关错误
        - 53xx: 缓存相关错误
        - 54xx: 文件系统相关错误
    """
    # 成功类
    SUCCESS = 200
    EMPTY_RESULT = 204  # 查询成功但无结果

    # 客户端错误
    PARAM_ERROR = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    CONFLICT = 409  # 资源冲突（如重复创建）

    # 服务端错误 - 通用
    SERVER_ERROR = 500
    SERVICE_UNAVAILABLE = 503

    # LLM相关错误 (51xx)
    LLM_ERROR = 5101
    LLM_TIMEOUT = 5102
    LLM_TOKEN_LIMIT = 5103
    LLM_PARSE_ERROR = 5104  # JSON解析失败

    # 数据库相关错误 (52xx)
    DB_ERROR = 5201
    DB_CONNECTION_ERROR = 5202
    DB_QUERY_ERROR = 5203
    DB_TRANSACTION_ERROR = 5204

    # 缓存相关错误 (53xx)
    CACHE_ERROR = 5301
    CACHE_MISS = 5302

    # 文件系统相关错误 (54xx)
    FILE_ERROR = 5401
    FILE_NOT_FOUND = 5402
    FILE_READ_ERROR = 5403
    FILE_WRITE_ERROR = 5404

    # 实体抽取相关错误 (55xx)
    EXTRACTION_ERROR = 5501
    EXTRACTION_TIMEOUT = 5502
    EXTRACTION_EMPTY = 5503  # 未抽取到任何实体


# ============================================================================
# 实体抽取响应模型 (Entity Extraction Result)
# ============================================================================

class EntityItem(BaseModel):
    """实体项"""
    name: str
    type: str
    description: Optional[str] = ""


class RelationItem(BaseModel):
    """关系项"""
    source: str
    target: str
    type: str
    description: Optional[str] = ""
    weight: Optional[float] = 0.5


class ExtractionResult(BaseModel):
    """
    实体抽取结果模型（标准化JSON格式）

    用途：
    - 替代旧的字符串格式（_build_compatible_result）
    - 统一 entity_extractor.py 和 build_graph.py 的数据交换格式
    """
    entities: List[EntityItem] = []
    relations: List[RelationItem] = []
    chunk_id: Optional[str] = None  # 对应的chunk ID
    file_name: Optional[str] = None  # 来源文件名
    processing_time: Optional[float] = None  # 处理时长（秒）
    error: Optional[str] = None  # 如果处理失败，记录错误信息


class ExtractionStats(BaseModel):
    """实体抽取统计信息"""
    total_chunks: int = 0
    success_count: int = 0
    failed_count: int = 0
    total_entities: int = 0
    total_relations: int = 0
    avg_processing_time: float = 0.0
    cache_hit_rate: float = 0.0