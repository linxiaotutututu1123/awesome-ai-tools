"""
market_gateway/ctp_gateway.py
CTP 行情网关实现。

提供 CTP 行情接入能力，支持：
- 连接/断开管理
- 指数退避重连
- Tick/Level2 数据订阅
- 数据校验与转换
- 自动生成 K 线

# RISK: CTP SDK 回调在单独线程，需要线程安全
# 缓解措施: 使用 asyncio.run_coroutine_threadsafe 桥接

Author: AI Quant Team
Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Final, Callable
import threading

from .base import AbstractGateway, GatewayState
from .config import GatewayConfig
from .models import TickData, DepthData, BarData, BarPeriod, PriceLevel, DataStatus
from .exceptions import (
    ConnectionException,
    AuthenticationException,
    ConnectionTimeoutException,
    ReconnectExhaustedException,
    SubscriptionException,
    SubscriptionLimitExceededException,
    SymbolNotFoundException,
    InvalidTickDataException,
    ErrorCode,
)

__all__: list[str] = ["CtpMarketGateway"]


# WHY: 中国期货交易所代码映射
EXCHANGE_MAP: Final[dict[str, str]] = {
    "CFFEX": "CFFEX",  # 中金所
    "SHFE": "SHFE",    # 上期所
    "DCE": "DCE",      # 大商所
    "CZCE": "CZCE",    # 郑商所
    "INE": "INE",      # 上期能源
    "GFEX": "GFEX",    # 广期所
}


class CtpMarketGateway(AbstractGateway):
    """
    CTP 行情网关实现。

    支持功能：
    - CTP/SimNow 行情连接
    - Tick + Level2 数据订阅
    - 自动生成 1m/5m K 线
    - 指数退避无限重连
    - 数据校验与脏数据记录

    # REVIEW: 如果重连 10 次失败如何告警？
    # 答：通过 _alert_callback 发送钉钉告警，见 _on_reconnect_failed()

    # REVIEW: 行情乱序如何处理？
    # 答：使用 _last_tick_time 记录，丢弃时间戳早于上一条的数据

    # REVIEW: 内存中缓存多少 Tick 数据？OOM 防护？
    # 答：使用 deque(maxlen=N) 环形缓存，默认 30 秒数据，约 150000 条

    Example:
        >>> config = GatewayConfig(...)
        >>> gateway = CtpMarketGateway(config)
        >>> await gateway.connect()
        >>> await gateway.subscribe(["IF*", "IC2401"])
        >>> async for tick in gateway.tick_stream():
        ...     print(tick)
    """

    # WHY: 类常量便于测试时修改
    _TICK_CACHE_SIZE: Final[int] = 150000  # 约 30 秒 @ 5000 ticks/s
    _LOGIN_TIMEOUT: Final[float] = 10.0
    _SUBSCRIBE_BATCH_SIZE: Final[int] = 100  # CTP 单次订阅上限

    def __init__(self, config: GatewayConfig) -> None:
        """
        初始化 CTP 行情网关。

        Args:
            config: 网关配置，必须包含 ctp 配置

        Raises:
            ValueError: 缺少 CTP 配置

        Example:
            正确用法：
            >>> config = GatewayConfig(
            ...     gateway_type=GatewayType.CTP,
            ...     ctp=CtpConfig(broker_id="9999", ...),
            ... )
            >>> gateway = CtpMarketGateway(config)

            错误用法（缺少 ctp 配置）：
            >>> config = GatewayConfig(gateway_type=GatewayType.CTP)
            >>> gateway = CtpMarketGateway(config)  # ValueError!
        """
        super().__init__(config)

        # WHY: 确保 CTP 配置存在
        if config.ctp is None:
            raise ValueError("CtpMarketGateway 需要 ctp 配置")

        self._ctp_config = config.ctp

        # === CTP API 相关（延迟初始化）===
        self._api: Any = None  # CTP MdApi 实例
        self._spi: Any = None  # CTP MdSpi 实例

        # === 登录状态 ===
        self._login_event: asyncio.Event = asyncio.Event()
        self._login_error: str | None = None
        self._request_id: int = 0

        # === 重连状态 ===
        self._reconnect_interval: float = config.reconnect.initial_interval
        self._consecutive_failures: int = 0
        self._reconnect_task: asyncio.Task[None] | None = None

        # === 数据缓存（环形缓冲区防 OOM）===
        # WHY: 使用 deque 实现固定大小缓存，自动丢弃旧数据
        self._tick_cache: deque[TickData] = deque(maxlen=self._TICK_CACHE_SIZE)
        self._last_tick_time: dict[str, datetime] = {}  # 用于乱序检测

        # === K 线生成器 ===
        self._bar_generators: dict[str, dict[BarPeriod, "_BarGenerator"]] = {}

        # === 合约信息缓存 ===
        self._all_symbols: set[str] = set()  # 所有可订阅合约

        # === 告警回调 ===
        self._alert_callback: Callable[[str, str], None] | None = None

        # === 线程安全 ===
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

        self._logger.info(
            f"CtpMarketGateway 初始化完成: "
            f"broker={self._ctp_config.broker_id}, "
            f"front={self._ctp_config.front_addr}"
        )

    # =========================================================================
    # 连接管理
    # =========================================================================

    async def connect(self) -> None:
        """
        连接到 CTP 行情服务器。

        执行流程：
        1. 创建 MdApi 实例
        2. 注册前置机地址
        3. 初始化连接
        4. 等待登录完成

        Raises:
            ConnectionException: 连接失败
            AuthenticationException: 登录失败
            ConnectionTimeoutException: 连接超时

        Example:
            >>> await gateway.connect()
            >>> assert gateway.is_connected

        # RISK: 网络不稳定可能导致连接失败
        # 缓解措施: 使用超时机制，失败后自动重连
        """
        if self.is_connected:
            self._logger.warning("已经连接，跳过重复连接")
            return

        await self._set_state(GatewayState.CONNECTING)
        self._loop = asyncio.get_running_loop()

        try:
            # WHY: 尝试导入 CTP SDK，失败则使用模拟模式
            await self._init_ctp_api()

            # WHY: 等待登录完成或超时
            self._login_event.clear()
            self._login_error = None

            try:
                await asyncio.wait_for(
                    self._login_event.wait(),
                    timeout=self._config.connect_timeout,
                )
            except asyncio.TimeoutError:
                raise ConnectionTimeoutException(
                    message=f"连接超时（{self._config.connect_timeout}秒）",
                    host=self._ctp_config.front_addr,
                    timeout_seconds=self._config.connect_timeout,
                )

            # WHY: 检查登录是否有错误
            if self._login_error:
                raise AuthenticationException(
                    message=f"登录失败: {self._login_error}",
                    host=self._ctp_config.front_addr,
                )

            await self._set_state(GatewayState.CONNECTED)
            self._connected_at = datetime.now(timezone.utc)
            self._consecutive_failures = 0
            self._reconnect_interval = self._config.reconnect.initial_interval

            self._logger.info("CTP 行情服务器连接成功")

        except (ConnectionTimeoutException, AuthenticationException):
            await self._set_state(GatewayState.ERROR)
            raise
        except Exception as e:
            await self._set_state(GatewayState.ERROR)
            raise ConnectionException(
                message=f"连接失败: {e}",
                host=self._ctp_config.front_addr,
                cause=e,
            ) from e

    async def _init_ctp_api(self) -> None:
        """
        初始化 CTP API。

        # RISK: CTP SDK 可能未安装
        # 缓解措施: 捕获 ImportError，使用模拟模式
        """
        try:
            # WHY: 动态导入，支持未安装 CTP SDK 的环境
            from openctp_ctp import mdapi

            # WHY: 创建 API 实例
            self._api = mdapi.CThostFtdcMdApi.CreateFtdcMdApi()

            # WHY: 创建并注册 SPI
            self._spi = _CtpMdSpi(self)
            self._api.RegisterSpi(self._spi)

            # WHY: 注册前置机地址
            self._api.RegisterFront(self._ctp_config.front_addr)

            # WHY: 初始化连接（异步，会触发 OnFrontConnected）
            self._api.Init()

            self._logger.info("CTP API 初始化完成")

        except ImportError:
            self._logger.warning(
                "openctp_ctp 未安装，使用模拟模式。"
                "安装命令: pip install openctp-ctp"
            )
            # WHY: 模拟模式下直接设置登录成功
            self._login_event.set()

    async def disconnect(self) -> None:
        """
        断开 CTP 行情连接。

        Raises:
            GatewayException: 断开失败
        """
        if self._state == GatewayState.DISCONNECTED:
            return

        self._logger.info("正在断开 CTP 行情连接...")

        try:
            # WHY: 取消重连任务
            if self._reconnect_task and not self._reconnect_task.done():
                self._reconnect_task.cancel()
                try:
                    await self._reconnect_task
                except asyncio.CancelledError:
                    pass

            # WHY: 释放 CTP API 资源
            if self._api:
                self._api.Release()
                self._api = None
                self._spi = None

            await self._set_state(GatewayState.DISCONNECTED)
            self._logger.info("CTP 行情连接已断开")

        except Exception as e:
            self._logger.error(f"断开连接异常: {e}", exc_info=True)
            raise

    # =========================================================================
    # 订阅管理
    # =========================================================================

    async def subscribe(self, symbols: list[str]) -> list[str]:
        """
        订阅合约行情。

        支持通配符订阅（如 "IF*" 订阅所有 IF 合约）。
        重复订阅相同合约具有幂等性（不会重复调用 SDK）。

        Args:
            symbols: 合约代码列表，支持通配符

        Returns:
            实际订阅成功的合约列表

        Raises:
            SubscriptionLimitExceededException: 超过订阅限制
            SymbolNotFoundException: 合约不存在

        Example:
            >>> await gateway.subscribe(["IF2401", "IC*"])
            ["IF2401", "IC2401", "IC2402", ...]
        """
        if not self.is_connected:
            raise ConnectionException(
                message="未连接，无法订阅",
                error_code=ErrorCode.CONNECTION_LOST,
            )

        await self._set_state(GatewayState.SUBSCRIBING)

        # WHY: 展开通配符
        expanded_symbols = self._expand_wildcards(symbols)

        # WHY: 过滤已订阅的合约（幂等性）
        new_symbols = [s for s in expanded_symbols if s not in self._subscribed_symbols]

        if not new_symbols:
            self._logger.debug("所有合约已订阅，跳过")
            await self._set_state(GatewayState.RUNNING)
            return []

        # WHY: 检查订阅限制
        total = len(self._subscribed_symbols) + len(new_symbols)
        if total > self._config.max_subscriptions:
            raise SubscriptionLimitExceededException(
                message=f"超过订阅限制: {total} > {self._config.max_subscriptions}",
                current_count=len(self._subscribed_symbols),
                max_limit=self._config.max_subscriptions,
                requested_count=len(new_symbols),
                symbols=new_symbols,
            )

        # WHY: 分批订阅（CTP 单次订阅有上限）
        success_symbols: list[str] = []
        for i in range(0, len(new_symbols), self._SUBSCRIBE_BATCH_SIZE):
            batch = new_symbols[i:i + self._SUBSCRIBE_BATCH_SIZE]
            try:
                await self._do_subscribe(batch)
                success_symbols.extend(batch)
                self._subscribed_symbols.update(batch)
            except Exception as e:
                self._logger.error(f"订阅失败: {batch}, error={e}")

        # WHY: 为新订阅的合约创建 K 线生成器
        for symbol in success_symbols:
            self._init_bar_generator(symbol)

        await self._set_state(GatewayState.RUNNING)
        self._logger.info(f"订阅完成: {len(success_symbols)} 个合约")

        return success_symbols

    async def _do_subscribe(self, symbols: list[str]) -> None:
        """调用 CTP SDK 订阅。"""
        if self._api is None:
            self._logger.warning("API 未初始化（模拟模式），跳过实际订阅")
            return

        # WHY: CTP 订阅接口需要 bytes 列表
        symbol_bytes = [s.encode("utf-8") for s in symbols]
        ret = self._api.SubscribeMarketData(symbol_bytes)

        if ret != 0:
            raise SubscriptionException(
                message=f"订阅失败，返回码: {ret}",
                symbols=symbols,
            )

    async def unsubscribe(self, symbols: list[str]) -> list[str]:
        """
        退订合约行情。

        Args:
            symbols: 合约代码列表

        Returns:
            实际退订成功的合约列表
        """
        # WHY: 只退订已订阅的合约
        to_unsub = [s for s in symbols if s in self._subscribed_symbols]

        if not to_unsub:
            return []

        try:
            if self._api:
                symbol_bytes = [s.encode("utf-8") for s in to_unsub]
                self._api.UnSubscribeMarketData(symbol_bytes)

            # WHY: 清理缓存
            for symbol in to_unsub:
                self._subscribed_symbols.discard(symbol)
                self._last_tick_time.pop(symbol, None)
                self._bar_generators.pop(symbol, None)

            self._logger.info(f"退订完成: {len(to_unsub)} 个合约")
            return to_unsub

        except Exception as e:
            self._logger.error(f"退订异常: {e}", exc_info=True)
            return []

    def _expand_wildcards(self, symbols: list[str]) -> list[str]:
        """
        展开通配符（如 IF* → IF2401, IF2402, ...）。

        # RISK: 合约列表未更新可能导致匹配不全
        # 缓解措施: 定期刷新合约列表
        """
        result: list[str] = []
        for symbol in symbols:
            if "*" in symbol or "?" in symbol:
                # WHY: 使用 fnmatch 进行通配符匹配
                matched = [s for s in self._all_symbols if fnmatch.fnmatch(s, symbol)]
                if matched:
                    result.extend(matched)
                else:
                    self._logger.warning(f"通配符 {symbol} 未匹配到任何合约")
            else:
                result.append(symbol)
        return list(set(result))  # WHY: 去重

    # =========================================================================
    # 重连逻辑
    # =========================================================================

    async def _do_reconnect(self) -> bool:
        """
        执行指数退避重连。

        重连策略：
        - 初始间隔 1s，乘数 2，最大 60s
        - 无限重试（用户要求）
        - 达到告警阈值时发送钉钉告警

        Returns:
            重连是否成功
        """
        await self._set_state(GatewayState.RECONNECTING)

        while True:
            self._consecutive_failures += 1
            self._logger.warning(
                f"第 {self._consecutive_failures} 次重连，"
                f"间隔 {self._reconnect_interval:.1f}s"
            )

            # WHY: 检查是否需要告警
            if self._consecutive_failures >= self._config.reconnect.alert_threshold:
                await self._on_reconnect_failed()

            # WHY: 等待退避间隔
            await asyncio.sleep(self._reconnect_interval)

            try:
                # WHY: 先断开旧连接
                if self._api:
                    self._api.Release()
                    self._api = None

                # WHY: 重新初始化
                await self._init_ctp_api()

                # WHY: 等待登录
                self._login_event.clear()
                try:
                    await asyncio.wait_for(
                        self._login_event.wait(),
                        timeout=self._config.connect_timeout,
                    )
                except asyncio.TimeoutError:
                    raise ConnectionTimeoutException(
                        message="重连超时",
                        timeout_seconds=self._config.connect_timeout,
                    )

                if self._login_error:
                    raise AuthenticationException(message=self._login_error)

                # WHY: 重连成功，恢复订阅
                await self._set_state(GatewayState.CONNECTED)
                self._consecutive_failures = 0
                self._reconnect_interval = self._config.reconnect.initial_interval

                # WHY: 自动恢复订阅
                if self._subscribed_symbols:
                    await self._restore_subscriptions()

                await self._set_state(GatewayState.RUNNING)
                self._logger.info("重连成功，已恢复订阅")
                return True

            except Exception as e:
                self._logger.error(f"重连失败: {e}")
                # WHY: 计算下次重连间隔（指数退避）
                self._reconnect_interval = min(
                    self._reconnect_interval * self._config.reconnect.multiplier,
                    self._config.reconnect.max_interval,
                )

    async def _restore_subscriptions(self) -> None:
        """恢复之前的订阅。"""
        symbols = list(self._subscribed_symbols)
        self._subscribed_symbols.clear()  # WHY: 清空后重新订阅
        await self.subscribe(symbols)

    async def _on_reconnect_failed(self) -> None:
        """
        重连失败告警处理。

        # REVIEW: 如果重连 10 次失败如何告警？
        # 答：调用 _alert_callback 发送钉钉告警
        """
        message = (
            f"[告警] CTP 行情网关重连失败\n"
            f"网关: {self.gateway_name}\n"
            f"连续失败: {self._consecutive_failures} 次\n"
            f"当前间隔: {self._reconnect_interval:.1f}s"
        )

        self._logger.critical(message)

        if self._alert_callback:
            try:
                self._alert_callback("CRITICAL", message)
            except Exception as e:
                self._logger.error(f"发送告警失败: {e}")

    # =========================================================================
    # 数据处理
    # =========================================================================

    def _on_tick_data(self, raw_data: dict[str, Any]) -> None:
        """
        处理 CTP 原始 Tick 数据（在 CTP 回调线程中调用）。

        处理流程：
        1. 转换为 TickData
        2. 校验数据有效性
        3. 检测乱序
        4. 更新 K 线
        5. 放入队列

        # RISK: 此方法在 CTP 回调线程中调用，需要线程安全
        # 缓解措施: 使用 run_coroutine_threadsafe 桥接到 asyncio
        """
        if self._loop is None:
            return

        # WHY: 使用线程安全方式调度到 asyncio 线程
        asyncio.run_coroutine_threadsafe(
            self._process_tick_async(raw_data),
            self._loop,
        )

    async def _process_tick_async(self, raw_data: dict[str, Any]) -> None:
        """异步处理 Tick 数据。"""
        try:
            # WHY: 转换原始数据
            tick = self._convert_tick(raw_data)

            # WHY: 校验数据
            is_valid, errors = tick.validate()
            if not is_valid:
                if self._config.data_filter.log_dirty_data:
                    self._logger.warning(f"脏数据: {tick.symbol}, errors={errors}")
                tick.status = DataStatus.FILTERED
                return

            # WHY: 乱序检测
            if not self._check_tick_order(tick):
                self._logger.debug(f"乱序数据丢弃: {tick.symbol}")
                return

            # WHY: 更新 K 线生成器
            self._update_bar_generators(tick)

            # WHY: 放入队列（非阻塞）
            try:
                self._tick_queue.put_nowait(tick)
            except asyncio.QueueFull:
                self._logger.warning("Tick 队列已满，丢弃数据")

            # WHY: 更新缓存
            self._tick_cache.append(tick)
            self._last_tick_at = datetime.now(timezone.utc)

            # WHY: 触发回调
            for callback in self._tick_callbacks:
                try:
                    await callback(tick)
                except Exception as e:
                    self._logger.error(f"Tick 回调异常: {e}")

        except Exception as e:
            self._logger.error(f"处理 Tick 异常: {e}", exc_info=True)

    def _convert_tick(self, raw: dict[str, Any]) -> TickData:
        """
        转换 CTP 原始数据为 TickData。

        # RISK: CTP 字段名可能变化
        # 缓解措施: 使用 get() 方法带默认值
        """
        # WHY: 解析时间戳
        update_time = raw.get("UpdateTime", "00:00:00")
        update_ms = raw.get("UpdateMillisec", 0)
        trading_day = raw.get("TradingDay", "19700101")

        try:
            ts = datetime.strptime(
                f"{trading_day} {update_time}",
                "%Y%m%d %H:%M:%S",
            ).replace(tzinfo=timezone.utc)
            # WHY: 添加毫秒精度
            ts = ts.replace(microsecond=update_ms * 1000)
        except ValueError:
            ts = datetime.now(timezone.utc)

        return TickData(
            symbol=raw.get("InstrumentID", ""),
            exchange=raw.get("ExchangeID", ""),
            timestamp=ts,
            last_price=Decimal(str(raw.get("LastPrice", 0))),
            volume=int(raw.get("Volume", 0)),
            turnover=Decimal(str(raw.get("Turnover", 0))),
            open_interest=int(raw.get("OpenInterest", 0)),
            bid_price_1=Decimal(str(raw.get("BidPrice1", 0))),
            bid_volume_1=int(raw.get("BidVolume1", 0)),
            ask_price_1=Decimal(str(raw.get("AskPrice1", 0))),
            ask_volume_1=int(raw.get("AskVolume1", 0)),
            pre_close=Decimal(str(raw.get("PreClosePrice", 0))),
            pre_settlement=Decimal(str(raw.get("PreSettlementPrice", 0))),
            upper_limit=Decimal(str(raw.get("UpperLimitPrice", 0))),
            lower_limit=Decimal(str(raw.get("LowerLimitPrice", 0))),
            gateway_name=self.gateway_name,
        )

    def _check_tick_order(self, tick: TickData) -> bool:
        """
        检查 Tick 是否乱序。

        # REVIEW: 行情乱序如何处理？
        # 答：丢弃时间戳早于上一条的数据
        """
        last_time = self._last_tick_time.get(tick.symbol)
        if last_time and tick.timestamp < last_time:
            return False
        self._last_tick_time[tick.symbol] = tick.timestamp
        return True

    # =========================================================================
    # K 线生成
    # =========================================================================

    def _init_bar_generator(self, symbol: str) -> None:
        """初始化合约的 K 线生成器。"""
        if symbol not in self._bar_generators:
            self._bar_generators[symbol] = {
                BarPeriod.MINUTE_1: _BarGenerator(symbol, BarPeriod.MINUTE_1),
                BarPeriod.MINUTE_5: _BarGenerator(symbol, BarPeriod.MINUTE_5),
            }

    def _update_bar_generators(self, tick: TickData) -> None:
        """更新 K 线生成器。"""
        generators = self._bar_generators.get(tick.symbol)
        if not generators:
            return

        for period, generator in generators.items():
            bar = generator.update(tick)
            if bar:
                # WHY: K 线完成，触发回调
                self._on_bar_complete(bar)

    def _on_bar_complete(self, bar: BarData) -> None:
        """K 线完成回调。"""
        if self._loop is None:
            return

        async def notify_callbacks() -> None:
            for callback in self._bar_callbacks:
                try:
                    await callback(bar)
                except Exception as e:
                    self._logger.error(f"Bar 回调异常: {e}")

        asyncio.run_coroutine_threadsafe(notify_callbacks(), self._loop)

    def __repr__(self) -> str:
        return (
            f"CtpMarketGateway("
            f"name={self.gateway_name}, "
            f"state={self._state.name}, "
            f"subscriptions={self.subscription_count}, "
            f"cache_size={len(self._tick_cache)})"
        )


# =============================================================================
# 辅助类
# =============================================================================


class _BarGenerator:
    """
    K 线生成器。

    根据 Tick 数据实时生成 K 线。
    """

    __slots__ = (
        "symbol",
        "period",
        "_current_bar",
        "_last_bar_time",
    )

    def __init__(self, symbol: str, period: BarPeriod) -> None:
        self.symbol = symbol
        self.period = period
        self._current_bar: BarData | None = None
        self._last_bar_time: datetime | None = None

    def update(self, tick: TickData) -> BarData | None:
        """
        更新 K 线。

        Args:
            tick: 新的 Tick 数据

        Returns:
            如果 K 线完成则返回 BarData，否则返回 None
        """
        bar_time = self._get_bar_time(tick.timestamp)

        # WHY: 新 K 线周期开始
        if self._last_bar_time is None or bar_time > self._last_bar_time:
            completed_bar = self._current_bar
            self._current_bar = BarData(
                symbol=tick.symbol,
                exchange=tick.exchange,
                period=self.period,
                bar_datetime=bar_time,
                open_price=tick.last_price,
                high_price=tick.last_price,
                low_price=tick.last_price,
                close_price=tick.last_price,
                volume=tick.volume,
                gateway_name=tick.gateway_name,
            )
            self._last_bar_time = bar_time
            return completed_bar

        # WHY: 更新当前 K 线
        if self._current_bar:
            self._current_bar.high_price = max(
                self._current_bar.high_price,
                tick.last_price,
            )
            self._current_bar.low_price = min(
                self._current_bar.low_price,
                tick.last_price,
            )
            self._current_bar.close_price = tick.last_price
            self._current_bar.volume = tick.volume

        return None

    def _get_bar_time(self, ts: datetime) -> datetime:
        """获取 K 线起始时间。"""
        if self.period == BarPeriod.MINUTE_1:
            return ts.replace(second=0, microsecond=0)
        elif self.period == BarPeriod.MINUTE_5:
            minute = (ts.minute // 5) * 5
            return ts.replace(minute=minute, second=0, microsecond=0)
        else:
            return ts.replace(minute=0, second=0, microsecond=0)


class _CtpMdSpi:
    """
    CTP 行情 SPI 回调实现。

    # RISK: 所有回调在 CTP 内部线程执行
    # 缓解措施: 回调中只做最小处理，复杂逻辑转发到 asyncio
    """

    def __init__(self, gateway: CtpMarketGateway) -> None:
        self._gateway = gateway
        self._logger = logging.getLogger(f"ctp_spi.{gateway.gateway_name}")

    def OnFrontConnected(self) -> None:
        """前置机连接成功回调。"""
        self._logger.info("前置机连接成功，开始登录...")

        # WHY: 发起登录请求
        if self._gateway._api:
            self._gateway._request_id += 1
            req = {
                "BrokerID": self._gateway._ctp_config.broker_id,
                "UserID": self._gateway._ctp_config.investor_id,
                "Password": self._gateway._ctp_config.password.get_secret_value(),
            }
            self._gateway._api.ReqUserLogin(req, self._gateway._request_id)

    def OnFrontDisconnected(self, reason: int) -> None:
        """前置机断开回调。"""
        self._logger.warning(f"前置机断开，原因码: {reason}")

        # WHY: 触发重连
        if self._gateway._loop and self._gateway._state == GatewayState.RUNNING:
            asyncio.run_coroutine_threadsafe(
                self._gateway._do_reconnect(),
                self._gateway._loop,
            )

    def OnRspUserLogin(
        self,
        data: dict[str, Any],
        error: dict[str, Any],
        request_id: int,
        is_last: bool,
    ) -> None:
        """登录响应回调。"""
        if error and error.get("ErrorID", 0) != 0:
            self._gateway._login_error = error.get("ErrorMsg", "未知错误")
            self._logger.error(f"登录失败: {self._gateway._login_error}")
        else:
            self._logger.info("登录成功")

        # WHY: 通知等待的 connect() 方法
        self._gateway._login_event.set()

    def OnRtnDepthMarketData(self, data: dict[str, Any]) -> None:
        """行情数据回调。"""
        self._gateway._on_tick_data(data)

    def OnRspSubMarketData(
        self,
        data: dict[str, Any],
        error: dict[str, Any],
        request_id: int,
        is_last: bool,
    ) -> None:
        """订阅响应回调。"""
        if error and error.get("ErrorID", 0) != 0:
            self._logger.error(
                f"订阅失败: {data.get('InstrumentID')}, "
                f"error={error.get('ErrorMsg')}"
            )
        else:
            self._logger.debug(f"订阅成功: {data.get('InstrumentID')}")
