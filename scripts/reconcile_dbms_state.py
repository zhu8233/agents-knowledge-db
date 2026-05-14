#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def dump_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = ""
    if path.exists() and path.stat().st_size > 0:
        with path.open("rb") as fh:
            fh.seek(-1, 2)
            if fh.read(1) != b"\n":
                prefix = "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(prefix + json.dumps(payload, ensure_ascii=False) + "\n")


def normalized(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def choose_latest_index_report(reports_dir: Path) -> Path | None:
    candidates = [
        path for path in reports_dir.glob("*index-audit-report.md")
        if path.exists() and path.is_file() and not path.is_symlink() and safe_report_candidate(reports_dir, reports_dir, path.name) is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def safe_report_candidate(root: Path, reports_dir: Path, report_path: str | None) -> Path | None:
    if not isinstance(report_path, str) or not report_path:
        return None
    candidate = (root / report_path).resolve()
    source_path = root / report_path
    if not source_path.exists() or not source_path.is_file() or source_path.is_symlink():
        return None
    try:
        candidate.relative_to(reports_dir.resolve())
    except ValueError:
        return None
    if not candidate.name.endswith("index-audit-report.md"):
        return None
    return candidate


def reconcile_state(root: Path) -> None:
    reports_dir = root / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "reports"
    state_dir = root / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state"
    index_state_path = state_dir / "last-index-run.json"
    dbms_state_path = state_dir / "last-dbms-run.json"
    ledger_path = root / ".knowledge-registry" / "change-ledger.jsonl"
    reports_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    index_state = load_json(index_state_path)
    last_report_path = index_state.get("last_report_path")
    current_report = safe_report_candidate(root, reports_dir, last_report_path)
    chosen_index_report = current_report if current_report is not None and current_report.exists() else choose_latest_index_report(reports_dir)

    if isinstance(last_report_path, str) and last_report_path and chosen_index_report is None:
        raise RuntimeError("No valid DBMS index audit report is available to reconcile the broken last_report_path.")

    if chosen_index_report is not None:
        index_state["last_report_path"] = normalized(chosen_index_report, root)
    index_state["version"] = str(index_state.get("version", "1.0"))
    dump_json(index_state_path, index_state)

    reconciliation_report = reports_dir / f"{now.astimezone(timezone.utc).strftime('%Y-%m-%d')}-state-reconciliation.md"
    reconciliation_report.write_text(
        "\n".join(
            [
                "# DBMS State Reconciliation",
                "",
                f"- Run time: {now_iso}",
                "- Actor: db-admin-agent",
                "- Task type: system_guard",
                "",
                "## Repaired State",
                "",
                f"- last-index-run report path: `{index_state.get('last_report_path')}`",
                f"- last-index-run status: `{index_state.get('last_status')}`",
                "- last-dbms-run updated to point to this reconciliation report.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    dbms_state = load_json(dbms_state_path) if dbms_state_path.exists() else {"version": "1.1"}
    dbms_state.update(
        {
            "version": str(dbms_state.get("version", "1.1")),
            "last_dbms_run": now_iso,
            "last_actor": "db-admin-agent",
            "last_task_type": "system_guard",
            "last_report_path": normalized(reconciliation_report, root),
            "last_status": "state-reconciled",
        }
    )
    dump_json(dbms_state_path, dbms_state)

    append_jsonl(
        ledger_path,
        {
            "timestamp": now_iso,
            "actor": "db-admin-agent",
            "operation": "state_reconcile",
            "target_path": "01-Workflow/Knowledge-Governance/DBMS/state",
            "kb_id": "kb.system.dbms.state-reconcile",
            "topic_id": "topic.dbms-control-plane",
            "layer": "system",
            "summary": "Reconciled DBMS state files and repaired missing index report references.",
            "registry_updated": False,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile DBMS state files with current reports and index outputs.")
    parser.add_argument("target_vault", help="Path to the governed data vault")
    args = parser.parse_args()
    try:
        reconcile_state(Path(args.target_vault).resolve())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"DBMS_STATE_RECONCILED\t{Path(args.target_vault).resolve()}")


if __name__ == "__main__":
    main()
