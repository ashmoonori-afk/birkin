"""Eval CLI commands — run, list, diff."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from birkin.core.models import Message
from birkin.core.providers import create_provider
from birkin.eval.dataset import EvalDataset
from birkin.eval.runner import EvalReport, EvalResult, EvalRunner
from birkin.eval.storage import EvalStorage

logger = logging.getLogger(__name__)

_DEFAULT_OUTPUT_DIR = Path("eval_results")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_target_fn(provider_name: str):
    """Create an async target function that wraps a Birkin provider."""
    provider = create_provider(provider_name)

    async def _target(input_data: dict) -> dict:
        prompt = input_data.get("prompt", "")
        messages = [Message(role="user", content=prompt)]
        response = await provider.acomplete(messages)

        tokens_in = 0
        tokens_out = 0
        cost_usd = 0.0
        if response.usage:
            tokens_in = response.usage.prompt_tokens
            tokens_out = response.usage.completion_tokens

        return {
            "output": response.content or "",
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
        }

    return provider, _target


def _print_report(console: Console, report: EvalReport) -> None:
    """Print a Rich table summarising an eval report."""
    table = Table(title=f"Eval: {report.dataset_name} -> {report.target}")
    table.add_column("Case ID", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Latency (ms)", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Output (truncated)")

    for r in report.results:
        status = "[green]OK[/green]" if r.error is None else f"[red]ERR: {r.error[:30]}[/red]"
        tokens = str(r.tokens_in + r.tokens_out)
        output_preview = (r.output[:60] + "...") if len(r.output) > 60 else r.output
        table.add_row(r.case_id, status, str(r.latency_ms), tokens, output_preview)

    console.print(table)
    console.print(
        f"\n[bold]Summary:[/bold] {report.success_count} passed, "
        f"{report.error_count} errors, "
        f"{report.total_tokens} tokens, "
        f"{report.total_latency_ms}ms total, "
        f"${report.total_cost_usd:.4f} cost\n"
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


async def cmd_eval_run(
    dataset_path: str,
    provider_name: str,
    output_dir: Optional[str] = None,
    *,
    use_memory: bool = False,
) -> EvalReport:
    """Load dataset, run eval against provider, save results, print table."""
    import tempfile

    from birkin.memory.wiki import WikiMemory

    console = Console()
    ds_path = Path(dataset_path)

    if not ds_path.is_file():
        console.print(f"[red]Dataset not found:[/red] {ds_path}")
        raise SystemExit(1)

    dataset = EvalDataset.from_jsonl(ds_path)
    console.print(f"Loaded [bold]{len(dataset.cases)}[/bold] cases from [cyan]{ds_path.name}[/cyan]")

    provider, target_fn = _build_target_fn(provider_name)
    target_label = f"{provider.name}/{provider.model}"
    if use_memory:
        target_label += "+memory"

    memory: Optional[WikiMemory] = None
    if use_memory:
        tmp_dir = tempfile.mkdtemp(prefix="birkin_eval_root_")
        memory = WikiMemory(root=tmp_dir)
        memory.init()
        console.print("[cyan]Memory-aware eval enabled[/cyan]")

    console.print(f"Running against [cyan]{target_label}[/cyan] ...")
    runner = EvalRunner(target_label, target_fn, memory=memory)
    report = await runner.run_dataset(dataset)

    storage = EvalStorage(Path(output_dir) if output_dir else _DEFAULT_OUTPUT_DIR)
    saved = storage.save_report(report)
    console.print(f"Results saved to [green]{saved}[/green]\n")

    _print_report(console, report)
    return report


def cmd_eval_list(output_dir: Optional[str] = None) -> list[str]:
    """List saved eval result datasets."""
    console = Console()
    storage = EvalStorage(Path(output_dir) if output_dir else _DEFAULT_OUTPUT_DIR)
    datasets = storage.list_datasets()

    if not datasets:
        console.print("[dim]No eval results found.[/dim]")
        return datasets

    table = Table(title="Saved Eval Results")
    table.add_column("Dataset", style="cyan")
    table.add_column("Results", justify="right")

    for name in datasets:
        count = len(storage.load_results(name))
        table.add_row(name, str(count))

    console.print(table)
    return datasets


def _load_results_from_file(path: Path) -> list[EvalResult]:
    """Load EvalResult objects from a JSONL file."""
    results: list[EvalResult] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            results.append(EvalResult.model_validate_json(line))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Skipping malformed line: %s", exc)
    return results


def cmd_eval_diff(baseline_path: str, current_path: str) -> dict:
    """Compare two result files and print a delta table."""
    console = Console()
    base_file = Path(baseline_path)
    curr_file = Path(current_path)

    if not base_file.is_file():
        console.print(f"[red]Baseline not found:[/red] {base_file}")
        raise SystemExit(1)
    if not curr_file.is_file():
        console.print(f"[red]Current not found:[/red] {curr_file}")
        raise SystemExit(1)

    base_results = _load_results_from_file(base_file)
    curr_results = _load_results_from_file(curr_file)

    base_map = {r.case_id: r for r in base_results}
    curr_map = {r.case_id: r for r in curr_results}
    all_ids = sorted(set(base_map) | set(curr_map))

    table = Table(title=f"Diff: {base_file.name} vs {curr_file.name}")
    table.add_column("Case ID", style="cyan")
    table.add_column("Latency Delta (ms)", justify="right")
    table.add_column("Token Delta", justify="right")
    table.add_column("Status Change")

    deltas: dict[str, dict] = {}
    for cid in all_ids:
        b = base_map.get(cid)
        c = curr_map.get(cid)

        if b and c:
            lat_delta = c.latency_ms - b.latency_ms
            tok_delta = (c.tokens_in + c.tokens_out) - (b.tokens_in + b.tokens_out)
            b_status = "ERR" if b.error else "OK"
            c_status = "ERR" if c.error else "OK"
            status_change = f"{b_status} -> {c_status}" if b_status != c_status else "—"

            lat_str = f"{lat_delta:+d}"
            tok_str = f"{tok_delta:+d}"
            table.add_row(cid, lat_str, tok_str, status_change)
            deltas[cid] = {
                "latency_delta_ms": lat_delta,
                "token_delta": tok_delta,
                "status_change": status_change,
            }
        elif b and not c:
            table.add_row(cid, "—", "—", "[yellow]REMOVED[/yellow]")
            deltas[cid] = {"latency_delta_ms": 0, "token_delta": 0, "status_change": "REMOVED"}
        else:
            table.add_row(cid, "—", "—", "[green]NEW[/green]")
            deltas[cid] = {"latency_delta_ms": 0, "token_delta": 0, "status_change": "NEW"}

    console.print(table)

    # Summary
    base_total_lat = sum(r.latency_ms for r in base_results)
    curr_total_lat = sum(r.latency_ms for r in curr_results)
    base_total_tok = sum(r.tokens_in + r.tokens_out for r in base_results)
    curr_total_tok = sum(r.tokens_in + r.tokens_out for r in curr_results)

    console.print(
        f"\n[bold]Totals:[/bold] latency {curr_total_lat - base_total_lat:+d}ms, "
        f"tokens {curr_total_tok - base_total_tok:+d}\n"
    )

    return deltas
