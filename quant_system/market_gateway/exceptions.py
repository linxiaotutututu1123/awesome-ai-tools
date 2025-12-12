"""
market_gateway/exceptions.py
行情网关异常定义模块（重构版）。

重构改进：
- 使用 ErrorCode 枚举替代魔法数字
- context 自动脱敏 + 大小限制
- 只读 context 防止多线程污染
- 显式异常链支持（cause 参数）

# RISK: 异常创建性能开销
# 缓解措施: 脱敏操作为 O(n)，n 为 context 字段数，通常 <10

Author: AI Quant Team
Version: 2.0.0
"""

from types import MappingProxyType
from typing import Any, Final

from .error_codes import ErrorCode, ERROR_CODE_DESCRIPTIONS
from ._sensitive import sanitize_context, REDACTED_PLACEHOLDER

__all__: list[str] = [
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
]


class GatewayException(Exception):
    """
    网关基础异常，所有网关相关异常的父类。

    Attributes:
        message: 人类可读的错误描述
        error_code: ErrorCode 枚举，机器可读
        context: 只读上下文字典（已脱敏）
        cause: 原始异常（异常链）

    Example:
        正确用法：
        >>> raise GatewayException(
        ...     "连接失败",
        ...     error_code=ErrorCode.CONNECTION_FAILED,
        ...     context={"host": "127.0.0.1"},
        ... )

        带异常链：
        >>> try:
        ...     sdk.connect()
        ... except TimeoutError as e:
        ...     raise GatewayException("超时", cause=e) from e
    """

    # WHY: __slots__ 减少内存占用，提升属性访问速度
    __slots__ = ("message", "error_code", "_context", "cause")

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.UNKNOWN,
        context: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.message: Final[str] = message
        self.error_code: Final[ErrorCode] = error_code
        self.cause: Final[BaseException | None] = cause
        # WHY: 先脱敏再转为只读，双重防护
        sanitized = sanitize_context(context)
        self._context: Final[MappingProxyType[str, Any]] = MappingProxyType(
            sanitized
        )

    @property
    def context(self) -> MappingProxyType[str, Any]:
        """只读上下文访问器。"""
        return self._context

    @property
    def error_description(self) -> str:
        """获取错误码对应的描述文本。"""
        return ERROR_CODE_DESCRIPTIONS.get(self.error_code, "未知错误")

    def __repr__(self) -> str:
        """调试友好的字符串表示（敏感信息已脱敏）。"""
        # WHY: 包含所有关键信息便于日志分析
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"error_code={self.error_code.name}({self.error_code.value}), "
            f"context={dict(self._context)}, "
            f"cause={self.cause!r})"
        )

    def __str__(self) -> str:
        """用户友好的字符串表示。"""
        return f"[{self.error_code.name}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """
        序列化为字典，用于 JSON 日志或 API 响应。

        Returns:
            包含异常信息的字典（已脱敏）
        """
        return {
            "exception_type": self.__class__.__name__,
            "message": self.message,
            "error_code": self.error_code.value,
            "error_name": self.error_code.name,
            "error_description": self.error_description,
            "context": dict(self._context),
            "cause": repr(self.cause) if self.cause else None,
        }


# =============================================================================
# 连接类异常 (1010-1099)
# =============================================================================


class ConnectionException(GatewayException):
    """
    连接相关异常的基类。

    用于网络连接、前置机通信等场景。

    Attributes:
        host: 目标主机地址
        port: 目标端口

    Example:
        >>> raise ConnectionException(
        ...     "无法连接到CTP前置",
        ...     host="180.168.146.187",
        ...     port=10211,
        ... )
    """

    # WHY: 子类扩展 __slots__，不重复父类字段
    __slots__ = ("host", "port")

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.CONNECTION_FAILED,
        context: dict[str, Any] | None = None,
        cause: BaseException | None = None,
        *,
        host: str = "",
        port: int = 0,
    ) -> None:
        # WHY: 自动将 host/port 加入 context 便于调试
        enriched_context = dict(context) if context else {}
        if host:
            enriched_context["host"] = host
        if port:
            enriched_context["port"] = port

        super().__init__(message, error_code, enriched_context, cause)
        self.host: Final[str] = host
        self.port: Final[int] = port


class AuthenticationException(ConnectionException):
    """
    认证失败异常。

    场景：用户名/密码错误、授权码无效、权限不足等。

    # RISK: 错误信息可能暴露账户状态（如"账户已锁定"）
    # 缓解措施: 生产环境使用通用错误消息

    Example:
        >>> raise AuthenticationException(
        ...     "登录失败：密码错误",
        ...     error_code=ErrorCode.AUTH_INVALID_CREDENTIAL,
        ...     host="180.168.146.187",
        ... )
    """

    __slots__ = ()  # WHY: 无额外字段，显式声明空 slots

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.AUTH_FAILED,
        context: dict[str, Any] | None = None,
        cause: BaseException | None = None,
        *,
        host: str = "",
        port: int = 0,
    ) -> None:
        super().__init__(message, error_code, context, cause, host=host, port=port)


class ConnectionTimeoutException(ConnectionException):
    """
    连接超时异常。

    Attributes:
        timeout_seconds: 超时时间（秒）

    Example:
        >>> raise ConnectionTimeoutException(
        ...     "连接CTP前置超时",
        ...     timeout_seconds=10.0,
        ...     host="180.168.146.187",
        ... )
    """

    __slots__ = ("timeout_seconds",)

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.CONNECTION_TIMEOUT,
        context: dict[str, Any] | None = None,
        cause: BaseException | None = None,
        *,
        host: str = "",
        port: int = 0,
        timeout_seconds: float = 0.0,
    ) -> None:
        enriched_context = dict(context) if context else {}
        # WHY: 超时时间对于调试和调优至关重要
        enriched_context["timeout_seconds"] = timeout_seconds

        super().__init__(message, error_code, enriched_context, cause, host=host, port=port)
        self.timeout_seconds: Final[float] = timeout_seconds


class ReconnectExhaustedException(ConnectionException):
    """
    重连次数耗尽异常。

    当重连达到最大次数仍失败时抛出，用于触发告警。

    Attributes:
        attempt_count: 已尝试次数
        max_attempts: 最大允许次数（0 表示无限）
        last_interval: 最后一次重连间隔（秒）

    # RISK: 此异常表示网关完全不可用，必须触发高优先级告警
    # 缓解措施: 调用方捕获后必须发送钉钉/短信告警

    Example:
        >>> raise ReconnectExhaustedException(
        ...     "重连失败，已尝试10次",
        ...     attempt_count=10,
        ...     max_attempts=10,
        ...     last_interval=60.0,
        ... )
    """

    __slots__ = ("attempt_count", "max_attempts", "last_interval")

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.RECONNECT_EXHAUSTED,
        context: dict[str, Any] | None = None,
        cause: BaseException | None = None,
        *,
        host: str = "",
        port: int = 0,
        attempt_count: int = 0,
        max_attempts: int = 0,
        last_interval: float = 0.0,
    ) -> None:
        enriched_context = dict(context) if context else {}
        # WHY: 重连相关指标对于运维分析很重要
        enriched_context["attempt_count"] = attempt_count
        enriched_context["max_attempts"] = max_attempts
        enriched_context["last_interval"] = last_interval

        super().__init__(message, error_code, enriched_context, cause, host=host, port=port)
        self.attempt_count: Final[int] = attempt_count
        self.max_attempts: Final[int] = max_attempts
        self.last_interval: Final[float] = last_interval


# =============================================================================
# 数据类异常 (1200-1299)
# =============================================================================


class DataException(GatewayException):
    """
    数据相关异常的基类。

    用于数据解析、校验、转换等场景。

    Attributes:
        symbol: 相关合约代码
        raw_data: 原始数据摘要（用于调试，自动截断）
    """

    __slots__ = ("symbol", "raw_data_summary")

    # WHY: 原始数据可能很大，只保留摘要
    _MAX_RAW_DATA_SUMMARY_LEN: Final[int] = 200

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.DATA_INVALID,
        context: dict[str, Any] | None = None,
        cause: BaseException | None = None,
        *,
        symbol: str = "",
        raw_data: Any = None,
    ) -> None:
        enriched_context = dict(context) if context else {}
        if symbol:
            enriched_context["symbol"] = symbol

        # WHY: 截断原始数据防止日志爆炸
        raw_summary = ""
        if raw_data is not None:
            raw_str = str(raw_data)
            if len(raw_str) > self._MAX_RAW_DATA_SUMMARY_LEN:
                raw_summary = raw_str[:self._MAX_RAW_DATA_SUMMARY_LEN] + "..."
            else:
                raw_summary = raw_str
            enriched_context["raw_data_summary"] = raw_summary

        super().__init__(message, error_code, enriched_context, cause)
        self.symbol: Final[str] = symbol
        self.raw_data_summary: Final[str] = raw_summary


class InvalidTickDataException(DataException):
    """
    无效Tick数据异常。

    场景：价格为负、时间戳无效、字段缺失等。

    Attributes:
        invalid_field: 无效字段名
        invalid_value: 无效字段值
        expected: 期望值描述
    """

    __slots__ = ("invalid_field", "invalid_value", "expected")

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.DATA_INVALID,
        context: dict[str, Any] | None = None,
        cause: BaseException | None = None,
        *,
        symbol: str = "",
        raw_data: Any = None,
        invalid_field: str = "",
        invalid_value: Any = None,
        expected: str = "",
    ) -> None:
        enriched_context = dict(context) if context else {}
        # WHY: 记录具体哪个字段出问题，加速定位
        enriched_context["invalid_field"] = invalid_field
        enriched_context["invalid_value"] = repr(invalid_value)
        enriched_context["expected"] = expected

        super().__init__(message, error_code, enriched_context, cause, symbol=symbol, raw_data=raw_data)
        self.invalid_field: Final[str] = invalid_field
        self.invalid_value: Final[Any] = invalid_value
        self.expected: Final[str] = expected


class DataValidationException(DataException):
    """
    数据校验失败异常。

    用于批量校验场景，可包含多个校验错误。

    Attributes:
        validation_errors: 校验错误列表 [(field, error_msg), ...]
    """

    __slots__ = ("validation_errors",)

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.DATA_VALIDATION_FAILED,
        context: dict[str, Any] | None = None,
        cause: BaseException | None = None,
        *,
        symbol: str = "",
        raw_data: Any = None,
        validation_errors: list[tuple[str, str]] | None = None,
    ) -> None:
        enriched_context = dict(context) if context else {}
        # WHY: 批量校验时一次性返回所有错误，减少往返
        enriched_context["validation_errors"] = validation_errors or []
        enriched_context["error_count"] = len(validation_errors or [])

        super().__init__(message, error_code, enriched_context, cause, symbol=symbol, raw_data=raw_data)
        self.validation_errors: Final[list[tuple[str, str]]] = validation_errors or []


# =============================================================================
# 订阅类异常 (1300-1399)
# =============================================================================


class SubscriptionException(GatewayException):
    """
    订阅相关异常的基类。

    用于合约订阅、退订等场景。

    Attributes:
        symbols: 相关合约列表
    """

    __slots__ = ("symbols",)

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.SUBSCRIPTION_FAILED,
        context: dict[str, Any] | None = None,
        cause: BaseException | None = None,
        *,
        symbols: list[str] | None = None,
    ) -> None:
        enriched_context = dict(context) if context else {}
        # WHY: 记录涉及的合约便于排查
        enriched_context["symbols"] = symbols or []
        enriched_context["symbol_count"] = len(symbols or [])

        super().__init__(message, error_code, enriched_context, cause)
        self.symbols: Final[list[str]] = symbols or []


class SubscriptionLimitExceededException(SubscriptionException):
    """
    订阅数量超限异常。

    Attributes:
        current_count: 当前已订阅数量
        max_limit: 最大允许数量
        requested_count: 本次请求订阅数量
    """

    __slots__ = ("current_count", "max_limit", "requested_count")

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.SUBSCRIPTION_LIMIT_EXCEEDED,
        context: dict[str, Any] | None = None,
        cause: BaseException | None = None,
        *,
        symbols: list[str] | None = None,
        current_count: int = 0,
        max_limit: int = 1000,
        requested_count: int = 0,
    ) -> None:
        enriched_context = dict(context) if context else {}
        # WHY: 超限信息对于调整订阅策略很重要
        enriched_context["current_count"] = current_count
        enriched_context["max_limit"] = max_limit
        enriched_context["requested_count"] = requested_count

        super().__init__(message, error_code, enriched_context, cause, symbols=symbols)
        self.current_count: Final[int] = current_count
        self.max_limit: Final[int] = max_limit
        self.requested_count: Final[int] = requested_count


class SymbolNotFoundException(SubscriptionException):
    """
    合约不存在异常。

    Attributes:
        symbol: 未找到的合约代码
        suggestion: 建议的相似合约（如有）
    """

    __slots__ = ("symbol", "suggestion")

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.SYMBOL_NOT_FOUND,
        context: dict[str, Any] | None = None,
        cause: BaseException | None = None,
        *,
        symbol: str = "",
        suggestion: str = "",
    ) -> None:
        enriched_context = dict(context) if context else {}
        enriched_context["symbol"] = symbol
        # WHY: 提供相似合约建议改善用户体验
        if suggestion:
            enriched_context["suggestion"] = suggestion

        super().__init__(message, error_code, enriched_context, cause, symbols=[symbol] if symbol else None)
        self.symbol: Final[str] = symbol
        self.suggestion: Final[str] = suggestion
