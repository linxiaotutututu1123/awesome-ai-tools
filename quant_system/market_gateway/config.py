"""
market_gateway/config.py
网关配置模型定义。

设计原则：
- 使用 Pydantic v2 进行配置校验
- 所有配置从环境变量或配置文件读取
- 敏感信息（密码）使用 SecretStr
- 提供默认值与校验规则

# RISK: 配置错误可能导致连接失败或数据丢失
# 缓解措施: 启动时强制校验，失败则拒绝启动

Author: AI Quant Team
Version: 1.0.0
"""

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Final
from enum import Enum

__all__: list[str] = [
    "GatewayType",
    "GatewayConfig",
    "CtpConfig",
    "ReconnectConfig",
    "DataFilterConfig",
    "RedisConfig",
    "ClickHouseConfig",
]


class GatewayType(str, Enum):
    """网关类型枚举。"""
    CTP = "ctp"
    SIMNOW = "simnow"
    IB = "ib"  # WHY: 预留 IB 扩展


# WHY: 默认值常量集中管理
DEFAULT_CONNECT_TIMEOUT: Final[float] = 10.0
DEFAULT_MAX_RECONNECT_INTERVAL: Final[float] = 60.0
DEFAULT_MAX_SUBSCRIPTIONS: Final[int] = 1000
DEFAULT_TICK_CACHE_SECONDS: Final[int] = 30
DEFAULT_STALE_THRESHOLD_SECONDS: Final[int] = 3600


class ReconnectConfig(BaseModel):
    """
    重连配置。

    Attributes:
        initial_interval: 初始重连间隔（秒）
        max_interval: 最大重连间隔（秒）
        multiplier: 退避乘数
        max_attempts: 最大重连次数（0=无限）
        alert_threshold: 触发告警的失败次数
    """

    initial_interval: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="初始重连间隔（秒）",
    )
    max_interval: float = Field(
        default=DEFAULT_MAX_RECONNECT_INTERVAL,
        ge=1.0,
        le=300.0,
        description="最大重连间隔（秒）",
    )
    multiplier: float = Field(
        default=2.0,
        ge=1.1,
        le=5.0,
        description="指数退避乘数",
    )
    # WHY: 0 表示无限重连，符合用户需求
    max_attempts: int = Field(
        default=0,
        ge=0,
        description="最大重连次数（0=无限）",
    )
    alert_threshold: int = Field(
        default=10,
        ge=1,
        description="触发告警的连续失败次数",
    )

    def __repr__(self) -> str:
        return (
            f"ReconnectConfig(interval={self.initial_interval}-{self.max_interval}s, "
            f"multiplier={self.multiplier}, max={self.max_attempts or '∞'})"
        )


class DataFilterConfig(BaseModel):
    """
    数据过滤配置。

    Attributes:
        filter_invalid_price: 是否过滤无效价格（<=0）
        filter_zero_volume: 是否过滤零成交量（保留，用于开盘前）
        stale_threshold_seconds: 时间戳过期阈值（秒）
        log_dirty_data: 是否记录脏数据
    """

    filter_invalid_price: bool = Field(
        default=True,
        description="是否过滤无效价格",
    )
    # WHY: 用户要求 volume=0 保留
    filter_zero_volume: bool = Field(
        default=False,
        description="是否过滤零成交量",
    )
    stale_threshold_seconds: int = Field(
        default=DEFAULT_STALE_THRESHOLD_SECONDS,
        ge=60,
        le=86400,
        description="时间戳过期阈值（秒）",
    )
    log_dirty_data: bool = Field(
        default=True,
        description="是否记录脏数据到日志",
    )

    def __repr__(self) -> str:
        return f"DataFilterConfig(stale={self.stale_threshold_seconds}s, log_dirty={self.log_dirty_data})"


class RedisConfig(BaseModel):
    """
    Redis 配置（用于 Pub/Sub）。

    Attributes:
        host: Redis 主机地址
        port: Redis 端口
        db: 数据库编号
        password: 密码（可选）
        channel_prefix: 发布通道前缀
    """

    host: str = Field(default="localhost", description="Redis主机")
    port: int = Field(default=6379, ge=1, le=65535, description="Redis端口")
    db: int = Field(default=0, ge=0, le=15, description="数据库编号")
    password: SecretStr | None = Field(default=None, description="密码")
    channel_prefix: str = Field(
        default="market:",
        description="发布通道前缀",
    )
    # WHY: 连接池配置，防止连接耗尽
    max_connections: int = Field(default=10, ge=1, le=100)

    def __repr__(self) -> str:
        return f"RedisConfig({self.host}:{self.port}/{self.db})"


class ClickHouseConfig(BaseModel):
    """
    ClickHouse 配置（用于持久化）。

    Attributes:
        host: ClickHouse 主机地址
        port: ClickHouse 端口
        database: 数据库名
        user: 用户名
        password: 密码
        batch_size: 批量写入大小
        flush_interval: 刷新间隔（秒）
    """

    host: str = Field(default="localhost", description="ClickHouse主机")
    port: int = Field(default=9000, ge=1, le=65535, description="端口")
    database: str = Field(default="quant", description="数据库名")
    user: str = Field(default="default", description="用户名")
    password: SecretStr = Field(default=SecretStr(""), description="密码")
    # WHY: 批量写入提升性能
    batch_size: int = Field(default=1000, ge=100, le=100000)
    flush_interval: float = Field(default=1.0, ge=0.1, le=60.0)

    def __repr__(self) -> str:
        return f"ClickHouseConfig({self.host}:{self.port}/{self.database})"


class CtpConfig(BaseModel):
    """
    CTP 特定配置。

    Attributes:
        broker_id: 经纪商代码
        investor_id: 投资者代码
        password: 密码
        front_addr: 前置机地址（如 tcp://180.168.146.187:10211）
        auth_code: 认证码（穿透式监管）
        app_id: 应用ID（穿透式监管）
    """

    broker_id: str = Field(..., min_length=1, description="经纪商代码")
    investor_id: str = Field(..., min_length=1, description="投资者代码")
    password: SecretStr = Field(..., description="密码")
    # WHY: 前置机地址格式必须正确
    front_addr: str = Field(
        ...,
        pattern=r"^tcp://[\w\.\-]+:\d+$",
        description="前置机地址",
    )
    auth_code: str = Field(default="", description="认证码")
    app_id: str = Field(default="", description="应用ID")

    @field_validator("front_addr")
    @classmethod
    def validate_front_addr(cls, v: str) -> str:
        """校验前置机地址格式。"""
        if not v.startswith("tcp://"):
            raise ValueError("前置机地址必须以 tcp:// 开头")
        return v

    def __repr__(self) -> str:
        # WHY: 隐藏敏感信息
        return f"CtpConfig(broker={self.broker_id}, investor={self.investor_id[:2]}***)"


class GatewayConfig(BaseSettings):
    """
    网关主配置（支持环境变量加载）。

    环境变量前缀: GATEWAY_

    Attributes:
        gateway_type: 网关类型
        gateway_name: 网关实例名称
        connect_timeout: 连接超时（秒）
        max_subscriptions: 最大订阅数量
        tick_cache_seconds: Tick缓存时长（秒）
        ctp: CTP配置
        reconnect: 重连配置
        data_filter: 数据过滤配置
        redis: Redis配置
        clickhouse: ClickHouse配置
    """

    model_config = SettingsConfigDict(
        env_prefix="GATEWAY_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    gateway_type: GatewayType = Field(
        default=GatewayType.CTP,
        description="网关类型",
    )
    gateway_name: str = Field(
        default="ctp_market",
        min_length=1,
        max_length=50,
        description="网关实例名称",
    )
    connect_timeout: float = Field(
        default=DEFAULT_CONNECT_TIMEOUT,
        ge=1.0,
        le=60.0,
        description="连接超时（秒）",
    )
    max_subscriptions: int = Field(
        default=DEFAULT_MAX_SUBSCRIPTIONS,
        ge=1,
        le=5000,
        description="最大订阅数量",
    )
    # WHY: 缓存最近30秒数据，用于断线恢复
    tick_cache_seconds: int = Field(
        default=DEFAULT_TICK_CACHE_SECONDS,
        ge=10,
        le=300,
        description="Tick缓存时长（秒）",
    )

    # === 嵌套配置 ===
    ctp: CtpConfig | None = Field(default=None, description="CTP配置")
    reconnect: ReconnectConfig = Field(
        default_factory=ReconnectConfig,
        description="重连配置",
    )
    data_filter: DataFilterConfig = Field(
        default_factory=DataFilterConfig,
        description="数据过滤配置",
    )
    redis: RedisConfig = Field(
        default_factory=RedisConfig,
        description="Redis配置",
    )
    clickhouse: ClickHouseConfig = Field(
        default_factory=ClickHouseConfig,
        description="ClickHouse配置",
    )

    @model_validator(mode="after")
    def validate_gateway_config(self) -> "GatewayConfig":
        """校验网关配置完整性。"""
        # WHY: CTP/SimNow 类型必须有 CTP 配置
        if self.gateway_type in (GatewayType.CTP, GatewayType.SIMNOW):
            if self.ctp is None:
                raise ValueError(f"{self.gateway_type.value} 网关必须提供 ctp 配置")
        return self

    def __repr__(self) -> str:
        return (
            f"GatewayConfig(type={self.gateway_type.value}, "
            f"name={self.gateway_name}, "
            f"max_subs={self.max_subscriptions})"
        )
