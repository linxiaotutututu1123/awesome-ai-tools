"""
market_gateway/logging_config.py
日志配置与敏感信息过滤模块。

功能：
- 敏感信息自动脱敏（密码、token等）
- 结构化日志输出
- 审计日志记录

# RISK: 新增敏感字段可能遗漏
# 缓解措施: 定期审计日志，发现泄露及时添加

Author: AI Quant Team
Version: 2.0.0
"""

import logging
import re
import json
from datetime import datetime, timezone
from typing import Final, Any
from pathlib import Path

__all__: list[str] = [
    "SensitiveFilter",
    "AuditLogger",
    "setup_gateway_logging",
    "get_gateway_logger",
]

# WHY: 敏感字段正则模式，统一管理便于维护
SENSITIVE_PATTERNS: Final[list[tuple[re.Pattern[str], str]]] = [
    # 密码相关
    (re.compile(r'[Pp]assword["\']?\s*[:=]\s*["\']?[^"\'\s,}]+'), 'password=***'),
    (re.compile(r'[Pp]wd["\']?\s*[:=]\s*["\']?[^"\'\s,}]+'), 'pwd=***'),
    # Token 相关
    (re.compile(r'[Tt]oken["\']?\s*[:=]\s*["\']?[^"\'\s,}]+'), 'token=***'),
    (re.compile(r'[Aa]uth[_]?[Cc]ode["\']?\s*[:=]\s*["\']?[^"\'\s,}]+'), 'auth_code=***'),
    # API 密钥
    (re.compile(r'[Aa]pi[_]?[Kk]ey["\']?\s*[:=]\s*["\']?[^"\'\s,}]+'), 'api_key=***'),
    (re.compile(r'[Ss]ecret["\']?\s*[:=]\s*["\']?[^"\'\s,}]+'), 'secret=***'),
    # CTP 特定
    (re.compile(r'[Bb]roker[_]?[Ii]d["\']?\s*[:=]\s*["\']?[^"\'\s,}]+'), 'broker_id=***'),
    (re.compile(r'[Ii]nvestor[_]?[Ii]d["\']?\s*[:=]\s*["\']?[^"\'\s,}]+'), 'investor_id=***'),
]


class SensitiveFilter(logging.Filter):
    """
    敏感信息过滤器。

    自动脱敏日志中的敏感字段，防止密码等信息泄露。

    Example:
        >>> logger = logging.getLogger("test")
        >>> logger.addFilter(SensitiveFilter())
        >>> logger.info("Login with password=secret123")
        # 输出: Login with password=***
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        过滤日志记录中的敏感信息。

        Args:
            record: 日志记录

        Returns:
            始终返回 True（不丢弃日志，只脱敏）
        """
        # WHY: 处理 msg 字段
        if isinstance(record.msg, str):
            record.msg = self._sanitize(record.msg)

        # WHY: 处理 args 中的字符串参数
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._sanitize(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self._sanitize(str(arg)) if isinstance(arg, str) else arg
                    for arg in record.args
                )

        return True

    def _sanitize(self, text: str) -> str:
        """脱敏文本中的敏感信息。"""
        for pattern, replacement in SENSITIVE_PATTERNS:
            text = pattern.sub(replacement, text)
        return text


class StructuredFormatter(logging.Formatter):
    """
    结构化日志格式化器（JSON 格式）。

    输出格式：
    {"timestamp": "...", "level": "INFO", "logger": "...", "message": "..."}
    """

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为 JSON。"""
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # WHY: 添加异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # WHY: 添加额外字段
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)

        return json.dumps(log_data, ensure_ascii=False)


class AuditLogger:
    """
    审计日志记录器。

    记录关键操作用于合规审计：
    - 连接/断开事件
    - 订阅变更
    - 认证事件
    - 异常事件

    审计日志特点：
    - 独立文件存储
    - 追加写入（不可修改历史）
    - 包含完整上下文

    Example:
        >>> audit = AuditLogger("gateway_audit.log")
        >>> audit.log("CONNECT", gateway="ctp_main", status="success")
    """

    def __init__(self, log_path: str | Path) -> None:
        """
        初始化审计日志记录器。

        Args:
            log_path: 审计日志文件路径
        """
        self._log_path = Path(log_path)
        # WHY: 确保父目录存在
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        event: str,
        *,
        gateway: str = "",
        operator: str = "system",
        **kwargs: Any,
    ) -> None:
        """
        记录审计事件。

        Args:
            event: 事件类型（如 CONNECT, SUBSCRIBE, DISCONNECT）
            gateway: 网关名称
            operator: 操作者（system/admin/user）
            **kwargs: 额外上下文
        """
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "gateway": gateway,
            "operator": operator,
            **kwargs,
        }

        # WHY: 追加写入，确保原子性
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def __repr__(self) -> str:
        return f"AuditLogger(path={self._log_path})"


# WHY: 全局审计日志实例（延迟初始化）
_audit_logger: AuditLogger | None = None


def get_audit_logger(log_path: str | Path = "logs/audit.log") -> AuditLogger:
    """获取全局审计日志实例。"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger(log_path)
    return _audit_logger


def setup_gateway_logging(
    level: int = logging.INFO,
    log_file: str | Path | None = None,
    structured: bool = False,
) -> None:
    """
    配置网关日志系统。

    Args:
        level: 日志级别
        log_file: 日志文件路径（可选）
        structured: 是否使用结构化（JSON）格式

    Example:
        >>> setup_gateway_logging(level=logging.DEBUG, log_file="gateway.log")
    """
    # WHY: 获取 gateway 根 logger
    root_logger = logging.getLogger("gateway")
    root_logger.setLevel(level)

    # WHY: 清除现有 handler 避免重复
    root_logger.handlers.clear()

    # WHY: 添加敏感信息过滤器
    sensitive_filter = SensitiveFilter()

    # WHY: 配置格式化器
    if structured:
        formatter = StructuredFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # WHY: 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(sensitive_filter)
    root_logger.addHandler(console_handler)

    # WHY: 文件输出（可选）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(sensitive_filter)
        root_logger.addHandler(file_handler)


def get_gateway_logger(name: str) -> logging.Logger:
    """
    获取网关子 logger。

    Args:
        name: logger 名称（会添加 gateway. 前缀）

    Returns:
        配置好的 logger 实例
    """
    return logging.getLogger(f"gateway.{name}")
