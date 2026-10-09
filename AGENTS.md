# Project mission
Build centralized Android fleet monitoring and management through authenticated ADB, supporting rooted and non-rooted devices. Never require a custom monitoring agent, management APK, or SSH server. M0 is a foundation, not production deployment readiness.

# Architecture rules
- All ADB access goes through `AdbClient`; APIs never run subprocesses.
- Device behavior is capability-driven. Never assume root or scatter rooted/non-rooted branches.
- Collectors depend on domain models and ADB interfaces, never FastAPI or Prometheus.
- Normalized snapshots feed an exporter which owns Prometheus names and labels.
- Domain models stay transport-independent; configuration parsers produce domain models.
- Device-specific collectors belong behind explicit interfaces. Unsupported metrics fail gracefully.
- Operational state is separate from capabilities; reconnects must invalidate stale observations.
- Avoid global mutable state; prefer dependency injection and per-application ownership.
- Keep ADB RSA authentication enabled. Never log keys or secrets. No unauthenticated control endpoints.

# Agent coordination
Read this file and existing interfaces before work. Split parallel tasks by bounded modules; each delegated task must name expected files and acceptance criteria. One coordinator owns shared domain models and architecture-sensitive interfaces. Avoid parallel edits to the same files unless explicitly coordinated. Never silently rename public interfaces used by another workstream. Report assumptions and interface changes to the coordinator.

# Coding conventions
Python 3.13+, required type hints, async-first process/network I/O, pathlib.Path, StrEnum, dataclasses/Pydantic as appropriate, Protocol/ABC interfaces, minimal inheritance and dependencies. Use ruff, mypy, pytest. Shell argv must be safely quoted for the remote shell; local subprocess invocation must use argv, never shell=True. Streaming needs cancellation, bounded buffers, and per-device concurrency limits when implemented.

# Testing expectations
Normal CI needs no real devices. Use FakeAdbClient and recorded fixtures. Test parsers, malformed and unsupported outputs, rooted and non-rooted cases, offline state, timeouts, and cleanup. Do not replace missing observations with fabricated zeros.

# Definition of done
Implementation and meaningful tests finished; tests, lint, format, typing pass; relevant documentation updated; architecture rules respected. Report checks unavailable in the environment honestly. No pushes, GitHub repository creation, or commits without explicit authorization.
