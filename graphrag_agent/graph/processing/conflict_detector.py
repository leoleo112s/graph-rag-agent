"""
规则based冲突检测器

检测知识图谱中的实体冲突和不一致性。
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from langchain_community.graphs import Neo4jGraph

logger = logging.getLogger(__name__)


class ConflictType:
    """冲突类型常量"""

    DUPLICATE_ENTITY = "duplicate_entity"  # 重复实体
    CONFLICTING_RELATIONSHIP = "conflicting_relationship"  # 冲突关系
    CIRCULAR_DEPENDENCY = "circular_dependency"  # 循环依赖
    MISSING_REQUIRED_PROPERTY = "missing_required_property"  # 缺少必需属性
    TYPE_MISMATCH = "type_mismatch"  # 类型不匹配


class RuleBasedConflictDetector:
    """
    规则based冲突检测器

    使用预定义规则检测图中的冲突：
    1. 重复实体（相似名称但不同节点）
    2. 冲突关系（互斥关系同时存在）
    3. 循环依赖（实体之间的环形引用）

    使用示例:
        >>> detector = RuleBasedConflictDetector(graph)
        >>> conflicts = detector.detect_all_conflicts()
        >>> for conflict in conflicts:
        ...     print(f"{conflict['type']}: {conflict['description']}")
    """

    def __init__(self, graph: Neo4jGraph):
        """
        初始化冲突检测器

        Args:
            graph: Neo4j 图实例
        """
        self.graph = graph

        # 互斥关系配置（根据实际业务定义）
        self.mutually_exclusive_relations = [
            ("申请", "拒绝"),  # 不能同时申请和被拒绝
            ("获得", "取消"),  # 不能同时获得和取消
            ("通过", "未通过"),  # 不能同时通过和未通过
        ]

        # 必需属性配置
        self.required_properties = {
            "__Entity__": ["id"],  # 所有实体必须有 id
        }

    def detect_all_conflicts(self) -> List[Dict[str, Any]]:
        """
        检测所有类型的冲突

        Returns:
            冲突列表 [{"type": "...", "description": "...", "entities": [...], ...}, ...]
        """
        conflicts = []

        logger.info("Starting conflict detection...")

        # 1. 检测重复实体
        logger.info("Checking for duplicate entities...")
        conflicts.extend(self.detect_duplicate_entities())

        # 2. 检测冲突关系
        logger.info("Checking for conflicting relationships...")
        conflicts.extend(self.detect_conflicting_relationships())

        # 3. 检测循环依赖
        logger.info("Checking for circular dependencies...")
        conflicts.extend(self.detect_circular_dependencies())

        # 4. 检测缺少必需属性
        logger.info("Checking for missing required properties...")
        conflicts.extend(self.detect_missing_properties())

        logger.info(f"Conflict detection completed. Found {len(conflicts)} conflicts.")

        return conflicts

    def detect_duplicate_entities(self, similarity_threshold: float = 0.9) -> List[Dict[str, Any]]:
        """
        检测重复实体（名称高度相似但不同节点）

        Args:
            similarity_threshold: 相似度阈值 (0.0-1.0)

        Returns:
            重复实体冲突列表
        """
        conflicts = []

        try:
            # 查询所有实体
            query = """
            MATCH (e:`__Entity__`)
            RETURN id(e) AS entity_id, e.id AS entity_name
            """

            entities = self.graph.query(query)

            # 简单的相似度检测（基于字符串编辑距离）
            from difflib import SequenceMatcher

            for i, entity_a in enumerate(entities):
                for entity_b in entities[i + 1 :]:
                    name_a = entity_a["entity_name"]
                    name_b = entity_b["entity_name"]

                    # 计算相似度
                    similarity = SequenceMatcher(None, name_a, name_b).ratio()

                    if similarity >= similarity_threshold and name_a != name_b:
                        conflicts.append(
                            {
                                "type": ConflictType.DUPLICATE_ENTITY,
                                "severity": "medium",
                                "description": f"发现疑似重复实体: '{name_a}' 和 '{name_b}' (相似度: {similarity:.2f})",
                                "entities": [
                                    {"id": entity_a["entity_id"], "name": name_a},
                                    {"id": entity_b["entity_id"], "name": name_b},
                                ],
                                "similarity": similarity,
                            }
                        )

        except Exception as e:
            logger.error(f"Error detecting duplicate entities: {e}")

        return conflicts

    def detect_conflicting_relationships(self) -> List[Dict[str, Any]]:
        """
        检测冲突关系（互斥关系同时存在）

        Returns:
            冲突关系列表
        """
        conflicts = []

        try:
            for rel_a, rel_b in self.mutually_exclusive_relations:
                # 查询同时具有互斥关系的实体对
                query = f"""
                MATCH (e1:`__Entity__`)-[r1:`{rel_a}`]->(e2:`__Entity__`)
                MATCH (e1)-[r2:`{rel_b}`]->(e2)
                RETURN e1.id AS source, e2.id AS target, type(r1) AS rel1, type(r2) AS rel2
                """

                results = self.graph.query(query)

                for result in results:
                    conflicts.append(
                        {
                            "type": ConflictType.CONFLICTING_RELATIONSHIP,
                            "severity": "high",
                            "description": f"实体 '{result['source']}' 和 '{result['target']}' 之间同时存在互斥关系: '{rel_a}' 和 '{rel_b}'",
                            "source": result["source"],
                            "target": result["target"],
                            "relationships": [rel_a, rel_b],
                        }
                    )

        except Exception as e:
            logger.error(f"Error detecting conflicting relationships: {e}")

        return conflicts

    def detect_circular_dependencies(self, max_depth: int = 5) -> List[Dict[str, Any]]:
        """
        检测循环依赖（实体之间的环形引用）

        Args:
            max_depth: 最大检测深度

        Returns:
            循环依赖列表
        """
        conflicts = []

        try:
            # 查询循环路径
            query = f"""
            MATCH path = (e:`__Entity__`)-[*1..{max_depth}]->(e)
            WHERE length(path) >= 2
            RETURN [n in nodes(path) | n.id] AS cycle
            LIMIT 100
            """

            results = self.graph.query(query)

            for result in results:
                cycle = result["cycle"]

                conflicts.append(
                    {
                        "type": ConflictType.CIRCULAR_DEPENDENCY,
                        "severity": "medium",
                        "description": f"发现循环依赖: {' -> '.join(cycle)}",
                        "cycle": cycle,
                        "length": len(cycle) - 1,  # 去除重复的首尾节点
                    }
                )

        except Exception as e:
            logger.error(f"Error detecting circular dependencies: {e}")

        return conflicts

    def detect_missing_properties(self) -> List[Dict[str, Any]]:
        """
        检测缺少必需属性的节点

        Returns:
            缺少属性的节点列表
        """
        conflicts = []

        try:
            for label, required_props in self.required_properties.items():
                for prop in required_props:
                    # 查询缺少该属性的节点
                    query = f"""
                    MATCH (n:`{label}`)
                    WHERE n.{prop} IS NULL OR n.{prop} = ''
                    RETURN id(n) AS node_id, labels(n) AS labels
                    LIMIT 100
                    """

                    results = self.graph.query(query)

                    for result in results:
                        conflicts.append(
                            {
                                "type": ConflictType.MISSING_REQUIRED_PROPERTY,
                                "severity": "high",
                                "description": f"节点 (id: {result['node_id']}) 缺少必需属性 '{prop}'",
                                "node_id": result["node_id"],
                                "labels": result["labels"],
                                "missing_property": prop,
                            }
                        )

        except Exception as e:
            logger.error(f"Error detecting missing properties: {e}")

        return conflicts

    def generate_report(self, conflicts: Optional[List[Dict[str, Any]]] = None) -> str:
        """
        生成冲突检测报告

        Args:
            conflicts: 冲突列表（如果为 None，则自动检测）

        Returns:
            文本格式的报告
        """
        if conflicts is None:
            conflicts = self.detect_all_conflicts()

        # 按类型分组
        conflicts_by_type = {}
        for conflict in conflicts:
            conflict_type = conflict["type"]
            conflicts_by_type.setdefault(conflict_type, []).append(conflict)

        # 生成报告
        report_lines = [
            "=" * 60,
            "知识图谱冲突检测报告",
            "=" * 60,
            f"\n总计发现 {len(conflicts)} 个冲突\n",
        ]

        for conflict_type, conflict_list in conflicts_by_type.items():
            report_lines.append(f"\n{conflict_type.upper()} ({len(conflict_list)} 个):")
            report_lines.append("-" * 60)

            for conflict in conflict_list[:10]:  # 只显示前10个
                report_lines.append(f"  [{conflict.get('severity', 'unknown')}] {conflict['description']}")

            if len(conflict_list) > 10:
                report_lines.append(f"  ... 还有 {len(conflict_list) - 10} 个冲突\n")

        report_lines.append("\n" + "=" * 60)

        return "\n".join(report_lines)

    def export_conflicts(self, conflicts: List[Dict[str, Any]], output_path: str):
        """
        导出冲突到 JSON 文件

        Args:
            conflicts: 冲突列表
            output_path: 输出文件路径
        """
        import json
        from pathlib import Path

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(conflicts, f, ensure_ascii=False, indent=2)

        logger.info(f"Conflicts exported to {output_file}")
