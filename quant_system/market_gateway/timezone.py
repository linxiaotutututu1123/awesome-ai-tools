"""
market_gateway/timezone.py
中国期货市场时区处理模块。

功能：
- Asia/Shanghai 时区标准化
- 交易时段判断
- 时间戳验证

# RISK: 夏令时（中国无夏令时，但需要处理国际市场）
# 缓解措施: 使用 ZoneInfo 自动处理

Author: AI Quant Team
Version: 1.0.0
"""

from datetime import datetime, time, timezone, timedelta
from typing import Final
from zoneinfo import ZoneInfo

__all__: list[str] = [
    "CHINA_TZ",
    "UTC_TZ",
    "to_china_time",
    "to_utc_time",
    "is_trading_time",
    "validate_timestamp",
    "get_trading_day",
]

# WHY: 中国期货市场统一使用 Asia/Shanghai 时区
CHINA_TZ: Final[ZoneInfo] = ZoneInfo("Asia/Shanghai")
UTC_TZ: Final[timezone] = timezone.utc

# WHY: 中国期货交易时段（不含夜盘的日盘时段）
DAY_SESSION_START: Final[time] = time(9, 0)
DAY_SESSION_END: Final[time] = time(15, 0)
NIGHT_SESSION_START: Final[time] = time(21, 0)
NIGHT_SESSION_END: Final[time] = time(2, 30)  # 次日凌晨

# WHY: 时间戳有效性阈值
MAX_FUTURE_SECONDS: Final[int] = 60  # 最大允许超前 60 秒
MAX_PAST_HOURS: Final[int] = 1  # 最大允许滞后 1 小时


def to_china_time(dt: datetime) -> datetime:
    """
    转换为中国时间。

    Args:
        dt: 任意时区的 datetime

    Returns:
        Asia/Shanghai 时区的 datetime

    Example:
        >>> utc_time = datetime(2024, 1, 15, 2, 0, tzinfo=UTC_TZ)
        >>> china_time = to_china_time(utc_time)
        >>> china_time.hour
        10  # UTC+8
    """
    # WHY: 处理 naive datetime（假定为 UTC）
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    return dt.astimezone(CHINA_TZ)


def to_utc_time(dt: datetime) -> datetime:
    """
    转换为 UTC 时间。

    Args:
        dt: 任意时区的 datetime

    Returns:
        UTC 时区的 datetime
    """
    # WHY: 处理 naive datetime（假定为中国时间）
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CHINA_TZ)
    return dt.astimezone(UTC_TZ)


def is_trading_time(dt: datetime | None = None) -> bool:
    """
    判断是否在交易时段内。

    # WHY: 用于过滤非交易时段的异常数据

    Args:
        dt: 待检查时间，默认当前时间

    Returns:
        是否在交易时段
    """
    if dt is None:
        dt = datetime.now(CHINA_TZ)
    else:
        dt = to_china_time(dt)

    t = dt.time()

    # WHY: 日盘时段 09:00-15:00
    if DAY_SESSION_START <= t <= DAY_SESSION_END:
        return True

    # WHY: 夜盘时段 21:00-次日02:30
    if t >= NIGHT_SESSION_START:  # 21:00 之后
        return True
    if t <= NIGHT_SESSION_END:  # 02:30 之前
        return True

    return False


def validate_timestamp(
    ts: datetime,
    reference: datetime | None = None,
) -> tuple[bool, str]:
    """
    验证时间戳有效性。

    检查规则：
    1. 不能超前太多（防止时钟漂移）
    2. 不能滞后太久（防止过期数据）

    Args:
        ts: 待验证时间戳
        reference: 参考时间，默认当前时间

    Returns:
        (是否有效, 原因描述)

    Example:
        >>> old_ts = datetime.now(UTC_TZ) - timedelta(hours=2)
        >>> valid, reason = validate_timestamp(old_ts)
        >>> valid
        False
        >>> "stale" in reason
        True
    """
    if reference is None:
        reference = datetime.now(UTC_TZ)

    # WHY: 统一转换为 UTC 比较
    ts_utc = to_utc_time(ts)
    ref_utc = to_utc_time(reference)

    diff = (ts_utc - ref_utc).total_seconds()

    # WHY: 检查是否超前太多
    if diff > MAX_FUTURE_SECONDS:
        return False, f"future_timestamp: {diff:.1f}s ahead"

    # WHY: 检查是否滞后太久
    max_past_seconds = MAX_PAST_HOURS * 3600
    if diff < -max_past_seconds:
        return False, f"stale_timestamp: {-diff:.1f}s old"

    return True, "valid"


def get_trading_day(dt: datetime | None = None) -> str:
    """
    获取交易日（格式：YYYYMMDD）。

    # WHY: 夜盘属于下一交易日
    # 例：周一 21:00 的交易日是周二

    Args:
        dt: 时间点，默认当前时间

    Returns:
        交易日字符串

    Example:
        >>> # 周一晚上 21:30
        >>> dt = datetime(2024, 1, 15, 21, 30, tzinfo=CHINA_TZ)
        >>> get_trading_day(dt)
        '20240116'  # 周二
    """
    if dt is None:
        dt = datetime.now(CHINA_TZ)
    else:
        dt = to_china_time(dt)

    # WHY: 夜盘时段（21:00后）属于下一交易日
    if dt.time() >= NIGHT_SESSION_START:
        dt = dt + timedelta(days=1)

    # WHY: 凌晨时段（00:00-02:30）属于当日交易日，无需调整

    return dt.strftime("%Y%m%d")
