"""
核心数据模型和状态定义
"""

from graphrag_agent.agents.multi_agent.core.execution_record import (
    ExecutionMetadata,
    ExecutionRecord,
    ReflectionResult,
    ToolCall,
)
from graphrag_agent.agents.multi_agent.core.plan_spec import (
    AcceptanceCriteria,
    PlanExecutionSignal,
    PlanSpec,
    ProblemStatement,
    TaskGraph,
    TaskNode,
)
from graphrag_agent.agents.multi_agent.core.retrieval_result import RetrievalMetadata, RetrievalResult
from graphrag_agent.agents.multi_agent.core.state import ExecutionContext, PlanContext, PlanExecuteState, ReportContext

__all__ = [
    "PlanExecuteState",
    "PlanContext",
    "ExecutionContext",
    "ReportContext",
    "PlanSpec",
    "ProblemStatement",
    "TaskNode",
    "TaskGraph",
    "AcceptanceCriteria",
    "PlanExecutionSignal",
    "ExecutionRecord",
    "ToolCall",
    "ReflectionResult",
    "ExecutionMetadata",
    "RetrievalResult",
    "RetrievalMetadata",
]
