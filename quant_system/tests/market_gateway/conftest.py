"""
tests/market_gateway/conftest.py
pytest 配置与共享 fixtures。

Author: AI Quant Team
Version: 1.0.0
"""

import pytest
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock
from pydantic import SecretStr

import sys
sys.path.insert(0, str(__file__).rsplit("tests", 1)[0])

from quant_system.market_gateway.models import TickData, DepthData, BarData, BarPeriod, PriceLevel
from quant_system.market_gateway.config import (
    GatewayConfig,
    CtpConfig,
    ReconnectConfig,
    GatewayType,
)


@pytest.fixture
def event_loop():
    """创建事件循环。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_ctp_config() -> CtpConfig:
    """示例 CTP 配置。"""
    return CtpConfig(
        broker_id="9999",
        investor_id="test_user",
        password=SecretStr("test_password"),
        front_addr="tcp://180.168.146.187:10211",
        auth_code="test_auth",
        app_id="test_app",
    )


@pytest.fixture
def sample_gateway_config(sample_ctp_config: CtpConfig) -> GatewayConfig:
    """示例网关配置。"""
    return GatewayConfig(
        gateway_type=GatewayType.CTP,
        gateway_name="test_ctp_gateway",
        connect_timeout=5.0,
        max_subscriptions=100,
        ctp=sample_ctp_config,
    )


@pytest.fixture
def sample_tick_data() -> TickData:
    """示例 Tick 数据。"""
    return TickData(
        symbol="IF2401",
        exchange="CFFEX",
        timestamp=datetime.now(timezone.utc),
        last_price=Decimal("3500.0"),
        volume=10000,
        turnover=Decimal("35000000.0"),
        open_interest=50000,
        bid_price_1=Decimal("3499.8"),
        bid_volume_1=100,
        ask_price_1=Decimal("3500.2"),
        ask_volume_1=150,
        gateway_name="test_gateway",
    )


@pytest.fixture
def sample_depth_data() -> DepthData:
    """示例深度数据。"""
    return DepthData(
        symbol="IF2401",
        exchange="CFFEX",
        timestamp=datetime.now(timezone.utc),
        bids=[
            PriceLevel(price=Decimal("3499.8"), volume=100),
            PriceLevel(price=Decimal("3499.6"), volume=200),
            PriceLevel(price=Decimal("3499.4"), volume=150),
        ],
        asks=[
            PriceLevel(price=Decimal("3500.2"), volume=150),
            PriceLevel(price=Decimal("3500.4"), volume=180),
            PriceLevel(price=Decimal("3500.6"), volume=120),
        ],
        gateway_name="test_gateway",
    )


@pytest.fixture
def sample_bar_data() -> BarData:
    """示例 K 线数据。"""
    return BarData(
        symbol="IF2401",
        exchange="CFFEX",
        period=BarPeriod.MINUTE_1,
        bar_datetime=datetime.now(timezone.utc),
        open_price=Decimal("3498.0"),
        high_price=Decimal("3502.0"),
        low_price=Decimal("3497.0"),
        close_price=Decimal("3500.0"),
        volume=5000,
        gateway_name="test_gateway",
    )


@pytest.fixture
def invalid_tick_data() -> TickData:
    """无效 Tick 数据（价格为负）。"""
    return TickData(
        symbol="IF2401",
        exchange="CFFEX",
        timestamp=datetime.now(timezone.utc),
        last_price=Decimal("-1.0"),  # 无效价格
        volume=100,
    )


@pytest.fixture
def stale_tick_data() -> TickData:
    """过期 Tick 数据（时间戳超过1小时）。"""
    from datetime import timedelta
    old_time = datetime.now(timezone.utc) - timedelta(hours=2)
    return TickData(
        symbol="IF2401",
        exchange="CFFEX",
        timestamp=old_time,
        last_price=Decimal("3500.0"),
        volume=100,
    )


@pytest.fixture
def mock_ctp_api() -> MagicMock:
    """模拟 CTP API 对象。"""
    mock = MagicMock()
    mock.Init = MagicMock()
    mock.RegisterFront = MagicMock()
    mock.ReqUserLogin = MagicMock(return_value=0)
    mock.SubscribeMarketData = MagicMock(return_value=0)
    mock.UnSubscribeMarketData = MagicMock(return_value=0)
    mock.Release = MagicMock()
    return mock
