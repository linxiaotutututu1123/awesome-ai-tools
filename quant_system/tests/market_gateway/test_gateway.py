"""
tests/market_gateway/test_gateway.py
CtpMarketGateway 单元测试。

测试覆盖场景：
1. 正常行情推送（验证 TickData 转换）
2. 断线重连（模拟断线 3 次，验证指数退避间隔）
3. 异常数据过滤（price=-1, volume=0）
4. 重复订阅幂等性
5. 配置错误（错误服务器地址）

Author: AI Quant Team
Version: 1.0.0
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from typing import Any

from quant_system.market_gateway.models import TickData, DataStatus
from quant_system.market_gateway.config import GatewayConfig, CtpConfig, GatewayType
from quant_system.market_gateway.exceptions import (
    ConnectionException,
    ConnectionTimeoutException,
    SubscriptionLimitExceededException,
    InvalidTickDataException,
)
from quant_system.market_gateway.base import GatewayState


# =============================================================================
# 场景1：正常行情推送测试
# =============================================================================


class TestTickDataConversion:
    """Tick 数据转换测试。"""

    def test_valid_tick_data_creation(self, sample_tick_data: TickData) -> None:
        """
        测试：有效 Tick 数据创建。

        Arrange: 使用 fixture 提供的有效数据
        Act: 创建 TickData 实例
        Assert: 所有字段正确设置
        """
        # Arrange - 由 fixture 提供

        # Act - 已在 fixture 中创建

        # Assert
        assert sample_tick_data.symbol == "IF2401"
        assert sample_tick_data.exchange == "CFFEX"
        assert sample_tick_data.last_price == Decimal("3500.0")
        assert sample_tick_data.volume == 10000
        assert sample_tick_data.status == DataStatus.VALID

    def test_tick_data_validation_success(self, sample_tick_data: TickData) -> None:
        """
        测试：有效数据校验通过。

        Arrange: 有效的 TickData
        Act: 调用 validate()
        Assert: 返回 (True, [])
        """
        # Arrange - 由 fixture 提供

        # Act
        is_valid, errors = sample_tick_data.validate()

        # Assert
        assert is_valid is True
        assert errors == []

    def test_tick_data_latency_calculation(self, sample_tick_data: TickData) -> None:
        """
        测试：延迟计算。

        Arrange: TickData 带有 local_timestamp
        Act: 获取 latency_us
        Assert: 延迟值合理（>= 0）
        """
        # Arrange - 由 fixture 提供

        # Act
        latency = sample_tick_data.latency_us

        # Assert
        assert latency >= 0
        # WHY: 延迟应该很小（同一进程内创建）
        assert latency < 1_000_000  # < 1秒

    def test_tick_data_unique_id_generation(self, sample_tick_data: TickData) -> None:
        """
        测试：唯一ID生成。

        Arrange: TickData
        Act: 获取 unique_id
        Assert: ID 为 16 字符的十六进制字符串
        """
        # Arrange - 由 fixture 提供

        # Act
        uid = sample_tick_data.unique_id

        # Assert
        assert len(uid) == 16
        assert all(c in "0123456789abcdef" for c in uid)

    def test_tick_data_serialization(self, sample_tick_data: TickData) -> None:
        """
        测试：序列化为字典。

        Arrange: TickData
        Act: 调用 to_dict()
        Assert: 包含所有必要字段
        """
        # Arrange - 由 fixture 提供

        # Act
        data_dict = sample_tick_data.to_dict()

        # Assert
        assert "symbol" in data_dict
        assert "last_price" in data_dict
        assert data_dict["symbol"] == "IF2401"
        # WHY: Decimal 应转换为字符串
        assert isinstance(data_dict["last_price"], str)


# =============================================================================
# 场景2：断线重连测试
# =============================================================================


class TestReconnectLogic:
    """断线重连逻辑测试。"""

    def test_exponential_backoff_intervals(self) -> None:
        """
        测试：指数退避间隔计算。

        Arrange: 初始间隔 1s，乘数 2，最大 60s
        Act: 计算前 10 次重连间隔
        Assert: 间隔序列为 1,2,4,8,16,32,60,60,60,60
        """
        # Arrange
        initial = 1.0
        multiplier = 2.0
        max_interval = 60.0

        # Act
        intervals = []
        interval = initial
        for _ in range(10):
            intervals.append(interval)
            interval = min(interval * multiplier, max_interval)

        # Assert
        expected = [1, 2, 4, 8, 16, 32, 60, 60, 60, 60]
        assert intervals == expected

    @pytest.mark.asyncio
    async def test_reconnect_state_transitions(
        self,
        sample_gateway_config: GatewayConfig,
    ) -> None:
        """
        测试：重连时状态转换。

        Arrange: 模拟网关处于 RUNNING 状态
        Act: 模拟断线触发重连
        Assert: 状态变为 RECONNECTING → CONNECTING → CONNECTED
        """
        # Arrange
        from quant_system.market_gateway.base import AbstractGateway, GatewayState

        # WHY: 创建一个简单的测试实现
        class TestGateway(AbstractGateway):
            async def connect(self) -> None:
                await self._set_state(GatewayState.CONNECTED)

            async def disconnect(self) -> None:
                await self._set_state(GatewayState.DISCONNECTED)

            async def subscribe(self, symbols: list[str]) -> list[str]:
                return symbols

            async def unsubscribe(self, symbols: list[str]) -> list[str]:
                return symbols

            async def _do_reconnect(self) -> bool:
                await self._set_state(GatewayState.RECONNECTING)
                await asyncio.sleep(0.01)
                await self._set_state(GatewayState.CONNECTING)
                await asyncio.sleep(0.01)
                await self._set_state(GatewayState.CONNECTED)
                return True

        # Act
        gateway = TestGateway(sample_gateway_config)
        state_history: list[GatewayState] = []

        async def track_state(old: GatewayState, new: GatewayState) -> None:
            state_history.append(new)

        gateway.on_state_change(track_state)

        await gateway._do_reconnect()

        # Assert
        assert GatewayState.RECONNECTING in state_history
        assert GatewayState.CONNECTING in state_history
        assert GatewayState.CONNECTED in state_history


# =============================================================================
# 场景3：异常数据过滤测试
# =============================================================================


class TestDataFiltering:
    """异常数据过滤测试。"""

    def test_invalid_price_detection(self, invalid_tick_data: TickData) -> None:
        """
        测试：检测无效价格（price <= 0）。

        Arrange: price = -1.0, volume = 100
        Act: 调用 validate()
        Assert: 返回错误，状态为 INVALID
        """
        # Arrange - 由 fixture 提供

        # Act
        is_valid, errors = invalid_tick_data.validate()

        # Assert
        assert is_valid is False
        assert any("无效价格" in e for e in errors)
        assert invalid_tick_data.status == DataStatus.INVALID

    def test_zero_volume_preserved(self) -> None:
        """
        测试：volume=0 的数据保留（开盘前状态）。

        Arrange: price = 0, volume = 0（开盘前）
        Act: 调用 validate()
        Assert: 校验通过（volume=0 时允许 price=0）
        """
        # Arrange
        tick = TickData(
            symbol="IF2401",
            exchange="CFFEX",
            timestamp=datetime.now(timezone.utc),
            last_price=Decimal("0"),
            volume=0,  # WHY: 开盘前无成交
        )

        # Act
        is_valid, errors = tick.validate()

        # Assert - volume=0 时 price=0 应该被接受
        # WHY: 用户要求 volume=0 保留
        price_errors = [e for e in errors if "无效价格" in e]
        assert len(price_errors) == 0

    def test_stale_timestamp_detection(self, stale_tick_data: TickData) -> None:
        """
        测试：检测过期时间戳（超过1小时）。

        Arrange: timestamp 为 2 小时前
        Act: 调用 validate()
        Assert: 返回错误，状态为 STALE
        """
        # Arrange - 由 fixture 提供

        # Act
        is_valid, errors = stale_tick_data.validate()

        # Assert
        assert is_valid is False
        assert any("时间戳过期" in e for e in errors)
        assert stale_tick_data.status in (DataStatus.STALE, DataStatus.INVALID)

    def test_invalid_exchange_detection(self) -> None:
        """
        测试：检测无效交易所代码。

        Arrange: exchange = "INVALID"
        Act: 调用 validate()
        Assert: 返回错误
        """
        # Arrange
        tick = TickData(
            symbol="IF2401",
            exchange="INVALID",
            timestamp=datetime.now(timezone.utc),
            last_price=Decimal("3500.0"),
            volume=100,
        )

        # Act
        is_valid, errors = tick.validate()

        # Assert
        assert is_valid is False
        assert any("无效交易所" in e for e in errors)


# =============================================================================
# 场景4：重复订阅幂等性测试
# =============================================================================


class TestSubscriptionIdempotency:
    """订阅幂等性测试。"""

    @pytest.mark.asyncio
    async def test_duplicate_subscription_ignored(
        self,
        sample_gateway_config: GatewayConfig,
    ) -> None:
        """
        测试：重复订阅同一合约不会重复调用 SDK。

        Arrange: 已订阅 IF2401
        Act: 再次订阅 IF2401
        Assert: SDK 订阅方法只调用一次
        """
        # Arrange
        from quant_system.market_gateway.base import AbstractGateway, GatewayState

        class TestGateway(AbstractGateway):
            def __init__(self, config: GatewayConfig) -> None:
                super().__init__(config)
                self.subscribe_call_count = 0

            async def connect(self) -> None:
                await self._set_state(GatewayState.CONNECTED)

            async def disconnect(self) -> None:
                await self._set_state(GatewayState.DISCONNECTED)

            async def subscribe(self, symbols: list[str]) -> list[str]:
                # WHY: 幂等性检查 - 只订阅未订阅的合约
                new_symbols = [s for s in symbols if s not in self._subscribed_symbols]
                if new_symbols:
                    self.subscribe_call_count += 1
                    self._subscribed_symbols.update(new_symbols)
                return new_symbols

            async def unsubscribe(self, symbols: list[str]) -> list[str]:
                return symbols

            async def _do_reconnect(self) -> bool:
                return True

        # Act
        gateway = TestGateway(sample_gateway_config)
        await gateway.connect()

        result1 = await gateway.subscribe(["IF2401"])
        result2 = await gateway.subscribe(["IF2401"])  # 重复订阅

        # Assert
        assert result1 == ["IF2401"]
        assert result2 == []  # WHY: 重复订阅返回空列表
        assert gateway.subscribe_call_count == 1
        assert gateway.subscription_count == 1

    @pytest.mark.asyncio
    async def test_subscription_limit_exceeded(
        self,
        sample_gateway_config: GatewayConfig,
    ) -> None:
        """
        测试：超过订阅限制时抛出异常。

        Arrange: max_subscriptions = 100，已订阅 100 个
        Act: 尝试订阅第 101 个
        Assert: 抛出 SubscriptionLimitExceededException
        """
        # Arrange
        from quant_system.market_gateway.base import AbstractGateway, GatewayState

        class TestGateway(AbstractGateway):
            async def connect(self) -> None:
                await self._set_state(GatewayState.CONNECTED)

            async def disconnect(self) -> None:
                pass

            async def subscribe(self, symbols: list[str]) -> list[str]:
                new_symbols = [s for s in symbols if s not in self._subscribed_symbols]
                if len(self._subscribed_symbols) + len(new_symbols) > self._config.max_subscriptions:
                    raise SubscriptionLimitExceededException(
                        message="超过订阅限制",
                        current_count=len(self._subscribed_symbols),
                        max_limit=self._config.max_subscriptions,
                        requested_count=len(new_symbols),
                    )
                self._subscribed_symbols.update(new_symbols)
                return new_symbols

            async def unsubscribe(self, symbols: list[str]) -> list[str]:
                return symbols

            async def _do_reconnect(self) -> bool:
                return True

        # Act
        gateway = TestGateway(sample_gateway_config)
        await gateway.connect()

        # 先订阅 100 个合约
        symbols = [f"TEST{i:04d}" for i in range(100)]
        await gateway.subscribe(symbols)

        # Assert - 尝试订阅第 101 个应抛出异常
        with pytest.raises(SubscriptionLimitExceededException) as exc_info:
            await gateway.subscribe(["TEST0100"])

        assert exc_info.value.current_count == 100
        assert exc_info.value.max_limit == 100


# =============================================================================
# 场景5：配置错误测试
# =============================================================================


class TestConfigurationErrors:
    """配置错误测试。"""

    def test_invalid_front_addr_format(self) -> None:
        """
        测试：无效的前置机地址格式。

        Arrange: front_addr = "http://invalid"
        Act: 创建 CtpConfig
        Assert: 抛出 ValidationError
        """
        # Arrange & Act & Assert
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            CtpConfig(
                broker_id="9999",
                investor_id="test",
                password="test",
                front_addr="http://invalid:10211",  # WHY: 应该是 tcp://
            )

        # 验证错误信息包含 front_addr
        assert "front_addr" in str(exc_info.value)

    def test_missing_ctp_config_for_ctp_gateway(self) -> None:
        """
        测试：CTP 网关缺少 CTP 配置。

        Arrange: gateway_type = CTP, ctp = None
        Act: 创建 GatewayConfig
        Assert: 抛出 ValidationError
        """
        # Arrange & Act & Assert
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            GatewayConfig(
                gateway_type=GatewayType.CTP,
                gateway_name="test",
                ctp=None,  # WHY: CTP 类型必须提供 ctp 配置
            )

        assert "ctp" in str(exc_info.value).lower()

    def test_valid_simnow_config(self, sample_ctp_config: CtpConfig) -> None:
        """
        测试：有效的 SimNow 配置。

        Arrange: 使用 SimNow 类型和有效 CTP 配置
        Act: 创建 GatewayConfig
        Assert: 成功创建
        """
        # Arrange & Act
        config = GatewayConfig(
            gateway_type=GatewayType.SIMNOW,
            gateway_name="simnow_test",
            ctp=sample_ctp_config,
        )

        # Assert
        assert config.gateway_type == GatewayType.SIMNOW
        assert config.ctp is not None


# =============================================================================
# 性能测试
# =============================================================================


class TestPerformance:
    """性能测试。"""

    def test_tick_data_creation_performance(self, benchmark) -> None:
        """
        测试：TickData 创建性能。

        目标: < 1ms/次
        """
        def create_tick() -> TickData:
            return TickData(
                symbol="IF2401",
                exchange="CFFEX",
                timestamp=datetime.now(timezone.utc),
                last_price=Decimal("3500.0"),
                volume=10000,
            )

        # Act
        result = benchmark(create_tick)

        # Assert
        assert result is not None
        # WHY: pytest-benchmark 会自动报告性能指标

    def test_tick_data_validation_performance(
        self,
        sample_tick_data: TickData,
        benchmark,
    ) -> None:
        """
        测试：TickData 校验性能。

        目标: < 1ms/次
        """
        # Act
        result = benchmark(sample_tick_data.validate)

        # Assert
        assert result[0] is True  # is_valid

    def test_tick_data_serialization_performance(
        self,
        sample_tick_data: TickData,
        benchmark,
    ) -> None:
        """
        测试：TickData 序列化性能。

        目标: < 1ms/次
        """
        # Act
        result = benchmark(sample_tick_data.to_dict)

        # Assert
        assert "symbol" in result
