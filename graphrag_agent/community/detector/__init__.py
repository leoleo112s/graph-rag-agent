"""社区检测模块

支持多种社区检测算法：
- Leiden: 高质量模块度优化算法
- Louvain: 经典模块度优化算法
- LabelPropagation: 快速标签传播算法
- SLLPA: Speaker-Listener标签传播算法

使用算法注册表统一管理：
    >>> from graphrag_agent.community.detector import AlgorithmRegistry
    >>> detector = AlgorithmRegistry.get_detector('louvain', gds, graph)
    >>> result = detector.process()

或使用工厂模式（向后兼容）：
    >>> from graphrag_agent.community.detector import CommunityDetectorFactory
    >>> detector = CommunityDetectorFactory.create('leiden', gds, graph)
"""

from graphdatascience import GraphDataScience
from langchain_community.graphs import Neo4jGraph

from .algorithm_registry import AlgorithmRegistry, get_detector, list_algorithms, recommend_algorithm
from .base import BaseCommunityDetector
from .label_propagation_detector import LabelPropagationDetector
from .leiden import LeidenDetector
from .louvain_detector import LouvainDetector
from .sllpa import SLLPADetector


class CommunityDetectorFactory:
    """社区检测器工厂类（向后兼容）"""

    ALGORITHMS = {
        "leiden": LeidenDetector,
        "louvain": LouvainDetector,
        "label_propagation": LabelPropagationDetector,
        "sllpa": SLLPADetector,
    }

    @classmethod
    def create(cls, algorithm: str, gds: GraphDataScience, graph: Neo4jGraph) -> BaseCommunityDetector:
        """创建社区检测器实例"""
        algorithm = algorithm.lower()
        if algorithm not in cls.ALGORITHMS:
            available = ", ".join(cls.ALGORITHMS.keys())
            raise ValueError(f"不支持的算法: {algorithm}。可用算法: {available}")
        return cls.ALGORITHMS[algorithm](gds, graph)


__all__ = [
    "CommunityDetectorFactory",
    "BaseCommunityDetector",
    "LeidenDetector",
    "LouvainDetector",
    "LabelPropagationDetector",
    "SLLPADetector",
    "AlgorithmRegistry",
    "get_detector",
    "list_algorithms",
    "recommend_algorithm",
]
