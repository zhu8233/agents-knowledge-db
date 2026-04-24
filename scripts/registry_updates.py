from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from proposal_store import create_proposal, update_proposal_status


IDENTITY_KEYS = {
    "topic": "topic_id",
    "object": "kb_id",
    "adapter": "adapter_id",
}

REGISTRY_ARRAY_KEYS = {
    "topic": "topics",
    "object": "objects",
    "adapter": "adapters",
}


def _append_jsonl(path: Path, payload: dict) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    prefix = "\n" if path.exists() and path.read_text(encoding="utf-8").rstrip("\n") else ""
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{prefix}{serialized}\n")


def _replace_or_append(items: list[dict], identity_key: str, entry: dict) -> tuple[list[dict], bool]:
    updated = False
    identity_value = entry[identity_key]
    next_items = []
    for item in items:
        if item.get(identity_key) == identity_value:
            next_items.append(entry)
            updated = True
        else:
            next_items.append(item)
    if not updated:
        next_items.append(entry)
    return next_items, updated


def _ledger_metadata(target_kind: str, entry: dict) -> tuple[str, str, str]:
    if target_kind == "topic":
        target_path = entry.get("canonical_home") or (entry.get("intake_paths") or [entry["topic_id"]])[0]
        kb_id = f"registry.topic.{entry['topic_id']}"
        topic_id = entry["topic_id"]
        layer = "system"
        return target_path, kb_id, topic_id, layer
    if target_kind == "object":
        return entry["path"], entry["kb_id"], entry["topic_id"], entry["kb_layer"]
    target_path = entry["path"]
    kb_id = f"registry.adapter.{entry['adapter_id']}"
    topic_id = entry.get("owner", "system")
    layer = "system"
    return target_path, kb_id, topic_id, layer


def apply_registry_update(
    vault_root: Path,
    *,
    subject_id: str,
    operation: str,
    target_kind: str,
    summary: str,
    entry: dict,
) -> dict:
    if target_kind not in IDENTITY_KEYS:
        raise ValueError(f"Unsupported target_kind: {target_kind}")
    expected_operation = f"upsert_{target_kind}"
    if operation != expected_operation:
        raise ValueError(f"Unsupported operation `{operation}` for target_kind `{target_kind}`")

    registry_path = Path(vault_root).resolve() / ".knowledge-registry" / "vault-registry.json"
    ledger_path = Path(vault_root).resolve() / ".knowledge-registry" / "change-ledger.jsonl"

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    identity_key = IDENTITY_KEYS[target_kind]
    container_key = REGISTRY_ARRAY_KEYS[target_kind]
    if identity_key not in entry:
        raise ValueError(f"Entry must include `{identity_key}`")

    updated_items, existed = _replace_or_append(registry[container_key], identity_key, entry)
    registry[container_key] = updated_items
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    target_path, kb_id, topic_id, layer = _ledger_metadata(target_kind, entry)
    ledger_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "actor": subject_id,
        "operation": operation,
        "target_path": target_path,
        "kb_id": kb_id,
        "topic_id": topic_id,
        "layer": layer,
        "summary": summary,
        "registry_updated": True,
    }
    _append_jsonl(ledger_path, ledger_entry)

    return {
        "targetKind": target_kind,
        "operation": operation,
        "updatedEntry": entry,
        "updated": existed,
        "created": not existed,
        "ledgerEntry": ledger_entry,
    }


def propose_registry_update(
    vault_root: Path,
    *,
    subject_id: str,
    target_kind: str,
    operation: str,
    summary: str,
    details: dict,
) -> dict:
    proposal = create_proposal(
        Path(vault_root).resolve(),
        subject_id=subject_id,
        proposal_type="registry_update",
        summary=summary,
        details={
            "target_kind": target_kind,
            "operation": operation,
            **details,
        },
    )
    return proposal


def apply_registry_update_with_proposal(
    vault_root: Path,
    *,
    subject_id: str,
    operation: str,
    target_kind: str,
    summary: str,
    entry: dict,
    proposal_id: str | None = None,
) -> dict:
    result = apply_registry_update(
        Path(vault_root).resolve(),
        subject_id=subject_id,
        operation=operation,
        target_kind=target_kind,
        summary=summary,
        entry=entry,
    )
    if proposal_id is not None:
        result["governanceProposal"] = update_proposal_status(
            Path(vault_root).resolve(),
            proposal_id=proposal_id,
            new_status="applied",
            actor=subject_id,
        )
    return result
