"""
market_gateway/models.py
行情数据模型定义。

设计原则：
- 使用 dataclass 实现，支持 __slots__ 优化内存
- 所有字段类型明确，支持 mypy --strict
- 提供校验方法与序列化能力
- 时间戳统一使用 UTC，精度到微秒

# RISK: 时区处理不当可能导致时间错误
# 缓解措施: 强制使用 UTC，转换在边界层处理

Author: AI Quant Team
Version: 1.0.0
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum, auto
from typing import Final, ClassVar
import hashlib

__all__: list[str] = [
    "TickData",
    "DepthData",
    "BarData",
    "BarPeriod",
    "PriceLevel",
    "DataStatus",
]


class BarPeriod(Enum):
    """K线周期枚举。"""
    MINUTE_1 = auto()   # 1分钟
    MINUTE_5 = auto()   # 5分钟
    MINUTE_15 = auto()  # 15分钟
    MINUTE_30 = auto()  # 30分钟
    HOUR_1 = auto()     # 1小时
    DAILY = auto()      # 日线


class DataStatus(Enum):
    """数据状态枚举。"""
    VALID = auto()      # 有效
    STALE = auto()      # 过期（时间戳超限）
    INVALID = auto()    # 无效（校验失败）
    FILTERED = auto()   # 被过滤（如 price<=0）


@dataclass(frozen=False, slots=True)
class PriceLevel:
    """
    价格档位（用于深度行情）。

    Attributes:
        price: 价格
        volume: 数量
        order_count: 订单数（可选，部分交易所不提供）
    """
    price: Decimal
    volume: int
    order_count: int = 0

    def __repr__(self) -> str:
        return f"PriceLevel(price={self.price}, vol={self.volume})"


# WHY: 时间戳有效性阈值，超过此值认为数据过期
_TIMESTAMP_STALE_THRESHOLD_SECONDS: Final[int] = 3600  # 1小时


@dataclass(frozen=False, slots=True)
class TickData:
    """
    Tick级行情数据。

    Attributes:
        symbol: 合约代码（如 "IF2401"）
        exchange: 交易所代码（如 "CFFEX"）
        timestamp: 行情时间戳（UTC）
        last_price: 最新价
        volume: 成交量（当日累计）
        turnover: 成交额（当日累计）
        open_interest: 持仓量
        bid_price_1: 买一价
        bid_volume_1: 买一量
        ask_price_1: 卖一价
        ask_volume_1: 卖一量
        pre_close: 昨收价
        pre_settlement: 昨结算价
        upper_limit: 涨停价
        lower_limit: 跌停价
        gateway_name: 来源网关名称
        local_timestamp: 本地接收时间戳（用于延迟计算）
        status: 数据状态

    Example:
        >>> tick = TickData(
        ...     symbol="IF2401",
        ...     exchange="CFFEX",
        ...     timestamp=datetime.now(timezone.utc),
        ...     last_price=Decimal("3500.0"),
        ...     volume=10000,
        ... )
    """

    # === 必填字段 ===
    symbol: str
    exchange: str
    timestamp: datetime
    last_price: Decimal

    # === 成交相关（默认0）===
    volume: int = 0
    turnover: Decimal = field(default_factory=lambda: Decimal("0"))
    open_interest: int = 0

    # === 盘口数据（默认0）===
    bid_price_1: Decimal = field(default_factory=lambda: Decimal("0"))
    bid_volume_1: int = 0
    ask_price_1: Decimal = field(default_factory=lambda: Decimal("0"))
    ask_volume_1: int = 0

    # === 参考价格 ===
    pre_close: Decimal = field(default_factory=lambda: Decimal("0"))
    pre_settlement: Decimal = field(default_factory=lambda: Decimal("0"))
    upper_limit: Decimal = field(default_factory=lambda: Decimal("0"))
    lower_limit: Decimal = field(default_factory=lambda: Decimal("0"))

    # === 元数据 ===
    gateway_name: str = ""
    local_timestamp: datetime | None = None
    status: DataStatus = DataStatus.VALID

    # WHY: 类变量用于校验配置，不占用实例内存
    _VALID_EXCHANGES: ClassVar[frozenset[str]] = frozenset({
        "CFFEX", "SHFE", "DCE", "CZCE", "INE", "GFEX",
    })

    def __post_init__(self) -> None:
        """初始化后自动设置本地时间戳。"""
        if self.local_timestamp is None:
            self.local_timestamp = datetime.now(timezone.utc)

    def validate(self) -> tuple[bool, list[str]]:
        """
        校验数据有效性。

        Returns:
            (is_valid, error_messages) 元组

        校验规则：
        1. symbol 非空
        2. exchange 在有效列表中
        3. last_price > 0（除非 volume=0 保留）
        4. timestamp 不超过阈值
        """
        errors: list[str] = []

        # WHY: 合约代码是核心标识，必须存在
        if not self.symbol:
            errors.append("symbol不能为空")

        if self.exchange not in self._VALID_EXCHANGES:
            errors.append(f"无效交易所: {self.exchange}")

        # WHY: 价格校验，volume=0时允许price=0（开盘前状态）
        if self.last_price <= 0 and self.volume > 0:
            errors.append(f"无效价格: {self.last_price}")

        # WHY: 时间戳校验，超过阈值认为过期
        now = datetime.now(timezone.utc)
        age = abs((now - self.timestamp).total_seconds())
        if age > _TIMESTAMP_STALE_THRESHOLD_SECONDS:
            errors.append(f"时间戳过期: {age:.0f}秒前")
            self.status = DataStatus.STALE

        if errors:
            self.status = DataStatus.INVALID

        return len(errors) == 0, errors

    @property
    def latency_us(self) -> int:
        """
        计算网关延迟（微秒）。

        Returns:
            从行情时间戳到本地接收的延迟，微秒
        """
        if self.local_timestamp is None:
            return 0
        delta = self.local_timestamp - self.timestamp
        # WHY: 转换为微秒便于精确监控
        return int(delta.total_seconds() * 1_000_000)

    @property
    def unique_id(self) -> str:
        """
        生成唯一标识（用于去重）。

        基于 symbol + timestamp 生成，同一毫秒内的数据视为重复。
        """
        # WHY: 使用 MD5 短哈希，足够用于去重
        key = f"{self.symbol}:{self.timestamp.isoformat()}"
        return hashlib.md5(key.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        """序列化为字典（用于存储/传输）。"""
        result = asdict(self)
        # WHY: Decimal 和 datetime 需要特殊处理
        result["last_price"] = str(self.last_price)
        result["timestamp"] = self.timestamp.isoformat()
        result["status"] = self.status.name
        return result

    def __repr__(self) -> str:
        return (
            f"TickData({self.symbol}@{self.exchange}, "
            f"price={self.last_price}, vol={self.volume}, "
            f"ts={self.timestamp.strftime('%H:%M:%S.%f')[:-3]})"
        )


@dataclass(frozen=False, slots=True)
class DepthData:
    """
    深度行情数据（Level2）。

    Attributes:
        symbol: 合约代码
        exchange: 交易所代码
        timestamp: 行情时间戳（UTC）
        bids: 买盘档位列表（价格从高到低）
        asks: 卖盘档位列表（价格从低到高）
        gateway_name: 来源网关名称
        local_timestamp: 本地接收时间戳
    """

    symbol: str
    exchange: str
    timestamp: datetime
    # WHY: 使用 list 而非 tuple，便于动态深度变化
    bids: list[PriceLevel] = field(default_factory=list)
    asks: list[PriceLevel] = field(default_factory=list)
    gateway_name: str = ""
    local_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        if self.local_timestamp is None:
            self.local_timestamp = datetime.now(timezone.utc)

    @property
    def bid_price_1(self) -> Decimal:
        """买一价。"""
        return self.bids[0].price if self.bids else Decimal("0")

    @property
    def ask_price_1(self) -> Decimal:
        """卖一价。"""
        return self.asks[0].price if self.asks else Decimal("0")

    @property
    def spread(self) -> Decimal:
        """买卖价差。"""
        if not self.bids or not self.asks:
            return Decimal("0")
        return self.asks[0].price - self.bids[0].price

    def __repr__(self) -> str:
        bid_str = f"bid={self.bid_price_1}" if self.bids else "bid=N/A"
        ask_str = f"ask={self.ask_price_1}" if self.asks else "ask=N/A"
        return f"DepthData({self.symbol}, {bid_str}, {ask_str}, depth={len(self.bids)})"


@dataclass(frozen=False, slots=True)
class BarData:
    """
    K线数据。

    Attributes:
        symbol: 合约代码
        exchange: 交易所代码
        period: K线周期
        datetime: K线开始时间（UTC）
        open: 开盘价
        high: 最高价
        low: 最低价
        close: 收盘价
        volume: 成交量
        turnover: 成交额
        open_interest: 持仓量
        gateway_name: 来源网关名称
    """

    symbol: str
    exchange: str
    period: BarPeriod
    bar_datetime: datetime  # WHY: 避免与 datetime 模块冲突
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int = 0
    turnover: Decimal = field(default_factory=lambda: Decimal("0"))
    open_interest: int = 0
    gateway_name: str = ""

    def validate(self) -> tuple[bool, list[str]]:
        """校验K线数据有效性。"""
        errors: list[str] = []

        # WHY: OHLC 关系校验
        if self.high_price < self.low_price:
            errors.append(f"high({self.high_price}) < low({self.low_price})")

        if self.open_price > self.high_price or self.open_price < self.low_price:
            errors.append(f"open({self.open_price})超出high-low范围")

        if self.close_price > self.high_price or self.close_price < self.low_price:
            errors.append(f"close({self.close_price})超出high-low范围")

        return len(errors) == 0, errors

    def __repr__(self) -> str:
        return (
            f"BarData({self.symbol}, {self.period.name}, "
            f"O={self.open_price}, H={self.high_price}, "
            f"L={self.low_price}, C={self.close_price})"
        )
