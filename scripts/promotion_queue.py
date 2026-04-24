from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from proposal_store import create_proposal, update_proposal_status
from registry_updates import _append_jsonl


def list_promotion_queue(vault_root: Path) -> dict:
    root = Path(vault_root).resolve()
    queue_path = root / ".knowledge-registry" / "promotion-queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    return {
        "items": queue.get("items", []),
        "totalItems": len(queue.get("items", [])),
        "lastUpdated": queue.get("last_updated"),
    }


def create_promotion_proposal(
    vault_root: Path,
    *,
    subject_id: str,
    topic_id: str,
    source_path: str,
    candidate_path: str,
    summary: str,
) -> dict:
    root = Path(vault_root).resolve()
    queue_path = root / ".knowledge-registry" / "promotion-queue.json"
    ledger_path = root / ".knowledge-registry" / "change-ledger.jsonl"

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    submitted_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    governance_proposal = create_proposal(
        root,
        subject_id=subject_id,
        proposal_type="promotion",
        summary=summary,
        details={
            "topic_id": topic_id,
            "source_path": source_path,
            "candidate_path": candidate_path,
        },
    )
    proposal = {
        "proposal_id": governance_proposal["proposal_id"],
        "topic_id": topic_id,
        "source_path": source_path,
        "candidate_path": candidate_path,
        "status": "proposed",
        "submitted_by": subject_id,
        "submitted_at": submitted_at,
    }
    queue["items"].append(proposal)
    queue["last_updated"] = submitted_at[:10]
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")

    ledger_entry = {
        "timestamp": submitted_at,
        "actor": subject_id,
        "operation": "promotion_proposal_create",
        "target_path": candidate_path,
        "kb_id": f"proposal.{topic_id}",
        "topic_id": topic_id,
        "layer": "canonical",
        "summary": summary,
        "registry_updated": True,
    }
    _append_jsonl(ledger_path, ledger_entry)

    return {
        "proposal": proposal,
        "governanceProposal": governance_proposal,
        "ledgerEntry": ledger_entry,
    }


def review_promotion_proposal(
    vault_root: Path,
    *,
    subject_id: str,
    proposal_id: str,
    decision: str,
    summary: str,
) -> dict:
    if decision not in {"approve", "reject"}:
        raise ValueError("decision must be `approve` or `reject`")

    root = Path(vault_root).resolve()
    queue_path = root / ".knowledge-registry" / "promotion-queue.json"
    ledger_path = root / ".knowledge-registry" / "change-ledger.jsonl"

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    reviewed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    updated_proposal = None
    next_items = []
    for item in queue.get("items", []):
        if item.get("proposal_id") == proposal_id:
            updated_proposal = {
                **item,
                "status": "approved" if decision == "approve" else "rejected",
                "reviewed_by": subject_id,
                "reviewed_at": reviewed_at,
                "review_summary": summary,
            }
            next_items.append(updated_proposal)
        else:
            next_items.append(item)

    if updated_proposal is None:
        raise ValueError(f"Unknown proposal_id: {proposal_id}")

    queue["items"] = next_items
    queue["last_updated"] = reviewed_at[:10]
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")

    governance_proposal = update_proposal_status(
        root,
        proposal_id=proposal_id,
        new_status="approved" if decision == "approve" else "rejected",
        actor=subject_id,
    )

    ledger_entry = {
        "timestamp": reviewed_at,
        "actor": subject_id,
        "operation": "promotion_proposal_review",
        "target_path": updated_proposal["candidate_path"],
        "kb_id": updated_proposal["proposal_id"],
        "topic_id": updated_proposal["topic_id"],
        "layer": "canonical",
        "summary": summary,
        "registry_updated": True,
    }
    _append_jsonl(ledger_path, ledger_entry)

    return {
        "proposal": updated_proposal,
        "governanceProposal": governance_proposal,
        "ledgerEntry": ledger_entry,
    }


def apply_promotion_proposal(
    vault_root: Path,
    *,
    subject_id: str,
    proposal_id: str,
    summary: str,
) -> dict:
    root = Path(vault_root).resolve()
    queue_path = root / ".knowledge-registry" / "promotion-queue.json"
    registry_path = root / ".knowledge-registry" / "vault-registry.json"
    ledger_path = root / ".knowledge-registry" / "change-ledger.jsonl"

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    applied_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    updated_proposal = None
    next_items = []
    for item in queue.get("items", []):
        if item.get("proposal_id") == proposal_id:
            if item.get("status") == "applied":
                raise ValueError(f"Proposal `{proposal_id}` is already applied")
            if item.get("status") != "approved":
                raise ValueError(f"Proposal `{proposal_id}` must be approved before apply")
            updated_proposal = {
                **item,
                "status": "applied",
                "applied_by": subject_id,
                "applied_at": applied_at,
                "apply_summary": summary,
            }
            next_items.append(updated_proposal)
        else:
            next_items.append(item)

    if updated_proposal is None:
        raise ValueError(f"Unknown proposal_id: {proposal_id}")

    updated_topic = None
    next_topics = []
    for topic in registry.get("topics", []):
        if topic.get("topic_id") == updated_proposal["topic_id"]:
            updated_topic = {
                **topic,
                "canonical_home": updated_proposal["candidate_path"],
            }
            next_topics.append(updated_topic)
        else:
            next_topics.append(topic)

    if updated_topic is None:
        raise ValueError(f"Unknown topic for proposal `{proposal_id}`")

    queue["items"] = next_items
    queue["last_updated"] = applied_at[:10]
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")

    registry["topics"] = next_topics
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    governance_proposal = update_proposal_status(
        root,
        proposal_id=proposal_id,
        new_status="applied",
        actor=subject_id,
    )

    ledger_entry = {
        "timestamp": applied_at,
        "actor": subject_id,
        "operation": "promotion_proposal_apply",
        "target_path": updated_proposal["candidate_path"],
        "kb_id": updated_proposal["proposal_id"],
        "topic_id": updated_proposal["topic_id"],
        "layer": "canonical",
        "summary": summary,
        "registry_updated": True,
    }
    _append_jsonl(ledger_path, ledger_entry)

    return {
        "proposal": updated_proposal,
        "governanceProposal": governance_proposal,
        "updatedTopic": updated_topic,
        "ledgerEntry": ledger_entry,
    }
