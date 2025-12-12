"""
market_gateway - 行情网关模块。

提供中国期货市场行情接入能力，支持：
- CTP（上期技术）
- SimNow（模拟）
- IB（预留）

核心组件：
- AbstractGateway: 网关抽象基类
- CtpMarketGateway: CTP行情网关实现
- TickData/DepthData/BarData: 数据模型
- GatewayConfig: 配置模型

Author: AI Quant Team
Version: 1.0.0
"""

from .error_codes import ErrorCode, ERROR_CODE_DESCRIPTIONS
from .exceptions import (
    GatewayException,
    ConnectionException,
    AuthenticationException,
    ConnectionTimeoutException,
    ReconnectExhaustedException,
    DataException,
    InvalidTickDataException,
    DataValidationException,
    SubscriptionException,
    SubscriptionLimitExceededException,
    SymbolNotFoundException,
)
from .models import (
    TickData,
    DepthData,
    BarData,
    BarPeriod,
    PriceLevel,
    DataStatus,
)
from .config import (
    GatewayType,
    GatewayConfig,
    CtpConfig,
    ReconnectConfig,
    DataFilterConfig,
    RedisConfig,
    ClickHouseConfig,
)
from .base import (
    GatewayState,
    AbstractGateway,
    TickCallback,
    DepthCallback,
    BarCallback,
    StateCallback,
)
from .ctp_gateway import CtpMarketGateway

__all__: list[str] = [
    # 错误码
    "ErrorCode",
    "ERROR_CODE_DESCRIPTIONS",
    # 异常
    "GatewayException",
    "ConnectionException",
    "AuthenticationException",
    "ConnectionTimeoutException",
    "ReconnectExhaustedException",
    "DataException",
    "InvalidTickDataException",
    "DataValidationException",
    "SubscriptionException",
    "SubscriptionLimitExceededException",
    "SymbolNotFoundException",
    # 数据模型
    "TickData",
    "DepthData",
    "BarData",
    "BarPeriod",
    "PriceLevel",
    "DataStatus",
    # 配置
    "GatewayType",
    "GatewayConfig",
    "CtpConfig",
    "ReconnectConfig",
    "DataFilterConfig",
    "RedisConfig",
    "ClickHouseConfig",
    # 基类
    "GatewayState",
    "AbstractGateway",
    "TickCallback",
    "DepthCallback",
    "BarCallback",
    "StateCallback",
    # 实现类
    "CtpMarketGateway",
]

__version__ = "1.0.0"
