from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from proposal_store import create_proposal, update_proposal_status
from registry_updates import _append_jsonl
from sync_system_snapshot import sync_snapshot


def _effective_snapshot_ref(version: dict) -> str | None:
    return version.get("release_tag") or version.get("source_commit")


def review_snapshot_upgrade(vault_root: Path) -> dict:
    root = Path(vault_root).resolve()
    version_path = root / ".dbms-system" / "version.json"
    compat_path = root / "LocalOverrides" / "compatibility-status.json"

    version = json.loads(version_path.read_text(encoding="utf-8"))
    compat = json.loads(compat_path.read_text(encoding="utf-8"))

    snapshot_ref = _effective_snapshot_ref(version)
    compat_ref = compat.get("system_tag")
    status = "compatible" if snapshot_ref == compat_ref else "review-needed"
    return {
        "snapshotRef": snapshot_ref,
        "compatibilityRef": compat_ref,
        "status": status,
        "upgradeAvailable": status != "compatible",
        "snapshotVersion": version,
        "compatibilityStatus": compat,
    }


def apply_snapshot_upgrade(vault_root: Path, *, subject_id: str, summary: str) -> dict:
    root = Path(vault_root).resolve()
    sync_snapshot(root)

    version_path = root / ".dbms-system" / "version.json"
    compat_path = root / "LocalOverrides" / "compatibility-status.json"
    ledger_path = root / ".knowledge-registry" / "change-ledger.jsonl"

    version = json.loads(version_path.read_text(encoding="utf-8"))
    snapshot_ref = _effective_snapshot_ref(version)
    compat = json.loads(compat_path.read_text(encoding="utf-8"))
    compat.update(
        {
            "system_tag": snapshot_ref,
            "override_checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "compatible",
            "notes": summary,
        }
    )
    compat_path.write_text(json.dumps(compat, ensure_ascii=False, indent=2), encoding="utf-8")

    ledger_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "actor": subject_id,
        "operation": "system_snapshot_apply",
        "target_path": ".dbms-system",
        "kb_id": "kb.system.snapshot",
        "topic_id": "topic.governance",
        "layer": "system",
        "summary": summary,
        "registry_updated": True,
    }
    _append_jsonl(ledger_path, ledger_entry)

    return {
        "snapshotRef": snapshot_ref,
        "status": "compatible",
        "compatibilityStatus": compat,
        "ledgerEntry": ledger_entry,
    }


def request_snapshot_review(vault_root: Path, *, subject_id: str, summary: str) -> dict:
    root = Path(vault_root).resolve()
    review = review_snapshot_upgrade(root)
    proposal = create_proposal(
        root,
        subject_id=subject_id,
        proposal_type="snapshot_upgrade",
        summary=summary,
        details={
            "snapshotRef": review["snapshotRef"],
            "compatibilityRef": review["compatibilityRef"],
            "status": review["status"],
        },
    )
    return {"proposal": proposal, "review": review}


def apply_snapshot_upgrade_with_proposal(
    vault_root: Path,
    *,
    subject_id: str,
    summary: str,
    proposal_id: str | None = None,
) -> dict:
    result = apply_snapshot_upgrade(vault_root, subject_id=subject_id, summary=summary)
    if proposal_id is not None:
        result["governanceProposal"] = update_proposal_status(
            Path(vault_root).resolve(),
            proposal_id=proposal_id,
            new_status="applied",
            actor=subject_id,
        )
    return result
