#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


IGNORE_DIRS = {".git", ".worktrees", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
IGNORE_SUFFIXES = {".pyc", ".tmp", ".temp", ".cache", ".log"}
ADAPTER_FILES = {"RULES.md", "CLAUDE.md", "AGENTS.md", "GEMINI.md"}
RUNTIME_PREFIXES = (
    "01-Workflow/Knowledge-Governance/DBMS/index/",
    "01-Workflow/Knowledge-Governance/DBMS/reports/",
    "01-Workflow/Knowledge-Governance/DBMS/state/",
)
SYSTEM_PROTECTED_PREFIXES = (
    ".knowledge-registry/",
    ".obsidian/",
    ".claude/",
    ".dbms-system/",
    "LocalOverrides/",
    "01-Workflow/Knowledge-Governance/",
)


def prefix_match(rel_path: str, candidate: str) -> bool:
    normalized_candidate = candidate.strip("/")
    return rel_path == normalized_candidate or rel_path.startswith(normalized_candidate + "/")


def build_topic_layer_overrides(topics: list[dict]) -> list[tuple[str, str]]:
    overrides: list[tuple[str, str]] = []
    for topic in topics:
        for path in topic.get("curation_paths", []):
            overrides.append((path, "curation"))
        for path in topic.get("intake_paths", []):
            overrides.append((path, "intake"))
        canonical_home = topic.get("canonical_home")
        if canonical_home:
            overrides.append((canonical_home, "canonical"))
    overrides.sort(key=lambda item: len(item[0]), reverse=True)
    return overrides


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


def should_ignore(path: Path, root: Path) -> bool:
    rel = normalized(path, root)
    if path.is_symlink():
        return True
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    if any(part in IGNORE_DIRS for part in path.parts):
        return True
    if path.suffix.lower() in IGNORE_SUFFIXES:
        return True
    if rel.startswith(RUNTIME_PREFIXES):
        return True
    return False


def classify_zone(rel_path: str, topic_layer_overrides: list[tuple[str, str]]) -> tuple[str, str, str]:
    if rel_path.startswith(".dbms-system/"):
        return "system_snapshot", "system", "snapshot"
    if rel_path.startswith(".knowledge-registry/"):
        return "registry", "system", "protected"
    if rel_path.startswith("LocalOverrides/"):
        return "local_override", "system", "protected"
    if rel_path.startswith(("01-Workflow/Knowledge-Governance/", ".obsidian/", ".claude/")) or rel_path in ADAPTER_FILES:
        return "system_local", "system", "protected"
    for candidate, layer in topic_layer_overrides:
        if prefix_match(rel_path, candidate):
            return layer, layer, "data"
    if rel_path.startswith(("ProjectRaw/", "00-GoogleDrive_SyncData/")):
        return "intake", "intake", "data"
    if rel_path.startswith(("40-Projects/", "Excalidraw/")):
        return "curation", "curation", "data"
    if rel_path.startswith("20-KnowledgeHub/"):
        return "canonical", "canonical", "data"
    if rel_path.startswith("90-Archive/"):
        return "archive", "archive", "data"
    return "system_local", "system", "protected"


def content_kind_for(rel_path: str) -> str:
    lower = rel_path.lower()
    if lower.endswith(".excalidraw.md"):
        return "drawing_note"
    if lower.endswith(".md"):
        return "markdown"
    if lower.endswith(".json"):
        return "json"
    if lower.endswith(".jsonl"):
        return "jsonl"
    if lower.endswith(".svg"):
        return "vector_asset"
    if lower.endswith(".gdoc"):
        return "external_doc_link"
    if lower.endswith(".py"):
        return "script"
    return "binary_or_other"


def ext_for(rel_path: str) -> str:
    if rel_path.lower().endswith(".excalidraw.md"):
        return ".excalidraw.md"
    return Path(rel_path).suffix.lower()


def read_frontmatter_status(path: Path, rel_path: str, zone: str, content_kind: str) -> str:
    if content_kind != "markdown":
        return "not_applicable"
    if rel_path in ADAPTER_FILES:
        return "not_applicable"
    if rel_path.startswith((".dbms-system/", ".knowledge-registry/", "LocalOverrides/")):
        return "not_applicable"
    if rel_path.startswith(("01-Workflow/Knowledge-Governance/DBMS/index/", "01-Workflow/Knowledge-Governance/DBMS/reports/")):
        return "not_applicable"
    if zone == "system_snapshot":
        return "not_applicable"

    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---\n"):
        return "missing"
    end = text.find("\n---", 4)
    if end == -1:
        return "invalid"
    return "present"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def timestamp_for(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def build_path_index(objects: list[dict]) -> dict[str, list[dict]]:
    by_path: dict[str, list[dict]] = defaultdict(list)
    for obj in objects:
        by_path[obj["path"]].append(obj)
    return by_path


def finding(finding_type: str, path: str, summary: str, *, kb_id: str | None = None, topic_id: str | None = None) -> dict:
    return {
        "finding_type": finding_type,
        "path": path,
        "kb_id": kb_id,
        "topic_id": topic_id,
        "summary": summary,
    }


def report_path(root: Path, now: datetime) -> Path:
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    return root / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "reports" / f"{stamp}-index-audit-report.md"


def choose_control_topic(topics: set[str]) -> str:
    for candidate in ("topic.dbms-control-plane", "topic.vault-governance", "topic.knowledge-governance"):
        if candidate in topics:
            return candidate
    return sorted(topics)[0] if topics else "topic.unresolved"


def rebuild_index(root: Path) -> None:
    registry_path = root / ".knowledge-registry" / "vault-registry.json"
    ledger_path = root / ".knowledge-registry" / "change-ledger.jsonl"
    registry = load_json(registry_path)
    objects = registry.get("objects", [])
    topics_payload = registry.get("topics", [])
    topics = {item["topic_id"] for item in topics_payload}
    topic_layer_overrides = build_topic_layer_overrides(topics_payload)
    by_path = build_path_index(objects)

    now = datetime.now(timezone.utc)
    scanned_at = now.isoformat()
    entries: list[dict] = []
    findings: list[dict] = []
    seen_paths: set[str] = set()
    topic_counter: dict[str, Counter] = defaultdict(Counter)

    for path in sorted(root.rglob("*")):
        if not path.is_file() or should_ignore(path, root):
            continue

        rel_path = normalized(path, root)
        seen_paths.add(rel_path)
        zone, kb_layer_guess, protection_class = classify_zone(rel_path, topic_layer_overrides)
        content_kind = content_kind_for(rel_path)
        frontmatter_status = read_frontmatter_status(path, rel_path, zone, content_kind)
        objects_for_path = by_path.get(rel_path, [])
        scan_flags: list[str] = []

        if len(objects_for_path) > 1:
            registry_status = "registry_path_duplicate"
            findings.append(
                finding(
                    "duplicate_registry_path",
                    rel_path,
                    "Path is registered more than once in vault-registry.objects.",
                    topic_id=objects_for_path[0].get("topic_id"),
                )
            )
        elif not objects_for_path:
            registry_status = "unregistered"
        else:
            obj = objects_for_path[0]
            registry_status = "registered"
            if obj.get("kb_layer") != kb_layer_guess and kb_layer_guess != "system":
                registry_status = "layer_mismatch"
                findings.append(
                    finding(
                        "layer_path_mismatch",
                        rel_path,
                        f"Registry layer '{obj.get('kb_layer')}' does not match path-implied layer '{kb_layer_guess}'.",
                        kb_id=obj.get("kb_id"),
                        topic_id=obj.get("topic_id"),
                    )
                )
            if obj.get("topic_id") not in topics:
                scan_flags.append("topic_unresolved")
                findings.append(
                    finding(
                        "topic_unresolved",
                        rel_path,
                        "Registry object points to a topic_id that does not exist in topics.",
                        kb_id=obj.get("kb_id"),
                        topic_id=obj.get("topic_id"),
                    )
                )

        if frontmatter_status == "missing":
            scan_flags.append("frontmatter_missing")
            findings.append(finding("frontmatter_missing", rel_path, "Markdown object is missing YAML frontmatter."))
        elif frontmatter_status == "invalid":
            scan_flags.append("frontmatter_invalid")
            findings.append(finding("frontmatter_invalid", rel_path, "Markdown object has invalid YAML frontmatter fence."))

        if registry_status == "unregistered":
            findings.append(finding("unregistered_file", rel_path, "Scanned file is not represented in vault-registry.objects."))
            if rel_path.startswith(SYSTEM_PROTECTED_PREFIXES) and not rel_path.startswith(RUNTIME_PREFIXES):
                findings.append(
                    finding(
                        "protected_zone_unexpected_file",
                        rel_path,
                        "Protected zone contains an unregistered file outside expected DBMS runtime state.",
                    )
                )
        if zone == "canonical" and registry_status != "registered" and ("index" in rel_path.lower() or "索引" in rel_path):
            findings.append(
                finding(
                    "canonical_orphan_index",
                    rel_path,
                    "Canonical index-like file is present without a matching registry object.",
                )
            )

        obj = objects_for_path[0] if len(objects_for_path) == 1 else {}
        entries.append(
            {
                "path": rel_path,
                "ext": ext_for(rel_path),
                "content_kind": content_kind,
                "zone": zone,
                "kb_layer_guess": kb_layer_guess,
                "protection_class": protection_class,
                "kb_id": obj.get("kb_id"),
                "topic_id": obj.get("topic_id"),
                "registry_status": registry_status,
                "frontmatter_status": frontmatter_status,
                "size": path.stat().st_size,
                "last_modified": timestamp_for(path),
                "content_hash": sha256_file(path),
                "last_scanned_at": scanned_at,
                "scan_flags": scan_flags,
            }
        )

    for rel_path, objects_for_path in sorted(by_path.items()):
        if rel_path in seen_paths:
            continue
        if len(objects_for_path) > 1:
            findings.append(
                finding(
                    "duplicate_registry_path",
                    rel_path,
                    "Path is registered more than once in vault-registry.objects.",
                    topic_id=objects_for_path[0].get("topic_id"),
                )
            )
            continue
        obj = objects_for_path[0]
        topic_counter[obj.get("topic_id") or "__unassigned__"]["registry_missing_file"] += 1
        findings.append(
            finding(
                "registry_missing_file",
                rel_path,
                "Registry object points to a file that does not exist on disk.",
                kb_id=obj.get("kb_id"),
                topic_id=obj.get("topic_id"),
            )
        )
        if obj.get("topic_id") not in topics:
            findings.append(
                finding(
                    "topic_unresolved",
                    rel_path,
                    "Missing file also points to an unresolved topic_id.",
                    kb_id=obj.get("kb_id"),
                    topic_id=obj.get("topic_id"),
                )
            )

    index_dir = root / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index"
    state_dir = root / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state"
    index_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    file_index_path = index_dir / "file-index.jsonl"
    with file_index_path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    for entry in entries:
        topic_key = entry["topic_id"] or "__unassigned__"
        topic_counter[topic_key]["files"] += 1
        topic_counter[topic_key][entry["zone"]] += 1
        topic_counter[topic_key][entry["registry_status"]] += 1

    topic_summary = {
        "version": "1.0",
        "generated_at": scanned_at,
        "total_files": len(entries),
        "topics": [
            {
                "topic_id": topic_id,
                "file_count": counts["files"],
                "zone_counts": {key: value for key, value in counts.items() if key not in {"files", "registered", "unregistered", "registry_missing_file", "registry_path_duplicate", "layer_mismatch"}},
                "registry_counts": {
                    key: counts[key]
                    for key in ("registered", "unregistered", "registry_missing_file", "registry_path_duplicate", "layer_mismatch")
                    if counts[key]
                },
            }
            for topic_id, counts in sorted(topic_counter.items())
        ],
    }
    dump_json(index_dir / "topic-summary.json", topic_summary)

    findings_payload = {
        "version": "1.0",
        "generated_at": scanned_at,
        "items": findings,
    }
    dump_json(index_dir / "findings.json", findings_payload)

    report = report_path(root, now)
    report.parent.mkdir(parents=True, exist_ok=True)
    finding_counts = Counter(item["finding_type"] for item in findings)
    top_lines = "\n".join(f"- `{key}`: {value}" for key, value in sorted(finding_counts.items())) or "- none"
    sample_findings = "\n".join(
        f"- `{item['finding_type']}` `{item['path']}`: {item['summary']}" for item in findings[:20]
    ) or "- none"
    report.write_text(
        "\n".join(
            [
                "# DBMS Index Audit Report",
                "",
                f"- Run time: {scanned_at}",
                "- Actor: db-admin-agent",
                "- Task type: index_rebuild",
                "- Risk level: L1-L2",
                f"- Total scanned files: {len(entries)}",
                f"- Total findings: {len(findings)}",
                "",
                "## Finding Counts",
                "",
                top_lines,
                "",
                "## Sample Findings",
                "",
                sample_findings,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    state_payload = {
        "version": "1.0",
        "last_index_run": scanned_at,
        "last_actor": "db-admin-agent",
        "last_task_type": "index_rebuild",
        "last_report_path": normalized(report, root),
        "last_status": "complete-with-findings" if findings else "complete-clean",
        "total_files": len(entries),
        "total_findings": len(findings),
    }
    dump_json(state_dir / "last-index-run.json", state_payload)

    ledger_entry = {
        "timestamp": scanned_at,
        "actor": "db-admin-agent",
        "operation": "index_rebuild",
        "target_path": "01-Workflow/Knowledge-Governance/DBMS/index",
        "kb_id": "kb.system.dbms.materialized-index",
        "topic_id": choose_control_topic(topics),
        "layer": "system",
        "summary": f"Rebuilt DBMS materialized index for {len(entries)} files with {len(findings)} findings.",
        "registry_updated": False,
    }
    append_jsonl(ledger_path, ledger_entry)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild the DBMS materialized file index for a governed data vault.")
    parser.add_argument("target_vault", help="Path to the governed data vault")
    args = parser.parse_args()
    rebuild_index(Path(args.target_vault).resolve())
    print(f"DBMS_INDEX_REBUILT\t{Path(args.target_vault).resolve()}")


if __name__ == "__main__":
    main()
