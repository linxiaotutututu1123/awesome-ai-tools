"""
market_gateway/exceptions.py
行情网关异常定义模块。

设计原则：
- 异常分层：基类 → 连接类 → 数据类 → 订阅类
- 每个异常携带上下文信息便于调试
- 支持异常链追踪（__cause__）

Author: AI Quant Team
Version: 1.0.0
"""

from typing import Any, Final

__all__: list[str] = [
    "GatewayException",
    "ConnectionException",
    "AuthenticationException",
    "ConnectionTimeoutException",
    "DataException",
    "InvalidTickDataException",
    "DataValidationException",
    "SubscriptionException",
    "SubscriptionLimitExceededException",
    "SymbolNotFoundException",
]

# WHY: 错误码常量集中管理，便于国际化和文档化
ERROR_CODE_UNKNOWN: Final[int] = -1
ERROR_CODE_CONNECTION_FAILED: Final[int] = 1001
ERROR_CODE_AUTH_FAILED: Final[int] = 1002
ERROR_CODE_TIMEOUT: Final[int] = 1003
ERROR_CODE_INVALID_DATA: Final[int] = 2001
ERROR_CODE_VALIDATION_FAILED: Final[int] = 2002
ERROR_CODE_SUBSCRIPTION_LIMIT: Final[int] = 3001
ERROR_CODE_SYMBOL_NOT_FOUND: Final[int] = 3002


class GatewayException(Exception):
    """
    网关基础异常，所有网关相关异常的父类。

    Attributes:
        message: 人类可读的错误描述
        error_code: 机器可读的错误码，用于监控和告警分类
        context: 附加上下文信息（如 symbol, timestamp 等）

    Example:
        >>> raise GatewayException("连接失败", error_code=1001, context={"host": "127.0.0.1"})
    """

    def __init__(
        self,
        message: str,
        error_code: int = ERROR_CODE_UNKNOWN,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.error_code: int = error_code
        # WHY: 使用不可变副本防止外部修改影响异常状态
        self.context: dict[str, Any] = dict(context) if context else {}

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"error_code={self.error_code}, "
            f"context={self.context})"
        )
