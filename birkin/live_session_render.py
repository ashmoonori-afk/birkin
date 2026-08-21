"""Render deterministic live agent-session inventories for the CLI."""

from __future__ import annotations

from .live_session_models import LiveAgentProcess, LiveInventory
from .operation_policy import permission_denial_summary


def render_live_inventory(inventory: LiveInventory) -> str:
    """Render one inventory without inventing unobserved limitations."""
    live_count = sum(
        len(project.processes) for project in inventory.projects
    ) + len(inventory.unknown_project)
    lines = [f"ACTIVE AGENT PROJECTS: {len(inventory.projects)}"]

    if live_count == 0:
        if inventory.counters.refusals.total == 0:
            lines.append("No live agent sessions.")
        else:
            lines.append("No live agent sessions were confirmed.")
    else:
        for project in inventory.projects:
            lines.extend(("", f"PROJECT: {project.cwd}"))
            for process in project.processes:
                _append_process(lines, process)
        if inventory.unknown_project:
            lines.extend(("", "PROJECT: <unknown cwd>"))
            for process in inventory.unknown_project:
                _append_process(lines, process)
        lines.append("")

    counters = inventory.counters
    lines.append(
        "SCAN: "
        f"enumerated={counters.enumerated} "
        f"own-user={counters.own_user} "
        f"unidentified={counters.unidentified} "
        f"cmdline_ok={counters.cmdline_ok} "
        f"open_files_ok={counters.open_files_ok} "
        f"disappeared={counters.disappeared}"
    )
    refusals = counters.refusals
    lines.append(
        "REFUSALS: "
        f"name={refusals.name} "
        f"cmdline={refusals.cmdline} "
        f"cwd={refusals.cwd} "
        f"open_files={refusals.open_files}"
    )

    refused_fields = tuple(
        f"{field.value}={count}" for field, count in refusals.nonzero()
    )
    if refused_fields:
        lines.append(
            f"LIMITATION: {permission_denial_summary()}: "
            + " ".join(refused_fields)
        )
    return "\n".join(lines)


def _append_process(lines: list[str], process: LiveAgentProcess) -> None:
    name = process.name.value or "<name unavailable>"
    lines.append(f"  PID {process.pid} {name}")

    if process.cmdline.value is not None:
        lines.append(f"    cmdline: {process.cmdline.value}")
    else:
        failure = process.cmdline.failure
        assert failure is not None
        lines.append(f"    cmdline: <unavailable: {failure.value}>")

    if process.session_files.value is not None:
        for session in process.session_files.value:
            lines.append(f"    session: {session.session_id}")
            lines.append(f"      file: {session.path}")
    else:
        failure = process.session_files.failure
        assert failure is not None
        lines.append(f"    session: <unavailable: {failure.value}>")
