from __future__ import annotations

from typing import TypeVar

from .records import CommandReceipt

_ERROR = TypeVar("_ERROR", bound=Exception)
_RECEIPT_ATTRIBUTE = "_birkin_command_receipt"


def attach_command_receipt(error: _ERROR, receipt: CommandReceipt) -> _ERROR:
    setattr(error, _RECEIPT_ATTRIBUTE, receipt)
    return error


def command_failure_receipt(error: Exception) -> CommandReceipt | None:
    receipt = getattr(error, _RECEIPT_ATTRIBUTE, None)
    return receipt if isinstance(receipt, CommandReceipt) else None
