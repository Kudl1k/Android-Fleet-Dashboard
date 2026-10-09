from dataclasses import dataclass
from enum import StrEnum


class ExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class CommandRequest:
    argv: tuple[str, ...]
    timeout: float = 10.0


@dataclass(frozen=True)
class CommandResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = 0
    duration: float = 0.0
    timeout: bool = False
