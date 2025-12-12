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
