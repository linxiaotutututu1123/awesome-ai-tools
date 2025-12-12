"""
market_gateway/_sensitive.py
敏感字段配置与脱敏工具模块。

设计原则：
- 集中管理敏感字段黑名单
- 提供统一脱敏函数
- 支持运行时扩展黑名单

# RISK: 黑名单不完整可能导致敏感信息泄露
# 缓解措施: 定期审计日志，发现新敏感字段及时添加

Author: AI Quant Team
Version: 2.0.0
"""

from typing import Any, Final
import sys

__all__: list[str] = [
    "SENSITIVE_KEYS",
    "REDACTED_PLACEHOLDER",
    "MAX_CONTEXT_SIZE_BYTES",
    "sanitize_context",
    "add_sensitive_key",
]

# WHY: 使用 frozenset 保证不可变，防止运行时意外修改
_DEFAULT_SENSITIVE_KEYS: Final[frozenset[str]] = frozenset({
    "password",
    "passwd",
    "pwd",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "secret_key",
    "api_key",
    "apikey",
    "credential",
    "credentials",
    "auth",
    "authorization",
    "private_key",
    "broker_id",  # WHY: CTP 经纪商ID也属于敏感信息
    "investor_id",  # WHY: CTP 投资者ID
    "auth_code",
    "app_id",
})

# WHY: 运行时可扩展的敏感字段集合（非默认部分）
_runtime_sensitive_keys: set[str] = set()

REDACTED_PLACEHOLDER: Final[str] = "***REDACTED***"
MAX_CONTEXT_SIZE_BYTES: Final[int] = 1024  # 1KB


def get_sensitive_keys() -> frozenset[str]:
    """
    获取当前所有敏感字段（默认 + 运行时添加）。

    Returns:
        所有敏感字段的不可变集合

    Example:
        >>> keys = get_sensitive_keys()
        >>> "password" in keys
        True
    """
    # WHY: 合并默认和运行时字段，返回不可变集合
    return _DEFAULT_SENSITIVE_KEYS | frozenset(_runtime_sensitive_keys)


# WHY: 导出为模块级变量，便于外部直接访问
SENSITIVE_KEYS: frozenset[str] = get_sensitive_keys()


def add_sensitive_key(key: str) -> None:
    """
    运行时添加敏感字段。

    Args:
        key: 要添加的敏感字段名（会自动转小写）

    Example:
        >>> add_sensitive_key("my_secret_field")
        >>> "my_secret_field" in get_sensitive_keys()
        True
    """
    global SENSITIVE_KEYS
    _runtime_sensitive_keys.add(key.lower())
    # WHY: 更新导出的不可变集合
    SENSITIVE_KEYS = get_sensitive_keys()


def sanitize_context(
    context: dict[str, Any] | None,
    max_size: int = MAX_CONTEXT_SIZE_BYTES,
) -> dict[str, Any]:
    """
    脱敏并限制 context 大小。

    处理逻辑：
    1. 敏感字段值替换为 REDACTED_PLACEHOLDER
    2. 超过 max_size 则截断，只保留 key 列表

    Args:
        context: 原始上下文字典
        max_size: 最大允许字节数，默认 1KB

    Returns:
        脱敏后的上下文字典（新对象，不修改原始）

    Example:
        >>> ctx = {"host": "127.0.0.1", "password": "secret123"}
        >>> sanitize_context(ctx)
        {'host': '127.0.0.1', 'password': '***REDACTED***'}

    # RISK: 嵌套字典中的敏感字段可能漏检
    # 缓解措施: 递归检查（当前版本仅检查顶层）
    """
    if not context:
        return {}

    # WHY: 创建新字典，不修改原始输入
    current_sensitive = get_sensitive_keys()
    sanitized: dict[str, Any] = {}

    for key, value in context.items():
        # WHY: 键名转小写匹配，但保留原始键名
        if key.lower() in current_sensitive:
            sanitized[key] = REDACTED_PLACEHOLDER
        else:
            sanitized[key] = value

    # WHY: 检查大小，防止 OOM
    size_estimate = sys.getsizeof(str(sanitized))
    if size_estimate > max_size:
        # WHY: 超限时只保留元信息，丢弃具体值
        return {
            "_truncated": True,
            "_original_keys": list(context.keys()),
            "_size_bytes": size_estimate,
        }

    return sanitized
