from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


VALID_STATUSES = {"proposed", "approved", "rejected", "applied"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_store(vault_root: Path) -> tuple[Path, dict]:
    path = Path(vault_root).resolve() / ".knowledge-registry" / "governance-proposals.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return path, data


def list_proposals(vault_root: Path, *, proposal_type: str | None = None, status: str | None = None) -> dict:
    _, store = _load_store(vault_root)
    items = store.get("items", [])
    if proposal_type is not None:
        items = [item for item in items if item.get("proposal_type") == proposal_type]
    if status is not None:
        items = [item for item in items if item.get("status") == status]
    return {
        "items": items,
        "totalItems": len(items),
        "lastUpdated": store.get("last_updated"),
    }


def create_proposal(
    vault_root: Path,
    *,
    subject_id: str,
    proposal_type: str,
    summary: str,
    details: dict,
    proposal_id: str | None = None,
) -> dict:
    path, store = _load_store(vault_root)
    submitted_at = _now()
    proposal = {
        "proposal_id": proposal_id or f"proposal.{uuid4().hex[:12]}",
        "proposal_type": proposal_type,
        "status": "proposed",
        "submitted_by": subject_id,
        "submitted_at": submitted_at,
        "reviewed_by": None,
        "reviewed_at": None,
        "applied_by": None,
        "applied_at": None,
        "summary": summary,
        "details": details,
    }
    store["items"].append(proposal)
    store["last_updated"] = submitted_at[:10]
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    return proposal


def get_proposal(vault_root: Path, proposal_id: str) -> dict:
    _, store = _load_store(vault_root)
    for item in store.get("items", []):
        if item.get("proposal_id") == proposal_id:
            return item
    raise ValueError(f"Unknown proposal_id: {proposal_id}")


def update_proposal_status(
    vault_root: Path,
    *,
    proposal_id: str,
    new_status: str,
    actor: str,
    summary: str | None = None,
) -> dict:
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Invalid proposal status: {new_status}")

    path, store = _load_store(vault_root)
    changed_at = _now()
    updated = None
    next_items = []
    for item in store.get("items", []):
        if item.get("proposal_id") != proposal_id:
            next_items.append(item)
            continue

        current_status = item.get("status")
        if current_status == "applied":
            raise ValueError(f"Proposal `{proposal_id}` is already applied")
        if current_status == "rejected" and new_status != "rejected":
            raise ValueError(f"Proposal `{proposal_id}` is rejected and cannot transition to `{new_status}`")
        if current_status != "approved" and new_status == "applied":
            raise ValueError(f"Proposal `{proposal_id}` must be approved before apply")

        updated = dict(item)
        updated["status"] = new_status
        if summary is not None:
            updated["summary"] = summary
        if new_status in {"approved", "rejected"}:
            updated["reviewed_by"] = actor
            updated["reviewed_at"] = changed_at
        if new_status == "applied":
            updated["applied_by"] = actor
            updated["applied_at"] = changed_at
        next_items.append(updated)

    if updated is None:
        raise ValueError(f"Unknown proposal_id: {proposal_id}")

    store["items"] = next_items
    store["last_updated"] = changed_at[:10]
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    return updated
