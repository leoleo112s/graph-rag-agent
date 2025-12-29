"""
社区检测算法注册表

提供统一的算法管理接口，支持动态选择和配置社区检测算法。
"""

from typing import Any, Dict, List, Optional, Type

from graphdatascience import GraphDataScience
from langchain_community.graphs import Neo4jGraph

from graphrag_agent.utils.logging_config import get_logger

from .base import BaseCommunityDetector
from .leiden import LeidenDetector
from .label_propagation_detector import LabelPropagationDetector
from .louvain_detector import LouvainDetector
from .sllpa import SLLPADetector

logger = get_logger(__name__)


class AlgorithmRegistry:
    """
    社区检测算法注册表

    使用示例:
        >>> registry = AlgorithmRegistry()
        >>> registry.list_algorithms()
        ['leiden', 'louvain', 'label_propagation', 'sllpa']

        >>> detector = registry.get_detector('louvain', gds, graph)
        >>> result = detector.process()
    """

    # 算法注册表
    _algorithms: Dict[str, Type[BaseCommunityDetector]] = {
        "leiden": LeidenDetector,
        "louvain": LouvainDetector,
        "label_propagation": LabelPropagationDetector,
        "sllpa": SLLPADetector,
    }

    # 算法元数据
    _metadata: Dict[str, Dict[str, Any]] = {
        "leiden": {
            "name": "Leiden",
            "description": "Leiden算法，Louvain的改进版本，模块度优化更准确",
            "complexity": "O(E log V)",
            "recommended_for": "中大规模网络，需要高质量社区划分",
            "pros": ["模块度优化好", "层级社区检测", "可调参数多"],
            "cons": ["计算开销较大", "内存占用高"],
            "tags": ["hierarchical", "modularity", "quality"],
        },
        "louvain": {
            "name": "Louvain",
            "description": "经典的模块度优化算法，广泛使用",
            "complexity": "O(E log V)",
            "recommended_for": "大规模网络，快速社区检测",
            "pros": ["速度快", "模块度高", "层级社区"],
            "cons": ["可能陷入局部最优", "社区不平衡"],
            "tags": ["hierarchical", "modularity", "fast"],
        },
        "label_propagation": {
            "name": "Label Propagation",
            "description": "快速的标签传播算法，线性时间复杂度",
            "complexity": "O(E)",
            "recommended_for": "超大规模网络，需要快速结果",
            "pros": ["速度极快", "内存占用低", "适合大规模网络"],
            "cons": ["结果不稳定", "对初始标签敏感", "无层级结构"],
            "tags": ["fast", "scalable", "unstable"],
        },
        "sllpa": {
            "name": "SLLPA",
            "description": "Speaker-Listener标签传播算法，改进版本",
            "complexity": "O(E)",
            "recommended_for": "中等规模网络，需要平衡速度和质量",
            "pros": ["速度快", "社区质量较好", "较稳定"],
            "cons": ["参数调优复杂", "无层级结构"],
            "tags": ["fast", "balanced", "moderate"],
        },
    }

    @classmethod
    def register_algorithm(
        cls, name: str, detector_class: Type[BaseCommunityDetector], metadata: Optional[Dict[str, Any]] = None
    ):
        """
        注册新的社区检测算法

        Args:
            name: 算法名称
            detector_class: 检测器类（继承自BaseCommunityDetector）
            metadata: 算法元数据（可选）

        Example:
            >>> class MyDetector(BaseCommunityDetector):
            ...     pass
            >>> AlgorithmRegistry.register_algorithm('my_algo', MyDetector, {...})
        """
        if not issubclass(detector_class, BaseCommunityDetector):
            raise ValueError(f"{detector_class} must inherit from BaseCommunityDetector")

        cls._algorithms[name] = detector_class
        if metadata:
            cls._metadata[name] = metadata

        logger.info(f"Registered algorithm: {name}")

    @classmethod
    def unregister_algorithm(cls, name: str) -> bool:
        """
        注销算法

        Args:
            name: 算法名称

        Returns:
            是否成功
        """
        if name in cls._algorithms:
            del cls._algorithms[name]
            cls._metadata.pop(name, None)
            logger.info(f"Unregistered algorithm: {name}")
            return True
        return False

    @classmethod
    def list_algorithms(cls) -> List[str]:
        """获取所有已注册算法名称"""
        return list(cls._algorithms.keys())

    @classmethod
    def get_algorithm_info(cls, name: str) -> Optional[Dict[str, Any]]:
        """获取算法元数据"""
        return cls._metadata.get(name)

    @classmethod
    def get_all_algorithms_info(cls) -> Dict[str, Dict[str, Any]]:
        """获取所有算法的元数据"""
        return cls._metadata.copy()

    @classmethod
    def get_detector(cls, name: str, gds: GraphDataScience, graph: Neo4jGraph) -> BaseCommunityDetector:
        """
        创建算法检测器实例

        Args:
            name: 算法名称
            gds: Neo4j GDS实例
            graph: Neo4j图实例

        Returns:
            检测器实例

        Raises:
            ValueError: 算法不存在

        Example:
            >>> registry = AlgorithmRegistry()
            >>> detector = registry.get_detector('leiden', gds, graph)
            >>> result = detector.process()
        """
        detector_class = cls._algorithms.get(name)

        if not detector_class:
            available = ", ".join(cls.list_algorithms())
            raise ValueError(f"Unknown algorithm: {name}. Available: {available}")

        return detector_class(gds, graph)

    @classmethod
    def compare_algorithms(
        cls, filter_tags: Optional[List[str]] = None, sort_by: str = "complexity"
    ) -> List[Dict[str, Any]]:
        """
        比较算法特性

        Args:
            filter_tags: 过滤标签（如 ['fast', 'hierarchical']）
            sort_by: 排序字段 ('complexity', 'name')

        Returns:
            算法比较列表

        Example:
            >>> AlgorithmRegistry.compare_algorithms(filter_tags=['fast'])
            [
                {'name': 'label_propagation', 'complexity': 'O(E)', ...},
                {'name': 'louvain', 'complexity': 'O(E log V)', ...}
            ]
        """
        results = []

        for algo_name, metadata in cls._metadata.items():
            # 标签过滤
            if filter_tags:
                algo_tags = metadata.get("tags", [])
                if not any(tag in algo_tags for tag in filter_tags):
                    continue

            results.append({"algorithm": algo_name, **metadata})

        # 排序
        if sort_by == "complexity":
            # 简单排序：O(E) < O(E log V) < O(V^2)
            complexity_order = {"O(E)": 1, "O(E log V)": 2, "O(V^2)": 3}
            results.sort(key=lambda x: complexity_order.get(x.get("complexity", ""), 999))
        elif sort_by == "name":
            results.sort(key=lambda x: x["algorithm"])

        return results

    @classmethod
    def recommend_algorithm(cls, graph_size: str = "medium", priority: str = "balanced") -> str:
        """
        推荐算法

        Args:
            graph_size: 图规模 ('small', 'medium', 'large', 'huge')
            priority: 优先级 ('speed', 'quality', 'balanced')

        Returns:
            推荐的算法名称

        Example:
            >>> AlgorithmRegistry.recommend_algorithm(graph_size='large', priority='speed')
            'label_propagation'
        """
        # 推荐矩阵
        recommendations = {
            ("small", "speed"): "label_propagation",
            ("small", "quality"): "leiden",
            ("small", "balanced"): "louvain",
            ("medium", "speed"): "louvain",
            ("medium", "quality"): "leiden",
            ("medium", "balanced"): "sllpa",
            ("large", "speed"): "label_propagation",
            ("large", "quality"): "louvain",
            ("large", "balanced"): "louvain",
            ("huge", "speed"): "label_propagation",
            ("huge", "quality"): "label_propagation",
            ("huge", "balanced"): "label_propagation",
        }

        recommended = recommendations.get((graph_size, priority), "louvain")
        logger.info(f"Recommended algorithm for {graph_size}/{priority}: {recommended}")

        return recommended


# 便捷函数


def get_detector(algorithm: str, gds: GraphDataScience, graph: Neo4jGraph) -> BaseCommunityDetector:
    """快捷方式：获取检测器实例"""
    return AlgorithmRegistry.get_detector(algorithm, gds, graph)


def list_algorithms() -> List[str]:
    """快捷方式：列出所有算法"""
    return AlgorithmRegistry.list_algorithms()


def recommend_algorithm(graph_size: str = "medium", priority: str = "balanced") -> str:
    """快捷方式：推荐算法"""
    return AlgorithmRegistry.recommend_algorithm(graph_size, priority)
