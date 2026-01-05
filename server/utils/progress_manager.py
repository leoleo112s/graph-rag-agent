"""
SSE 进度管理器（单例模式）

用于在后台任务和 SSE 接口之间共享构建进度状态。
与 WebSocket 方案互补，提供更轻量的单向推送方案。
"""

import asyncio
import json
import logging
import threading
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

_LOGGER = logging.getLogger(__name__)


class BuildStage(str, Enum):
    """构建阶段枚举（标准化）"""

    IDLE = "idle"
    INITIALIZING = "initializing"
    DETECTING_CHANGES = "detecting_changes"
    CHUNKING = "chunking"
    ENTITY_EXTRACTION = "entity_extraction"
    ENTITY_DISAMBIGUATION = "entity_disambiguation"
    INDEXING = "indexing"
    COMMUNITY_DETECTION = "community_detection"
    COMPLETED = "completed"
    FAILED = "failed"


# 阶段显示名称映射（用于前端展示）
STAGE_DISPLAY_NAMES = {
    BuildStage.IDLE: "空闲",
    BuildStage.INITIALIZING: "初始化",
    BuildStage.DETECTING_CHANGES: "检测文件变化",
    BuildStage.CHUNKING: "文档分块",
    BuildStage.ENTITY_EXTRACTION: "实体关系提取",
    BuildStage.ENTITY_DISAMBIGUATION: "实体消歧",
    BuildStage.INDEXING: "向量索引构建",
    BuildStage.COMMUNITY_DETECTION: "社区检测",
    BuildStage.COMPLETED: "已完成",
    BuildStage.FAILED: "失败",
}


# 阶段进度权重（用于计算总进度）
STAGE_WEIGHTS = {
    BuildStage.IDLE: 0,
    BuildStage.INITIALIZING: 5,
    BuildStage.DETECTING_CHANGES: 10,
    BuildStage.CHUNKING: 20,
    BuildStage.ENTITY_EXTRACTION: 60,
    BuildStage.ENTITY_DISAMBIGUATION: 75,
    BuildStage.INDEXING: 85,
    BuildStage.COMMUNITY_DETECTION: 95,
    BuildStage.COMPLETED: 100,
    BuildStage.FAILED: 0,
}


class ProgressManager:
    """
    SSE 进度管理器（线程安全单例）

    功能：
    - 维护当前构建进度状态
    - 支持多个 SSE 客户端订阅
    - 线程安全的状态更新
    - 自动清理过期日志
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(ProgressManager, cls).__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        """初始化状态"""
        self.current_status: Dict[str, Any] = {
            "percent": 0,
            "stage": "idle",
            "details": "等待开始",
            "logs": [],
            "stats": {"l0_files": 0, "l1_tasks": 0, "entities": 0, "relations": 0},
            "last_update": datetime.now().isoformat(),
            "start_time": None,  # 构建开始时间（ISO格式字符串）
        }

        # 用于通知 SSE 有新数据的事件
        self._events: List[asyncio.Event] = []
        self._events_lock = asyncio.Lock()

    async def update(
        self,
        percent: Optional[int] = None,
        stage: Optional[str] = None,
        details: Optional[str] = None,
        log: Optional[str] = None,
        stats: Optional[Dict[str, int]] = None,
    ):
        """
        更新进度状态并通知所有订阅者

        Args:
            percent: 进度百分比（0-100）
            stage: 当前阶段（idle, init, detect_changes, entity_extraction, etc.）
            details: 详细描述
            log: 日志消息（会添加到日志列表）
            stats: 统计数据（文件数、实体数等）
        """
        updated = False

        if percent is not None:
            self.current_status["percent"] = min(100, max(0, percent))
            updated = True

        if stage is not None:
            self.current_status["stage"] = stage
            updated = True

        if details is not None:
            self.current_status["details"] = details
            updated = True

        if log is not None:
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_entry = f"[{timestamp}] {log}"
            self.current_status["logs"].append(log_entry)

            # 只保留最近 50 条日志
            if len(self.current_status["logs"]) > 50:
                self.current_status["logs"].pop(0)

            updated = True

        if stats is not None:
            self.current_status["stats"].update(stats)
            updated = True

        if updated:
            self.current_status["last_update"] = datetime.now().isoformat()
            await self._notify_subscribers()

    async def _notify_subscribers(self):
        """通知所有订阅的 SSE 客户端"""
        async with self._events_lock:
            for event in self._events:
                event.set()

    async def subscribe(self) -> asyncio.Event:
        """
        订阅进度更新

        Returns:
            asyncio.Event: 用于等待更新的事件对象
        """
        event = asyncio.Event()
        async with self._events_lock:
            self._events.append(event)
        _LOGGER.info(f"新的 SSE 订阅者，当前订阅数: {len(self._events)}")
        return event

    async def unsubscribe(self, event: asyncio.Event):
        """
        取消订阅

        Args:
            event: 订阅时返回的事件对象
        """
        async with self._events_lock:
            if event in self._events:
                self._events.remove(event)
        _LOGGER.info(f"SSE 订阅者断开，剩余订阅数: {len(self._events)}")

    def get_current_status(self) -> Dict[str, Any]:
        """
        获取当前状态快照

        Returns:
            当前进度状态的副本
        """
        return self.current_status.copy()

    def update_status(self, stage: str, percent: int = 0, details: str = "", log: Optional[str] = None):
        """
        同步更新状态（用于非异步环境，如后台线程）

        Args:
            stage: 当前阶段
            percent: 进度百分比
            details: 详细描述
            log: 日志消息
        """
        # 更新状态
        self.current_status["stage"] = stage
        self.current_status["percent"] = min(100, max(0, percent))
        self.current_status["details"] = details

        if log:
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_entry = f"[{timestamp}] {log}"
            self.current_status["logs"].append(log_entry)

            # 只保留最近 50 条日志
            if len(self.current_status["logs"]) > 50:
                self.current_status["logs"].pop(0)

        self.current_status["last_update"] = datetime.now().isoformat()

        # 在事件循环中通知订阅者（如果有的话）
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._notify_subscribers())
        except RuntimeError:
            # 如果没有事件循环，跳过通知
            pass

    async def event_generator(self):
        """
        SSE 事件生成器

        生成 Server-Sent Events 格式的数据流。
        当状态更新时，会自动推送最新状态到客户端。

        Yields:
            Dict: SSE 事件数据（包含 event 和 data 字段）
        """
        # 订阅更新事件
        event = await self.subscribe()

        try:
            # 立即发送当前状态
            yield {
                "event": "connected",
                "data": json.dumps(
                    {"message": "SSE 连接成功", "timestamp": datetime.now().isoformat()}, ensure_ascii=False
                ),
            }

            yield {"event": "status", "data": json.dumps(self.current_status, ensure_ascii=False)}

            # 持续监听更新
            while True:
                # 等待状态更新
                await event.wait()
                event.clear()

                # 发送更新后的状态
                yield {"event": "status", "data": json.dumps(self.current_status, ensure_ascii=False)}

        except asyncio.CancelledError:
            _LOGGER.info("SSE 连接被取消")
        except Exception as exc:
            _LOGGER.exception(f"SSE 事件生成器错误: {exc}")
        finally:
            # 清理订阅
            await self.unsubscribe(event)

    def start_build(self):
        """开始构建（记录开始时间）"""
        self.current_status["start_time"] = datetime.now().isoformat()
        self.current_status["percent"] = 0
        self.current_status["stage"] = "initializing"
        self.current_status["details"] = "正在初始化..."
        self.current_status["last_update"] = datetime.now().isoformat()

    def reset(self):
        """重置状态到初始值"""
        self.current_status = {
            "percent": 0,
            "stage": "idle",
            "details": "等待开始",
            "logs": [],
            "stats": {"l0_files": 0, "l1_tasks": 0, "entities": 0, "relations": 0},
            "last_update": datetime.now().isoformat(),
            "start_time": None,
        }

    def has_subscribers(self) -> bool:
        """
        检查是否有活动的订阅者

        Returns:
            是否有订阅者
        """
        return len(self._events) > 0


# 全局单例
progress_manager = ProgressManager()


def get_progress_manager() -> ProgressManager:
    """
    获取全局进度管理器实例

    Returns:
        ProgressManager 单例
    """
    return progress_manager
