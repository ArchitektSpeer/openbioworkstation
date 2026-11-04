"""Non-executing preflight for the saved workflow graph.

This module performs full-saved-graph compile validation only. It is **not** a
Snakemake dry-run, not an environment or conda check, not a data-format or
content check, and not proof that the workflow will execute. It reads saved
state only; UI drafts are not included. It never writes a session, run folder,
Snakefile, log or benchmark, and it never launches a process.

The registry may lazily build/cache its catalog index under the configured cache
directory (the same behaviour as ``get_workflow``); that cache is not a run artifact.
"""

from __future__ import annotations

from glue.errors import (
    CompileError,
    PathNotAllowedError,
    SessionConflictError,
    ToolNotFoundError,
    ToolNotWrappedError,
    WorkstationError,
)
from glue.session_store import load_session
from glue.snakemake_bridge import compile_session
from glue.workflow_service import validate_session

MAX_MESSAGE_CHARS = 500
MAX_PLAN_ITEMS = 200


def _message(exc: BaseException) -> str:
    text = str(exc) or exc.__class__.__name__
    return text[:MAX_MESSAGE_CHARS]


def _classify(exc: WorkstationError, *, phase: str) -> tuple[str, str | None]:
    """Map an expected error to a stable diagnostic code and carried node UID."""
    if isinstance(exc, CompileError):
        return "compile_error", exc.uid
    if isinstance(exc, (ToolNotFoundError, ToolNotWrappedError)):
        return "tool_not_found", None
    if isinstance(exc, PathNotAllowedError):
        return "path_not_allowed", None
    if phase == "validate":
        return "invalid_session", None
    return "workstation_error", None


def _diagnostic(code: str, exc: BaseException, node_id: str | None = None) -> dict:
    return {"code": code, "message": _message(exc), "node_id": node_id}


def _bounded_plan(
    targets: list[str], outputs: dict[str, dict[str, list[str]]], limit: int
) -> tuple[list[str], dict[str, dict[str, list[str]]], bool]:
    """Cap total targets and output paths, reporting whether either cap applied."""
    truncated = len(targets) > limit
    bounded_targets = list(targets[:limit])
    remaining = limit
    bounded_outputs: dict[str, dict[str, list[str]]] = {}
    for uid, ports in outputs.items():
        if remaining <= 0:
            truncated = True
            break
        kept: dict[str, list[str]] = {}
        for port, paths in ports.items():
            if remaining <= 0:
                truncated = True
                break
            kept[port] = list(paths[:remaining])
            remaining -= len(kept[port])
            if len(paths) > len(kept[port]):
                truncated = True
        if kept:
            bounded_outputs[uid] = kept
    return bounded_targets, bounded_outputs, truncated


def preflight_workflow(
    config,
    registry,
    *,
    expected_revision: int | None = None,
    allow_unreviewed: bool | None = None,
) -> dict:
    """Validate the saved graph by reusing the shared validator and compiler.

    This is full-saved-graph compile validation only. It is not a Snakemake
    dry-run, not an environment or conda check, not a data-format or content
    check, and not proof that the workflow will execute. It only reads saved
    state; unsaved UI drafts are excluded. No run, Snakefile, log, benchmark or
    session write is performed.

    ``expected_revision`` rejects a stale saved graph with
    :class:`~glue.errors.SessionConflictError`; ``allow_unreviewed=None`` follows
    ``config.allow_unreviewed``. Expected workstation/compile failures become
    bounded diagnostics, while revision conflicts and unexpected bugs propagate.
    """
    session, revision = load_session(config.workspace)
    if expected_revision is not None and revision != expected_revision:
        raise SessionConflictError("会话已修改，请重新读取后再校验")
    effective_unreviewed = (
        config.allow_unreviewed if allow_unreviewed is None else bool(allow_unreviewed)
    )
    result = {
        "valid": False,
        "revision": revision,
        "allow_unreviewed": effective_unreviewed,
        "diagnostics": [],
        "warnings": [],
        "tool_node_count": 0,
        "targets": [],
        "outputs": {},
        "truncated": False,
    }
    try:
        normalized = validate_session(session, registry, config)
    except WorkstationError as exc:
        code, node_id = _classify(exc, phase="validate")
        result["diagnostics"] = [_diagnostic(code, exc, node_id)]
        return result
    try:
        compiled = compile_session(
            normalized,
            registry,
            config.workspace,
            allow_unreviewed=effective_unreviewed,
            allowed_input_roots=config.allowed_input_roots,
        )
    except WorkstationError as exc:
        code, node_id = _classify(exc, phase="compile")
        result["diagnostics"] = [_diagnostic(code, exc, node_id)]
        return result
    targets, outputs, truncated = _bounded_plan(compiled.targets, compiled.outputs, MAX_PLAN_ITEMS)
    result.update(
        valid=True,
        warnings=[str(w)[:MAX_MESSAGE_CHARS] for w in compiled.warnings[:MAX_PLAN_ITEMS]],
        tool_node_count=len(compiled.rule_of_node),
        targets=targets,
        outputs=outputs,
        truncated=(
            truncated
            or len(compiled.warnings) > MAX_PLAN_ITEMS
            or any(len(str(w)) > MAX_MESSAGE_CHARS for w in compiled.warnings[:MAX_PLAN_ITEMS])
        ),
    )
    return result
