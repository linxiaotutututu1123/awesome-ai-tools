"""
market_gateway/base.py
网关抽象基类定义。

设计原则：
- 定义统一的网关接口契约
- 支持 CTP/SimNow/IB 等多种实现
- 生命周期管理：connect → subscribe → on_tick → disconnect
- 异步优先：使用 asyncio 实现

# RISK: 子类可能未正确实现抽象方法
# 缓解措施: 使用 ABC 强制实现，单元测试覆盖

Author: AI Quant Team
Version: 1.0.0
"""

from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Callable, Awaitable, Final, AsyncIterator
from datetime import datetime, timezone
import asyncio
import logging

from .models import TickData, DepthData, BarData
from .config import GatewayConfig
from .exceptions import GatewayException

__all__: list[str] = [
    "GatewayState",
    "AbstractGateway",
    "TickCallback",
    "DepthCallback",
    "BarCallback",
    "StateCallback",
]

# WHY: 类型别名提升代码可读性
TickCallback = Callable[[TickData], Awaitable[None]]
DepthCallback = Callable[[DepthData], Awaitable[None]]
BarCallback = Callable[[BarData], Awaitable[None]]
StateCallback = Callable[["GatewayState", "GatewayState"], Awaitable[None]]


class GatewayState(Enum):
    """
    网关状态枚举。

    状态转换图：
    DISCONNECTED → CONNECTING → CONNECTED → SUBSCRIBING → RUNNING
                 ↘         ↙                          ↓
                   RECONNECTING ←←←←←←←←←←←←←←←← ERROR
    """
    DISCONNECTED = auto()  # 未连接
    CONNECTING = auto()    # 连接中
    CONNECTED = auto()     # 已连接（未订阅）
    SUBSCRIBING = auto()   # 订阅中
    RUNNING = auto()       # 运行中（正常接收数据）
    RECONNECTING = auto()  # 重连中
    ERROR = auto()         # 错误状态
    STOPPED = auto()       # 已停止


class AbstractGateway(ABC):
    """
    行情网关抽象基类。

    所有具体网关实现（CTP/SimNow/IB）必须继承此类。

    Attributes:
        config: 网关配置
        state: 当前状态
        subscribed_symbols: 已订阅合约集合
        tick_queue: Tick数据异步队列

    Lifecycle:
        1. __init__: 初始化配置
        2. connect: 连接到服务器
        3. subscribe: 订阅合约
        4. on_tick/on_depth: 处理行情回调
        5. disconnect: 断开连接

    Example:
        >>> gateway = CtpMarketGateway(config)
        >>> await gateway.connect()
        >>> await gateway.subscribe(["IF2401", "IC2401"])
        >>> async for tick in gateway.tick_stream():
        ...     process(tick)
        >>> await gateway.disconnect()
    """

    # WHY: 默认队列大小，防止消费慢时内存爆炸
    _DEFAULT_QUEUE_SIZE: Final[int] = 10000

    def __init__(self, config: GatewayConfig) -> None:
        """
        初始化网关。

        Args:
            config: 网关配置对象

        Raises:
            ValueError: 配置校验失败
        """
        self._config: Final[GatewayConfig] = config
        self._state: GatewayState = GatewayState.DISCONNECTED
        self._subscribed_symbols: set[str] = set()
        self._pending_symbols: set[str] = set()  # WHY: 待订阅队列

        # WHY: 使用 asyncio.Queue 实现生产者-消费者模式
        self._tick_queue: asyncio.Queue[TickData] = asyncio.Queue(
            maxsize=self._DEFAULT_QUEUE_SIZE
        )
        self._depth_queue: asyncio.Queue[DepthData] = asyncio.Queue(
            maxsize=self._DEFAULT_QUEUE_SIZE
        )

        # WHY: 回调函数列表，支持多个消费者
        self._tick_callbacks: list[TickCallback] = []
        self._depth_callbacks: list[DepthCallback] = []
        self._bar_callbacks: list[BarCallback] = []
        self._state_callbacks: list[StateCallback] = []

        # WHY: 日志使用网关名称区分
        self._logger = logging.getLogger(
            f"gateway.{config.gateway_name}"
        )

        # WHY: 连接状态追踪
        self._connected_at: datetime | None = None
        self._last_tick_at: datetime | None = None
        self._reconnect_count: int = 0

    # =========================================================================
    # 属性访问器
    # =========================================================================

    @property
    def config(self) -> GatewayConfig:
        """获取网关配置（只读）。"""
        return self._config

    @property
    def state(self) -> GatewayState:
        """获取当前状态。"""
        return self._state

    @property
    def is_connected(self) -> bool:
        """是否已连接。"""
        return self._state in (
            GatewayState.CONNECTED,
            GatewayState.SUBSCRIBING,
            GatewayState.RUNNING,
        )

    @property
    def is_running(self) -> bool:
        """是否正在运行。"""
        return self._state == GatewayState.RUNNING

    @property
    def subscribed_symbols(self) -> frozenset[str]:
        """已订阅合约集合（只读）。"""
        return frozenset(self._subscribed_symbols)

    @property
    def subscription_count(self) -> int:
        """当前订阅数量。"""
        return len(self._subscribed_symbols)

    @property
    def gateway_name(self) -> str:
        """网关名称。"""
        return self._config.gateway_name

    # =========================================================================
    # 状态管理
    # =========================================================================

    async def _set_state(self, new_state: GatewayState) -> None:
        """
        设置网关状态并触发回调。

        Args:
            new_state: 新状态
        """
        old_state = self._state
        if old_state == new_state:
            return

        self._state = new_state
        self._logger.info(f"状态变更: {old_state.name} → {new_state.name}")

        # WHY: 异步通知所有状态监听器
        for callback in self._state_callbacks:
            try:
                await callback(old_state, new_state)
            except Exception as e:
                self._logger.error(f"状态回调异常: {e}", exc_info=True)

    # =========================================================================
    # 回调注册
    # =========================================================================

    def on_tick(self, callback: TickCallback) -> None:
        """注册Tick数据回调。"""
        self._tick_callbacks.append(callback)

    def on_depth(self, callback: DepthCallback) -> None:
        """注册深度数据回调。"""
        self._depth_callbacks.append(callback)

    def on_bar(self, callback: BarCallback) -> None:
        """注册K线数据回调。"""
        self._bar_callbacks.append(callback)

    def on_state_change(self, callback: StateCallback) -> None:
        """注册状态变更回调。"""
        self._state_callbacks.append(callback)

    # =========================================================================
    # 抽象方法（子类必须实现）
    # =========================================================================

    @abstractmethod
    async def connect(self) -> None:
        """
        连接到行情服务器。

        Raises:
            ConnectionException: 连接失败
            AuthenticationException: 认证失败
            ConnectionTimeoutException: 连接超时

        Example:
            >>> await gateway.connect()
            >>> assert gateway.is_connected
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """
        断开连接。

        Raises:
            GatewayException: 断开失败
        """
        ...

    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> list[str]:
        """
        订阅合约行情。

        Args:
            symbols: 合约代码列表，支持通配符（如 "IF*"）

        Returns:
            实际订阅成功的合约列表

        Raises:
            SubscriptionLimitExceededException: 超过订阅限制
            SymbolNotFoundException: 合约不存在
        """
        ...

    @abstractmethod
    async def unsubscribe(self, symbols: list[str]) -> list[str]:
        """
        退订合约行情。

        Args:
            symbols: 合约代码列表

        Returns:
            实际退订成功的合约列表
        """
        ...

    @abstractmethod
    async def _do_reconnect(self) -> bool:
        """
        执行重连逻辑（子类实现）。

        Returns:
            重连是否成功
        """
        ...

    # =========================================================================
    # 通用方法
    # =========================================================================

    async def tick_stream(self) -> "AsyncIterator[TickData]":
        """
        异步迭代器：获取Tick数据流。

        Yields:
            TickData 对象

        Example:
            >>> async for tick in gateway.tick_stream():
            ...     print(tick.last_price)
        """
        while self._state != GatewayState.STOPPED:
            try:
                # WHY: 使用超时防止永久阻塞
                tick = await asyncio.wait_for(
                    self._tick_queue.get(),
                    timeout=1.0,
                )
                yield tick
            except asyncio.TimeoutError:
                continue

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"name={self.gateway_name}, "
            f"state={self._state.name}, "
            f"subscriptions={self.subscription_count})"
        )
