"""
Label Propagation 社区检测算法

快速的标签传播算法，适用于大规模网络且对初始标签敏感度较低。
"""

from typing import Any, Dict

from graphrag_agent.config.settings import GDS_CONCURRENCY

from .base import BaseCommunityDetector
from .projections import GraphProjectionMixin


class LabelPropagationDetector(GraphProjectionMixin, BaseCommunityDetector):
    """Label Propagation算法社区检测实现"""

    def detect_communities(self) -> Dict[str, Any]:
        """执行Label Propagation算法社区检测"""
        if not self.G:
            raise ValueError("请先创建图投影")

        print("开始执行Label Propagation社区检测...")

        try:
            # 检查连通分量
            wcc = self.gds.wcc.stats(self.G)
            print(f"图包含 {wcc.get('componentCount', 0)} 个连通分量")

            # 执行Label Propagation算法
            result = self.gds.labelPropagation.write(
                self.G,
                writeProperty="communities",
                relationshipWeightProperty="weight",
                **self._get_optimized_lpa_params(),
            )

            # Label Propagation 不计算模块度，需要手动计算
            try:
                modularity_result = self.gds.beta.modularityOptimization.stats(
                    self.G, relationshipWeightProperty="weight", communityProperty="communities"
                )
                modularity = modularity_result.get("modularity", 0)
            except Exception:
                modularity = 0

            return {
                "componentCount": wcc.get("componentCount", 0),
                "componentDistribution": wcc.get("componentDistribution", {}),
                "communityCount": result.get("communityCount", 0),
                "ranIterations": result.get("ranIterations", 0),
                "didConverge": result.get("didConverge", False),
                "modularity": modularity,
            }

        except Exception as e:
            print(f"Label Propagation算法执行失败: {e}")
            return self._execute_fallback_lpa()

    def _execute_fallback_lpa(self) -> Dict[str, Any]:
        """执行备用Label Propagation算法"""
        print("尝试使用备用参数...")

        try:
            result = self.gds.labelPropagation.write(
                self.G, writeProperty="communities", maxIterations=5, concurrency=1
            )

            return {
                "communityCount": result.get("communityCount", 0),
                "ranIterations": result.get("ranIterations", 0),
                "didConverge": result.get("didConverge", False),
                "note": "使用了备用参数",
            }
        except Exception as e:
            raise ValueError(f"Label Propagation算法执行失败: {e}")

    def _get_optimized_lpa_params(self) -> Dict[str, Any]:
        """获取优化的Label Propagation算法参数"""
        if self.memory_mb > 32 * 1024:  # >32GB
            return {"maxIterations": 20, "concurrency": GDS_CONCURRENCY}
        elif self.memory_mb > 16 * 1024:  # >16GB
            return {"maxIterations": 15, "concurrency": max(1, GDS_CONCURRENCY - 1)}
        else:  # 小内存系统
            return {"maxIterations": 10, "concurrency": max(1, GDS_CONCURRENCY // 2)}

    def save_communities(self) -> Dict[str, int]:
        """保存Label Propagation算法的社区检测结果"""
        print("开始保存Label Propagation社区检测结果...")

        try:
            # 创建约束
            self.graph.query("CREATE CONSTRAINT IF NOT EXISTS FOR (c:__Community__) REQUIRE c.id IS UNIQUE;")

            # Label Propagation 只有单层社区，简化保存逻辑
            result = self.graph.query(
                """
            MATCH (e:`__Entity__`)
            WHERE e.communities IS NOT NULL
            WITH e, CASE
                WHEN e.communities IS NULL THEN null
                WHEN size(e.communities) = 0 THEN null
                ELSE e.communities[0]
            END AS community_id
            WHERE community_id IS NOT NULL

            MERGE (c:`__Community__` {id: 'lpa-' + toString(community_id)})
            ON CREATE SET c.level = 0, c.algorithm = 'label_propagation'

            MERGE (e)-[:IN_COMMUNITY]->(c)
            RETURN count(*) AS saved_count
            """
            )

            saved_count = result[0]["saved_count"] if result else 0
            print(f"Label Propagation: 保存了 {saved_count} 个社区关系")

            return {"saved_communities": saved_count}

        except Exception as e:
            print(f"社区保存失败: {e}")
            return self._save_communities_fallback()

    def _save_communities_fallback(self) -> Dict[str, int]:
        """备用保存方法：最简单的保存逻辑"""
        print("使用备用方法保存社区...")

        try:
            result = self.graph.query(
                """
            MATCH (e:`__Entity__`)
            WHERE e.communities IS NOT NULL AND size(e.communities) > 0
            WITH e, e.communities[0] AS community_id
            MERGE (c:`__Community__` {id: 'lpa-' + toString(community_id)})
            ON CREATE SET c.level = 0, c.algorithm = 'label_propagation'
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
