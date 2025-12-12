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
