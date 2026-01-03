"""
Map-Reduce reporter组件集合。

该子模块提供证据映射、章节归约与报告组装的能力，用于支持长文档写作。
"""

from .evidence_mapper import EvidenceMapper, EvidenceSummary
from .report_assembler import ReportAssembler
from .section_reducer import ReduceStrategy, SectionReducer

__all__ = [
    "EvidenceMapper",
    "EvidenceSummary",
    "SectionReducer",
    "ReduceStrategy",
    "ReportAssembler",
]
