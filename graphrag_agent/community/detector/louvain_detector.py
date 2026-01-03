"""
Louvain 社区检测算法

经典的模块度优化算法，适用于大规模网络。
"""

from typing import Any, Dict

from graphrag_agent.config.settings import GDS_CONCURRENCY

from .base import BaseCommunityDetector
from .projections import GraphProjectionMixin


class LouvainDetector(GraphProjectionMixin, BaseCommunityDetector):
    """Louvain算法社区检测实现"""

    def detect_communities(self) -> Dict[str, Any]:
        """执行Louvain算法社区检测"""
        if not self.G:
            raise ValueError("请先创建图投影")

        print("开始执行Louvain社区检测...")

        try:
            # 检查连通分量
            wcc = self.gds.wcc.stats(self.G)
            print(f"图包含 {wcc.get('componentCount', 0)} 个连通分量")

            # 执行Louvain算法
            result = self.gds.louvain.write(
                self.G,
                writeProperty="communities",
                includeIntermediateCommunities=True,
                relationshipWeightProperty="weight",
                **self._get_optimized_louvain_params(),
            )

            return {
                "componentCount": wcc.get("componentCount", 0),
                "componentDistribution": wcc.get("componentDistribution", {}),
                "communityCount": result.get("communityCount", 0),
                "modularity": result.get("modularity", 0),
                "ranLevels": result.get("ranLevels", 0),
            }

        except Exception as e:
            print(f"Louvain算法执行失败: {e}")
            return self._execute_fallback_louvain()

    def _execute_fallback_louvain(self) -> Dict[str, Any]:
        """执行备用Louvain算法"""
        print("尝试使用备用参数...")

        try:
            result = self.gds.louvain.write(
                self.G,
                writeProperty="communities",
                includeIntermediateCommunities=False,
                tolerance=0.001,
                maxLevels=3,
                concurrency=1,
            )

            return {
                "communityCount": result.get("communityCount", 0),
                "modularity": result.get("modularity", 0),
                "ranLevels": result.get("ranLevels", 0),
                "note": "使用了备用参数",
            }
        except Exception as e:
            raise ValueError(f"Louvain算法执行失败: {e}")

    def _get_optimized_louvain_params(self) -> Dict[str, Any]:
        """获取优化的Louvain算法参数"""
        if self.memory_mb > 32 * 1024:  # >32GB
            return {"tolerance": 0.0001, "maxLevels": 10, "concurrency": GDS_CONCURRENCY}
        elif self.memory_mb > 16 * 1024:  # >16GB
            return {"tolerance": 0.0005, "maxLevels": 5, "concurrency": max(1, GDS_CONCURRENCY - 1)}
        else:  # 小内存系统
            return {"tolerance": 0.001, "maxLevels": 3, "concurrency": max(1, GDS_CONCURRENCY // 2)}

    def save_communities(self) -> Dict[str, int]:
        """保存Louvain算法的社区检测结果"""
        print("开始保存Louvain社区检测结果...")

        try:
            # 创建约束
            self.graph.query("CREATE CONSTRAINT IF NOT EXISTS FOR (c:__Community__) REQUIRE c.id IS UNIQUE;")

            # 保存基础社区关系
            base_result = self.graph.query(
                """
            MATCH (e:`__Entity__`)
            WHERE e.communities IS NOT NULL AND size(e.communities) > 0
            WITH collect({entityId: id(e), community: e.communities[0]}) AS data
            UNWIND data AS item
            MERGE (c:`__Community__` {id: '0-' + toString(item.community)})
            ON CREATE SET c.level = 0, c.algorithm = 'louvain'
            WITH item, c
            MATCH (e) WHERE id(e) = item.entityId
            MERGE (e)-[:IN_COMMUNITY]->(c)
            RETURN count(*) AS base_count
            """
            )

            base_count = base_result[0]["base_count"] if base_result else 0

            # 保存更高层级社区关系
            higher_result = self.graph.query(
                """
            MATCH (e:`__Entity__`)
            WHERE e.communities IS NOT NULL AND size(e.communities) > 1
            WITH e, e.communities AS communities
            UNWIND range(1, size(communities) - 1) AS index
            WITH e, index, communities[index] AS current_community,
                 communities[index-1] AS previous_community

            MERGE (current:`__Community__` {id: toString(index) + '-' +
                                              toString(current_community)})
            ON CREATE SET current.level = index, current.algorithm = 'louvain'

            WITH e, current, previous_community, index
            MATCH (previous:`__Community__` {id: toString(index - 1) + '-' +
                                              toString(previous_community)})
            MERGE (previous)-[:IN_COMMUNITY]->(current)

            RETURN count(*) AS higher_count
            """
            )

            higher_count = higher_result[0]["higher_count"] if higher_result else 0

            print(f"Louvain: 保存了 {base_count} 个基础社区和 {higher_count} 个层级关系")

            return {"saved_communities": base_count + higher_count}

        except Exception as e:
            print(f"社区保存失败: {e}")
            return self._save_communities_fallback()

    def _save_communities_fallback(self) -> Dict[str, int]:
        """备用保存方法：仅保存基础社区"""
        print("使用备用方法保存社区...")

        try:
            result = self.graph.query(
                """
            MATCH (e:`__Entity__`)
            WHERE e.communities IS NOT NULL AND size(e.communities) > 0
            WITH e, e.communities[0] AS community_id
            MERGE (c:`__Community__` {id: '0-' + toString(community_id)})
            ON CREATE SET c.level = 0, c.algorithm = 'louvain'
            MERGE (e)-[:IN_COMMUNITY]->(c)
            RETURN count(*) AS saved_count
            """
            )

            saved_count = result[0]["saved_count"] if result else 0
            print(f"备用方法保存了 {saved_count} 个社区")

            return {"saved_communities": saved_count}

        except Exception as e:
            print(f"备用保存也失败: {e}")
            return {"saved_communities": 0}
