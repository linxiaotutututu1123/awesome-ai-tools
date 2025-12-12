"""
market_gateway/metrics.py
Prometheus 监控指标模块。

指标类型：
- Counter: 累计计数（如 tick 数量）
- Gauge: 瞬时值（如 连接状态）
- Histogram: 分布统计（如 延迟）

# RISK: 指标过多导致内存占用
# 缓解措施: 限制 label cardinality，避免高基数标签

Author: AI Quant Team
Version: 1.0.0
"""

from typing import Final
from prometheus_client import Counter, Gauge, Histogram, Info

__all__: list[str] = [
    "TICK_RECEIVED_TOTAL",
    "TICK_FILTERED_TOTAL",
    "TICK_LATENCY_SECONDS",
    "GATEWAY_STATE",
    "GATEWAY_SUBSCRIPTIONS",
    "GATEWAY_RECONNECT_TOTAL",
    "GATEWAY_QUEUE_SIZE",
    "GATEWAY_INFO",
    "record_tick_received",
    "record_tick_filtered",
    "record_tick_latency",
    "set_gateway_state",
]

# =============================================================================
# 指标定义
# =============================================================================

# WHY: 使用 gateway 标签区分不同网关实例
TICK_RECEIVED_TOTAL: Final[Counter] = Counter(
    "gateway_tick_received_total",
    "Total number of ticks received",
    ["gateway", "exchange"],
)

TICK_FILTERED_TOTAL: Final[Counter] = Counter(
    "gateway_tick_filtered_total",
    "Total number of ticks filtered (invalid/stale)",
    ["gateway", "reason"],
)

# WHY: 使用 Histogram 统计延迟分布
# buckets 设计：0.1ms, 0.5ms, 1ms, 5ms, 10ms, 50ms, 100ms
TICK_LATENCY_SECONDS: Final[Histogram] = Histogram(
    "gateway_tick_latency_seconds",
    "Tick processing latency in seconds",
    ["gateway"],
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
)

# WHY: 使用 Gauge 表示瞬时状态
GATEWAY_STATE: Final[Gauge] = Gauge(
    "gateway_state",
    "Gateway state (0=disconnected, 1=connecting, 2=connected, 3=running)",
    ["gateway"],
)

GATEWAY_SUBSCRIPTIONS: Final[Gauge] = Gauge(
    "gateway_subscriptions",
    "Number of active subscriptions",
    ["gateway"],
)

GATEWAY_RECONNECT_TOTAL: Final[Counter] = Counter(
    "gateway_reconnect_total",
    "Total number of reconnection attempts",
    ["gateway", "result"],  # result: success/failure
)

GATEWAY_QUEUE_SIZE: Final[Gauge] = Gauge(
    "gateway_queue_size",
    "Current size of tick queue",
    ["gateway"],
)

GATEWAY_INFO: Final[Info] = Info(
    "gateway",
    "Gateway information",
)


# =============================================================================
# 状态映射
# =============================================================================

# WHY: 将 GatewayState 枚举映射为数字便于 Prometheus 处理
STATE_VALUES: Final[dict[str, int]] = {
    "DISCONNECTED": 0,
    "CONNECTING": 1,
    "CONNECTED": 2,
    "SUBSCRIBING": 3,
    "RUNNING": 4,
    "RECONNECTING": 5,
    "ERROR": 6,
    "STOPPED": 7,
}


# =============================================================================
# 便捷函数
# =============================================================================


def record_tick_received(gateway: str, exchange: str) -> None:
    """记录收到的 Tick。"""
    TICK_RECEIVED_TOTAL.labels(gateway=gateway, exchange=exchange).inc()


def record_tick_filtered(gateway: str, reason: str) -> None:
    """
    记录被过滤的 Tick。

    Args:
        gateway: 网关名称
        reason: 过滤原因 (invalid_price/stale_timestamp/out_of_order)
    """
    TICK_FILTERED_TOTAL.labels(gateway=gateway, reason=reason).inc()


def record_tick_latency(gateway: str, latency_seconds: float) -> None:
    """记录 Tick 延迟。"""
    TICK_LATENCY_SECONDS.labels(gateway=gateway).observe(latency_seconds)


def set_gateway_state(gateway: str, state: str) -> None:
    """
    设置网关状态。

    Args:
        gateway: 网关名称
        state: 状态名称（如 "RUNNING"）
    """
    value = STATE_VALUES.get(state, -1)
    GATEWAY_STATE.labels(gateway=gateway).set(value)


def set_gateway_subscriptions(gateway: str, count: int) -> None:
    """设置订阅数量。"""
    GATEWAY_SUBSCRIPTIONS.labels(gateway=gateway).set(count)


def record_reconnect(gateway: str, success: bool) -> None:
    """记录重连尝试。"""
    result = "success" if success else "failure"
    GATEWAY_RECONNECT_TOTAL.labels(gateway=gateway, result=result).inc()


def set_queue_size(gateway: str, size: int) -> None:
    """设置队列大小。"""
    GATEWAY_QUEUE_SIZE.labels(gateway=gateway).set(size)


def set_gateway_info(
    gateway: str,
    version: str,
    gateway_type: str,
) -> None:
    """设置网关元信息。"""
    GATEWAY_INFO.info({
        "gateway": gateway,
        "version": version,
        "type": gateway_type,
    })
