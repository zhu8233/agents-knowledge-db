from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from proposal_store import create_proposal, get_proposal, update_proposal_status
from registry_updates import _append_jsonl
from sync_system_snapshot import current_snapshot_version, sync_snapshot


def _effective_snapshot_ref(version: dict) -> str | None:
    return version.get("snapshot_ref") or version.get("release_tag") or version.get("source_commit")


def current_snapshot_apply_context(vault_root: Path) -> dict:
    root = Path(vault_root).resolve()
    compat_path = root / "LocalOverrides" / "compatibility-status.json"
    compat = json.loads(compat_path.read_text(encoding="utf-8"))
    source_version = current_snapshot_version()
    return {
        "snapshotRef": _effective_snapshot_ref(source_version),
        "compatibilityRef": compat.get("system_tag"),
        "snapshotVersion": source_version,
        "compatibilityStatus": compat,
    }


def validate_snapshot_proposal_for_apply(
    vault_root: Path,
    *,
    proposal_id: str,
    allow_pending_with_approval: bool,
    apply_context: dict | None = None,
) -> dict:
    root = Path(vault_root).resolve()
    proposal = get_proposal(root, proposal_id.strip())
    if proposal.get("proposal_type") != "snapshot_upgrade":
        raise ValueError(f"Proposal `{proposal_id}` is not a snapshot_upgrade proposal")

    apply_context = apply_context or current_snapshot_apply_context(root)
    details = proposal.get("details") or {}
    if (
        details.get("snapshotRef") != apply_context["snapshotRef"]
        or details.get("compatibilityRef") != apply_context["compatibilityRef"]
    ):
        raise ValueError(f"Proposal `{proposal_id}` does not match the current snapshot review")

    status = proposal.get("status")
    if status == "rejected":
        raise ValueError(f"Proposal `{proposal_id}` is rejected and cannot authorize snapshot apply")
    if status == "applied":
        raise ValueError(f"Proposal `{proposal_id}` is already applied")
    if not allow_pending_with_approval and status != "approved":
        raise ValueError(f"Proposal `{proposal_id}` must be approved before apply")
    return proposal


def review_snapshot_upgrade(vault_root: Path) -> dict:
    root = Path(vault_root).resolve()
    compat_path = root / "LocalOverrides" / "compatibility-status.json"

    version = current_snapshot_version()
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


def apply_snapshot_upgrade(
    vault_root: Path,
    *,
    subject_id: str,
    summary: str,
    approval: dict | None = None,
    expected_snapshot_context: dict | None = None,
) -> dict:
    root = Path(vault_root).resolve()
    expected_context = expected_snapshot_context or current_snapshot_apply_context(root)
    current_context = current_snapshot_apply_context(root)
    if current_context["snapshotRef"] != expected_context["snapshotRef"]:
        raise RuntimeError("shipped snapshot changed before apply")
    if current_context["compatibilityRef"] != expected_context["compatibilityRef"]:
        raise RuntimeError("compatibility status changed before apply")

    expected_version = expected_context["snapshotVersion"]
    expected_snapshot_ref = _effective_snapshot_ref(expected_version)
    sync_snapshot(root, expected_version=expected_version)

    version_path = root / ".dbms-system" / "version.json"
    compat_path = root / "LocalOverrides" / "compatibility-status.json"
    ledger_path = root / ".knowledge-registry" / "change-ledger.jsonl"

    version = json.loads(version_path.read_text(encoding="utf-8"))
    snapshot_ref = _effective_snapshot_ref(version)
    if snapshot_ref != expected_snapshot_ref:
        raise RuntimeError("shipped snapshot changed during apply")
    compat = json.loads(compat_path.read_text(encoding="utf-8"))
    compat.update(
        {
            "system_tag": snapshot_ref,
            "override_checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "compatible",
            "notes": summary,
        }
    )
    if approval is not None:
        compat["approval_evidence"] = approval
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
    if approval is not None:
        ledger_entry["approval_evidence"] = approval
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
    apply_context = current_snapshot_apply_context(root)
    proposal = create_proposal(
        root,
        subject_id=subject_id,
        proposal_type="snapshot_upgrade",
        summary=summary,
        details={
            "snapshotRef": apply_context["snapshotRef"],
            "compatibilityRef": apply_context["compatibilityRef"],
            "status": review["status"],
        },
    )
    return {"proposal": proposal, "review": review, "applyContext": apply_context}


def apply_snapshot_upgrade_with_proposal(
    vault_root: Path,
    *,
    subject_id: str,
    summary: str,
    proposal_id: str | None = None,
    approval: dict | None = None,
    expected_snapshot_context: dict | None = None,
) -> dict:
    root = Path(vault_root).resolve()
    expected_context = expected_snapshot_context or current_snapshot_apply_context(root)
    if proposal_id is not None:
        proposal_id = proposal_id.strip()
        proposal = validate_snapshot_proposal_for_apply(
            root,
            proposal_id=proposal_id,
            allow_pending_with_approval=approval is not None,
            apply_context=expected_context,
        )
        if approval is not None and proposal.get("status") != "approved":
            update_proposal_status(
                root,
                proposal_id=proposal_id,
                new_status="approved",
                actor=subject_id,
                metadata_updates={"approval_evidence": approval},
            )

    result = apply_snapshot_upgrade(
        vault_root,
        subject_id=subject_id,
        summary=summary,
        approval=approval,
        expected_snapshot_context=expected_context,
    )
    if proposal_id is not None:
        result["governanceProposal"] = update_proposal_status(
            root,
            proposal_id=proposal_id,
            new_status="applied",
            actor=subject_id,
            metadata_updates={"approval_evidence": approval} if approval is not None else None,
        )
    return result
