"""Local CLI adapters. No shell interpolation or permission bypasses.

CLI availability and listed models are not evidence of remaining quota. Successful
completion is only recorded after a real invocation exits without an error event.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

PROVIDERS = ("codex", "claude", "qodercn", "opencode")


@dataclass
class ProcessResult:
    returncode: int
    timed_out: bool
    stdout: str
    stderr: str
    stdout_path: str
    stderr_path: str
    duration: float
    pid: int | None = None


def run_process(argv: list[str], cwd: Path, timeout: float, log_dir: Path) -> ProcessResult:
    """Execute an argv in a fresh process group and retain stdout/stderr and PID.

    The caller supplies a unique call directory so recovery can locate process.json.
    Timeout kills the whole group, including grandchildren.
    """
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / "process.json").exists():
        raise FileExistsError(f"Call directory already used: {directory}")
    stdout_path, stderr_path = directory / "stdout.log", directory / "stderr.log"
    started = time.monotonic()
    timed_out = False
    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        (directory / "process.json").write_text(
            json.dumps(
                {
                    "pid": process.pid,
                    "pgid": process.pid,
                    "argv": argv,
                    "cwd": str(cwd),
                    "started_at": datetime.now(UTC).isoformat(),
                },
                indent=2,
            )
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=2)
            # Parent exit does not imply its descendants have exited.
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    result = ProcessResult(
        process.returncode,
        timed_out,
        stdout_path.read_text(errors="replace"),
        stderr_path.read_text(errors="replace"),
        str(stdout_path),
        str(stderr_path),
        time.monotonic() - started,
        process.pid,
    )
    (directory / "completion.json").write_text(
        json.dumps(
            {
                "returncode": result.returncode,
                "timed_out": timed_out,
                "duration": result.duration,
            }
        )
    )
    return result


@dataclass
class AdapterResult:
    status: str
    provider: str
    requested_model: str | None
    actual_model: str | None = None
    returncode: int | None = None
    text: str = ""
    stdout: str = ""
    stderr: str = ""
    stdout_path: str | None = None
    stderr_path: str | None = None
    duration: float = 0.0
    version: str | None = None
    cost_usd: float | None = None
    retry_after: float | None = None
    command: tuple[str, ...] = ()
    pid: int | None = None
    model_mismatch: bool = False


def _objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def _top_events(stdout: str) -> list[dict]:
    try:
        parsed = json.loads(stdout)
        if isinstance(parsed, dict):
            return [parsed]
        return (
            [event for event in parsed if isinstance(event, dict)]
            if isinstance(parsed, list)
            else []
        )
    except (ValueError, TypeError):
        events = []
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    events.append(event)
            except ValueError:
                continue
        return events


def _events(stdout: str) -> list[dict]:
    try:
        parsed = json.loads(stdout)
        return list(_objects(parsed))
    except (ValueError, TypeError):
        events = []
        for line in stdout.splitlines():
            try:
                events.extend(_objects(json.loads(line)))
            except (ValueError, TypeError):
                continue
        return events


def _retry_after(events: list[dict], error_text: str) -> float | None:
    values = []
    for event in events:
        for key, value in event.items():
            if key.lower().replace("_", "-") == "retry-after":
                values.append(str(value))
    # Require a header/key-style field, not a model's informal estimate.
    values += re.findall(r"(?im)^\s*retry-after\s*:\s*(.+?)\s*$", error_text)
    for value in values:
        try:
            seconds = float(value)
            if 0 <= seconds < float("inf"):
                return seconds
        except ValueError:
            try:
                reset = parsedate_to_datetime(value)
                if reset.tzinfo is not None:
                    return max(0.0, (reset - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
    # Claude emits an authoritative quota notice in its structured API error.
    # Accept only an explicit UTC date/time, never infer a local timezone.
    quota_event = any(
        event.get("api_error") == "usage_limit_reached" or event.get("api_error_status") == 429
        for event in events
    )
    if quota_event:
        notice = " ".join(
            str(e.get("result", "")) + " " + str(e.get("message", "")) for e in events
        )
        match = re.search(
            r"resets\s+([A-Za-z]{3}\s+\d{1,2}),?\s+(\d{1,2}(?::\d{2})?\s*[ap]m)\s*\(UTC\)",
            notice,
            re.IGNORECASE,
        )
        if match:
            now = datetime.now(UTC)
            clock = match[2].replace(" ", "").upper()
            fmt = "%Y %b %d %I:%M%p" if ":" in clock else "%Y %b %d %I%p"
            try:
                reset = datetime.strptime(f"{now.year} {match[1]} {clock}", fmt).replace(tzinfo=UTC)
                if reset < now:
                    reset = reset.replace(year=now.year + 1)
                return (reset - now).total_seconds()
            except ValueError:
                pass
    return None


def _parse(process: ProcessResult) -> tuple[str, str, str | None, float | None, float | None]:
    events = _events(process.stdout)
    errors = [
        event
        for event in events
        if event.get("is_error") is True
        or event.get("type") in ("error", "turn.failed", "step_error")
        or (event.get("error") and event.get("type") != "tool_use")
    ]
    # Successful model prose must never trigger fallback by mentioning "429".
    error_text = process.stderr + "\n" + "\n".join(json.dumps(e) for e in errors)
    if process.returncode:
        error_text += "\n" + process.stdout
    status = "success"
    if process.timed_out:
        status = "timeout"
    elif any(event.get("permission_denials") for event in events):
        status = "permission"
    elif errors or process.returncode:
        lower = error_text.lower()
        if re.search(
            r"\b(401|403)\b|unauthorized|invalid.api.key|authentication.failed|not.logged.in", lower
        ):
            status = "auth"
        elif re.search(
            r"permission.denied|permission.required|permission.*reject|operation.not.permitted",
            lower,
        ):
            status = "permission"
        elif re.search(
            r"\b429\b|rate.limit|quota|usage.limit|usage_limit|insufficient.credit", lower
        ):
            status = "quota"
        elif re.search(
            r"\b(500|502|503|504)\b|temporarily.unavailable|overloaded|connection.reset|econnreset|etimedout|network.error",
            lower,
        ):
            status = "transient"
        elif re.search(r"model.*(not.found|not.available)|unknown.model|unsupported.model", lower):
            status = "unavailable"
        else:
            status = "failed"
    texts = []
    model, cost = None, None
    for event in events:
        if isinstance(event.get("model"), str):
            model = event["model"]
        for field in ("total_cost_usd", "cost_usd"):
            if isinstance(event.get(field), (int, float)) and not isinstance(event[field], bool):
                cost = float(event[field])
    for event in _top_events(process.stdout):
        if event.get("type") == "result" and isinstance(event.get("result"), str):
            texts.append(event["result"])
        elif event.get("type") == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                texts.append(item["text"])
        elif event.get("type") == "text":
            part = event.get("part", event)
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
    if status == "success" and not texts:
        status = "failed"
    return (
        status,
        (texts[-1] if texts else process.stdout),
        model,
        cost,
        _retry_after(events, error_text),
    )


class CLIAdapter:
    def __init__(
        self,
        provider: str,
        model: str | None = None,
        *,
        executable: str | None = None,
        runner: Callable = run_process,
    ):
        if provider not in PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}")
        self.provider, self.model = provider, model
        self.executable = executable or provider
        self.runner = runner
        self._version: str | None = None

    def build_command(
        self, prompt: str, worktree: Path, model: str | None = None, write: bool = False
    ) -> list[str]:
        model = model or self.model
        argv = [self.executable]
        if self.provider == "codex":
            argv += [
                "exec",
                "--json",
                "--ephemeral",
                "--ignore-user-config",
                "-s",
                "workspace-write" if write else "read-only",
                "-C",
                str(worktree),
            ]
        elif self.provider in ("claude", "qodercn"):
            tools = "Read,Glob,Grep,Edit,Write" if write else "Read,Glob,Grep"
            argv += ["--output-format", "json", "--no-session-persistence", "--tools", tools]
            if self.provider == "claude":
                argv += [
                    "--allowedTools",
                    tools,
                    "--permission-mode",
                    "acceptEdits" if write else "dontAsk",
                    "--strict-mcp-config",
                ]
            else:
                argv += [
                    "--allowed-tools",
                    tools,
                    "--permission-mode",
                    "accept_edits" if write else "dont_ask",
                    "--strict-mcp-config",
                    "--max-model-request-retries",
                    "0",
                ]
        else:
            argv += ["--standalone", "run", "--format", "json"]
            # Plan is a built-in read-only agent; normal permissions still apply.
            if not write:
                argv += ["--agent", "plan"]
        if model:
            argv += ["--model", model]
        if self.provider in ("claude", "qodercn"):
            argv += ["-p", prompt]
        else:
            argv += ["--", prompt]
        return argv

    def diagnose(self) -> dict:
        path = shutil.which(self.executable)
        version = None
        if path:
            try:
                process = subprocess.run(
                    [path, "--version"], capture_output=True, text=True, timeout=10, check=False
                )
                if process.returncode == 0:
                    version = process.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                pass
        self._version = version
        return {
            "provider": self.provider,
            "executable": path,
            "version": version,
            "available": path is not None,
            "authentication": "not_checked",
            "quota": "not_checked",
            "permission_policy": (
                "CLI sandbox"
                if self.provider == "codex"
                else "restricted built-in tools; normal CLI approvals"
                if self.provider in ("claude", "qodercn")
                else "plan agent for read-only; normal CLI approvals (no OS sandbox)"
            ),
        }

    def run(
        self,
        prompt: str,
        worktree: Path,
        timeout: float,
        log_dir: Path,
        model: str | None = None,
        write: bool = False,
    ) -> AdapterResult:
        model = model or self.model
        command = self.build_command(prompt, worktree, model, write)
        if self._version is None:
            self.diagnose()
        result = AdapterResult(
            "unavailable", self.provider, model, version=self._version, command=tuple(command)
        )
        try:
            process = self.runner(command, Path(worktree), timeout, Path(log_dir))
        except FileNotFoundError as exc:
            result.stderr = str(exc)
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            (Path(log_dir) / "result.json").write_text(json.dumps(asdict(result), indent=2))
            return result
        except PermissionError as exc:
            result.status, result.stderr = "permission", str(exc)
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            (Path(log_dir) / "result.json").write_text(json.dumps(asdict(result), indent=2))
            return result
        status, output, actual_model, cost, retry = _parse(process)
        result.status, result.text = status, output
        result.actual_model, result.cost_usd, result.retry_after = actual_model, cost, retry
        result.model_mismatch = bool(model and actual_model and model != actual_model)
        for field in (
            "returncode",
            "stdout",
            "stderr",
            "stdout_path",
            "stderr_path",
            "duration",
            "pid",
        ):
            setattr(result, field, getattr(process, field))
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        (Path(log_dir) / "result.json").write_text(json.dumps(asdict(result), indent=2))
        return result


def get_adapter(provider: str, **kwargs) -> CLIAdapter:
    return CLIAdapter(provider, **kwargs)


def diagnose_provider(provider: str) -> dict:
    return CLIAdapter(provider).diagnose()


def build_command(
    provider: str, prompt: str, worktree: Path, model: str | None = None, write: bool = False
) -> list[str]:
    return CLIAdapter(provider, model).build_command(prompt, worktree, write=write)
