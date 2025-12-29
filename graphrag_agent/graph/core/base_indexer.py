import concurrent.futures
import time
from typing import Any, List, Optional

from graphrag_agent.config.settings import MAX_WORKERS as CONFIG_MAX_WORKERS
from graphrag_agent.utils.logging_config import get_logger
from graphrag_agent.utils.process_result import ProcessResult

logger = get_logger(__name__)


class BaseIndexer:
    """
    基础索引器类，为各种索引器提供通用功能。
    包含批处理、并行计算和性能监控逻辑。
    """

    def __init__(self, batch_size: int = 100, max_workers: int = 4):
        """
        初始化基础索引器

        Args:
            batch_size: 批处理大小
            max_workers: 并行工作线程数
        """
        # 批处理和并行参数
        self.batch_size = batch_size
        self.max_workers = max_workers

        # 性能监控参数
        self.embedding_time = 0
        self.db_time = 0

    def _create_indexes(self) -> None:
        """创建必要的索引以优化查询性能 - 由子类实现"""
        raise NotImplementedError("子类必须实现此方法")

    def get_optimal_batch_size(self, total_items: int) -> int:
        # 使用配置的批处理大小作为上限
        optimal_size = min(self.batch_size, max(20, total_items // 10))
        return optimal_size

    def batch_process_with_progress(
        self, items: List[Any], process_func, batch_size: Optional[int] = None, desc: str = "处理中"
    ) -> None:
        """
        通用批处理逻辑，带进度跟踪

        Args:
            items: 待处理项目列表
            process_func: 处理单个批次的函数
            batch_size: 批处理大小，如果不提供则使用最优值
            desc: 进度描述
        """
        if not items:
            logger.warning(f"没有找到需要处理的项目")
            return

        # 计算批处理参数
        item_count = len(items)
        optimal_batch_size = batch_size or self.get_optimal_batch_size(item_count)
        total_batches = (item_count + optimal_batch_size - 1) // optimal_batch_size

        logger.info(f"{desc}: 共{item_count}项，批次大小: {optimal_batch_size}, 总批次: {total_batches}")

        # 保存每个批次的处理时间
        batch_times = []

        # 批量处理
        for batch_index in range(total_batches):
            batch_start = time.time()

            start_idx = batch_index * optimal_batch_size
            end_idx = min(start_idx + optimal_batch_size, item_count)
            batch = items[start_idx:end_idx]

            # 处理当前批次
            process_func(batch, batch_index)

            # 计算和显示进度
            batch_end = time.time()
            batch_time = batch_end - batch_start
            batch_times.append(batch_time)

            # 计算平均时间和剩余时间
            avg_time = sum(batch_times) / len(batch_times)
            remaining_batches = total_batches - (batch_index + 1)
            estimated_remaining = avg_time * remaining_batches

            logger.info(
                f"已处理批次 {batch_index+1}/{total_batches}, "
                f"批次耗时: {batch_time:.2f}秒, "
                f"平均: {avg_time:.2f}秒/批, "
                f"预计剩余: {estimated_remaining:.2f}秒"
            )

    def process_in_parallel(self, items: List[Any], process_func) -> List[ProcessResult]:
        """
        并行处理项目（改进版，支持结构化错误处理）

        使用预分配列表 + 按索引填充的方式确保：
        1. 结果顺序与输入 items 严格一致
        2. 每个结果包含成功/失败状态和详细错误信息
        3. 支持错误分类（临时错误/数据库错误/未知错误）

        Args:
            items: 待处理项目列表
            process_func: 处理单个项目的函数

        Returns:
            List[ProcessResult]: 处理结果列表，顺序与 items 一致
        """
        if not items:
            return []

        max_workers = min(self.max_workers, CONFIG_MAX_WORKERS)
        # 预分配固定长度的列表，确保索引对齐
        results: List[ProcessResult] = [None] * len(items)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 记录 Future -> Index 的映射
            future_to_index = {executor.submit(process_func, item): i for i, item in enumerate(items)}

            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result = future.result()
                    # 成功：按原始索引归位
                    results[index] = ProcessResult.success_result(data=result, index=index)
                except TimeoutError as e:
                    # 临时错误：超时（可重试）
                    logger.warning(f"并行处理超时 (索引 {index}): {e}")
                    results[index] = ProcessResult.failure_result(error=e, index=index, error_type="transient")
                except ConnectionError as e:
                    # 临时错误：连接问题（可重试）
                    logger.warning(f"并行处理连接错误 (索引 {index}): {e}")
                    results[index] = ProcessResult.failure_result(error=e, index=index, error_type="transient")
                except Exception as e:
                    # 检查是否为数据库相关错误
                    error_type = (
                        "database" if "neo4j" in str(type(e)).lower() or "database" in str(e).lower() else "unknown"
                    )
                    logger.error(f"并行处理出错 (索引 {index}, 类型: {error_type}): {e}", exc_info=True)
                    results[index] = ProcessResult.failure_result(error=e, index=index, error_type=error_type)

        return results
