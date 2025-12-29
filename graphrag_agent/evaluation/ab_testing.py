"""
简单的 A/B 测试框架

用于比较不同Agent配置、提示词模板或模型的性能。
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ABTestVariant:
    """A/B 测试变体"""

    name: str
    description: str
    config: Dict[str, Any]
    traffic_split: float = 0.5  # 流量分配比例 (0.0-1.0)


@dataclass
class ABTestResult:
    """A/B 测试结果"""

    variant_name: str
    query: str
    answer: str
    latency_ms: float
    success: bool
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ABTestFramework:
    """
    A/B 测试框架

    使用示例:
        >>> # 定义两个变体
        >>> variant_a = ABTestVariant(
        ...     name="gpt-4o",
        ...     description="使用 GPT-4o 模型",
        ...     config={"model": "gpt-4o", "temperature": 0.7}
        ... )
        >>> variant_b = ABTestVariant(
        ...     name="gpt-4o-mini",
        ...     description="使用 GPT-4o-mini 模型",
        ...     config={"model": "gpt-4o-mini", "temperature": 0.7}
        ... )
        >>>
        >>> # 创建测试
        >>> framework = ABTestFramework(
        ...     test_name="model_comparison",
        ...     variant_a=variant_a,
        ...     variant_b=variant_b
        ... )
        >>>
        >>> # 运行测试
        >>> queries = ["问题1", "问题2", "问题3"]
        >>> results = framework.run_test(queries, agent_callable)
        >>>
        >>> # 分析结果
        >>> report = framework.generate_report()
        >>> print(report)
    """

    def __init__(
        self, test_name: str, variant_a: ABTestVariant, variant_b: ABTestVariant, results_dir: str = "./ab_test_results"
    ):
        """
        初始化 A/B 测试框架

        Args:
            test_name: 测试名称
            variant_a: 变体 A
            variant_b: 变体 B
            results_dir: 结果保存目录
        """
        self.test_name = test_name
        self.variant_a = variant_a
        self.variant_b = variant_b

        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.results_a: List[ABTestResult] = []
        self.results_b: List[ABTestResult] = []

    def run_test(self, queries: List[str], agent_callable: Any, variant_override: Optional[str] = None) -> Dict[str, List[ABTestResult]]:
        """
        运行 A/B 测试

        Args:
            queries: 测试查询列表
            agent_callable: Agent 调用函数（接受 query 和 config 参数）
            variant_override: 强制使用某个变体（"a" 或 "b"），用于对比测试

        Returns:
            测试结果 {"variant_a": [...], "variant_b": [...]}
        """
        import random

        logger.info(f"Starting A/B test: {self.test_name} with {len(queries)} queries")

        for i, query in enumerate(queries):
            # 流量分配
            if variant_override:
                use_variant_a = variant_override.lower() == "a"
            else:
                use_variant_a = random.random() < self.variant_a.traffic_split

            variant = self.variant_a if use_variant_a else self.variant_b
            results_list = self.results_a if use_variant_a else self.results_b

            logger.info(f"Query {i+1}/{len(queries)}: Testing with variant '{variant.name}'")

            # 执行测试
            start_time = time.time()
            try:
                answer = agent_callable(query=query, config=variant.config)
                latency_ms = (time.time() - start_time) * 1000
                success = True
                error = None
            except Exception as e:
                answer = ""
                latency_ms = (time.time() - start_time) * 1000
                success = False
                error = str(e)
                logger.error(f"Variant '{variant.name}' failed: {e}")

            # 记录结果
            result = ABTestResult(
                variant_name=variant.name,
                query=query,
                answer=answer,
                latency_ms=latency_ms,
                success=success,
                error=error,
                metadata={"config": variant.config},
            )
            results_list.append(result)

        # 保存结果
        self.save_results()

        return {"variant_a": self.results_a, "variant_b": self.results_b}

    def generate_report(self) -> Dict[str, Any]:
        """
        生成测试报告

        Returns:
            测试报告 (包含统计数据)
        """
        report = {
            "test_name": self.test_name,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "variant_a": self._compute_stats(self.variant_a, self.results_a),
            "variant_b": self._compute_stats(self.variant_b, self.results_b),
            "winner": self._determine_winner(),
        }

        logger.info(f"Test report generated for '{self.test_name}'")
        return report

    def _compute_stats(self, variant: ABTestVariant, results: List[ABTestResult]) -> Dict[str, Any]:
        """计算变体统计数据"""
        if not results:
            return {
                "name": variant.name,
                "description": variant.description,
                "total_queries": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
            }

        successful = [r for r in results if r.success]
        latencies = [r.latency_ms for r in results if r.success]

        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0

        return {
            "name": variant.name,
            "description": variant.description,
            "config": variant.config,
            "total_queries": len(results),
            "successful_queries": len(successful),
            "success_rate": len(successful) / len(results) * 100,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
            "p95_latency_ms": p95_latency,
        }

    def _determine_winner(self) -> str:
        """确定获胜变体（基于成功率和延迟）"""
        stats_a = self._compute_stats(self.variant_a, self.results_a)
        stats_b = self._compute_stats(self.variant_b, self.results_b)

        # 成功率优先
        if stats_a["success_rate"] > stats_b["success_rate"]:
            return self.variant_a.name
        elif stats_a["success_rate"] < stats_b["success_rate"]:
            return self.variant_b.name
        else:
            # 成功率相同，比较延迟
            if stats_a["avg_latency_ms"] < stats_b["avg_latency_ms"]:
                return self.variant_a.name
            else:
                return self.variant_b.name

    def save_results(self):
        """保存测试结果到文件"""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = self.results_dir / f"{self.test_name}_{timestamp}.json"

        results_data = {
            "test_name": self.test_name,
            "timestamp": timestamp,
            "variant_a": {
                "config": self.variant_a.config,
                "results": [
                    {
                        "query": r.query,
                        "answer": r.answer,
                        "latency_ms": r.latency_ms,
                        "success": r.success,
                        "error": r.error,
                    }
                    for r in self.results_a
                ],
            },
            "variant_b": {
                "config": self.variant_b.config,
                "results": [
                    {
                        "query": r.query,
                        "answer": r.answer,
                        "latency_ms": r.latency_ms,
                        "success": r.success,
                        "error": r.error,
                    }
                    for r in self.results_b
                ],
            },
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(results_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Results saved to {filename}")

    def print_report(self):
        """打印测试报告"""
        report = self.generate_report()

        print(f"\n{'='*60}")
        print(f"A/B 测试报告: {report['test_name']}")
        print(f"时间: {report['timestamp']}")
        print(f"{'='*60}\n")

        print(f"📊 变体 A: {report['variant_a']['name']}")
        print(f"   描述: {report['variant_a']['description']}")
        print(f"   查询数: {report['variant_a']['total_queries']}")
        print(f"   成功率: {report['variant_a']['success_rate']:.1f}%")
        print(f"   平均延迟: {report['variant_a']['avg_latency_ms']:.2f}ms")
        print(f"   P95延迟: {report['variant_a']['p95_latency_ms']:.2f}ms\n")

        print(f"📊 变体 B: {report['variant_b']['name']}")
        print(f"   描述: {report['variant_b']['description']}")
        print(f"   查询数: {report['variant_b']['total_queries']}")
        print(f"   成功率: {report['variant_b']['success_rate']:.1f}%")
        print(f"   平均延迟: {report['variant_b']['avg_latency_ms']:.2f}ms")
        print(f"   P95延迟: {report['variant_b']['p95_latency_ms']:.2f}ms\n")

        print(f"🏆 获胜者: {report['winner']}\n")
        print(f"{'='*60}\n")
