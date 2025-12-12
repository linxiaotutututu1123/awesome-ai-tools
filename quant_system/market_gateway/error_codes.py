"""
market_gateway/error_codes.py
错误码枚举定义模块。

设计原则：
- 按模块分段：1000-1999 行情网关
- 枚举类型安全，IDE 自动补全
- 每个错误码必须有描述

错误码分段规范：
- 1000-1099: 连接相关
- 1100-1199: 认证相关
- 1200-1299: 数据相关
- 1300-1399: 订阅相关
- 1900-1999: 预留扩展

Author: AI Quant Team
Version: 2.0.0
"""

from enum import IntEnum, unique
from typing import Final

__all__: list[str] = ["ErrorCode", "ERROR_CODE_DESCRIPTIONS"]


@unique  # WHY: 确保没有重复的错误码值
class ErrorCode(IntEnum):
    """
    行情网关错误码枚举。

    使用 IntEnum 而非 Enum 的原因：
    - 可直接用于 Prometheus 指标标签
    - 可序列化为 JSON
    - 保持与旧系统兼容
    """

    # === 通用错误 (1000-1009) ===
    UNKNOWN = 1000

    # === 连接错误 (1010-1099) ===
    CONNECTION_FAILED = 1010
    CONNECTION_TIMEOUT = 1011
    CONNECTION_LOST = 1012
    RECONNECT_EXHAUSTED = 1013  # WHY: 重连次数耗尽需单独标识

    # === 认证错误 (1100-1199) ===
    AUTH_FAILED = 1100
    AUTH_INVALID_CREDENTIAL = 1101
    AUTH_EXPIRED = 1102
    AUTH_PERMISSION_DENIED = 1103

    # === 数据错误 (1200-1299) ===
    DATA_INVALID = 1200
    DATA_VALIDATION_FAILED = 1201
    DATA_PARSE_ERROR = 1202
    DATA_TIMESTAMP_INVALID = 1203  # WHY: 时间戳超1小时需单独处理

    # === 订阅错误 (1300-1399) ===
    SUBSCRIPTION_FAILED = 1300
    SUBSCRIPTION_LIMIT_EXCEEDED = 1301
    SYMBOL_NOT_FOUND = 1302
    SYMBOL_INVALID_FORMAT = 1303


# WHY: 错误描述独立维护，支持国际化扩展
ERROR_CODE_DESCRIPTIONS: Final[dict[ErrorCode, str]] = {
    ErrorCode.UNKNOWN: "未知错误",
    ErrorCode.CONNECTION_FAILED: "连接失败",
    ErrorCode.CONNECTION_TIMEOUT: "连接超时",
    ErrorCode.CONNECTION_LOST: "连接断开",
    ErrorCode.RECONNECT_EXHAUSTED: "重连次数耗尽",
    ErrorCode.AUTH_FAILED: "认证失败",
    ErrorCode.AUTH_INVALID_CREDENTIAL: "无效凭证",
    ErrorCode.AUTH_EXPIRED: "凭证过期",
    ErrorCode.AUTH_PERMISSION_DENIED: "权限不足",
    ErrorCode.DATA_INVALID: "无效数据",
    ErrorCode.DATA_VALIDATION_FAILED: "数据校验失败",
    ErrorCode.DATA_PARSE_ERROR: "数据解析错误",
    ErrorCode.DATA_TIMESTAMP_INVALID: "时间戳无效",
    ErrorCode.SUBSCRIPTION_FAILED: "订阅失败",
    ErrorCode.SUBSCRIPTION_LIMIT_EXCEEDED: "订阅数量超限",
    ErrorCode.SYMBOL_NOT_FOUND: "合约不存在",
    ErrorCode.SYMBOL_INVALID_FORMAT: "合约格式错误",
}
