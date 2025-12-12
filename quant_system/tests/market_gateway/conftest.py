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
