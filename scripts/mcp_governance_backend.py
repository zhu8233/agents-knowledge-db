from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from mcp_access import evaluate_access, load_json
from promotion_queue import apply_promotion_proposal, create_promotion_proposal, list_promotion_queue, review_promotion_proposal
from proposal_store import get_proposal, list_proposals
from registry_updates import apply_registry_update_with_proposal, propose_registry_update
from snapshot_upgrade import (
    apply_snapshot_upgrade_with_proposal,
    current_snapshot_apply_context,
    request_snapshot_review,
    review_snapshot_upgrade,
)
from vault_content_ops import append_markdown, check_artifacts, list_paths, read_markdown, scan_curation_gaps, search_markdown, upsert_markdown


DEFAULT_PAGE_LIMIT = 20
APPROVAL_INPUT_SCHEMA = {
    "type": "object",
    "required": ["approved_by", "approved_at", "evidence"],
    "properties": {
        "approved_by": {"type": "string"},
        "approved_at": {"type": "string"},
        "evidence": {"type": "string"},
        "snapshot_ref": {"type": "string"},
        "compatibility_ref": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}
SNAPSHOT_APPROVAL_INPUT_SCHEMA = {
    "type": "object",
    "required": ["approved_by", "approved_at", "evidence", "snapshot_ref", "compatibility_ref"],
    "properties": {
        "approved_by": {"type": "string"},
        "approved_at": {"type": "string"},
        "evidence": {"type": "string"},
        "snapshot_ref": {"type": "string"},
        "compatibility_ref": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

SERVER_INFO = {
    "name": "agents-knowledge-db",
    "version": "0.1.0",
}

SUPPORTED_PROTOCOL_VERSIONS = ["2025-11-25"]


class GovernanceBackend:
    def __init__(self, vault_root: Path, *, subject_id: str, auth_mode: str) -> None:
        # INVARIANT: vault_root must be stored in its resolved (canonical) form.
        # Methods like _safe_resolve_file and _latest_index_report_path compare
        # resolved file paths against self.vault_root using relative_to(). On macOS,
        # /var is a symlink to /private/var, so an unresolved vault_root path like
        # /var/folders/... would never match a resolved file path like
        # /private/var/folders/..., silently breaking the escape boundary checks.
        self.vault_root = Path(vault_root).resolve()
        self.subject_id = subject_id
        self.auth_mode = auth_mode

    def _registry(self) -> dict:
        return self._safe_load_json(self.vault_root / ".knowledge-registry" / "vault-registry.json")

    def _agent_roster(self) -> dict:
        return self._safe_load_json(self.vault_root / ".knowledge-registry" / "agent-roster.json")

    def _findings(self) -> dict:
        return self._safe_load_json(self.vault_root / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "findings.json")

    def _dbms_index_dir(self) -> Path:
        return self.vault_root / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index"

    def _dbms_state_dir(self) -> Path:
        return self.vault_root / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state"

    def _dbms_reports_dir(self) -> Path:
        return self.vault_root / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "reports"

    def _script_path(self, script_name: str) -> Path:
        return Path(__file__).resolve().parent / script_name

    def _safe_resolve_file(self, path: Path) -> Path:
        source_path = Path(path)
        if not source_path.is_absolute():
            source_path = self.vault_root / source_path
        if source_path.exists() and source_path.is_symlink():
            raise ValueError("resource path must not be a symlink")
        resolved_path = source_path.resolve()
        try:
            resolved_path.relative_to(self.vault_root)
        except ValueError as exc:
            raise ValueError("resource path escapes the vault root") from exc
        if not source_path.exists() or not resolved_path.exists() or not resolved_path.is_file():
            raise ValueError("resource path must point to an existing file")
        return resolved_path

    def _safe_load_json(self, path: Path) -> dict:
        return load_json(self._safe_resolve_file(path))

    def _safe_read_text(self, path: Path) -> str:
        return self._safe_resolve_file(path).read_text(encoding="utf-8")

    def _load_json_if_exists(self, path: Path) -> dict | None:
        source_path = Path(path)
        if not source_path.is_absolute():
            source_path = self.vault_root / source_path
        return self._safe_load_json(source_path) if source_path.exists() else None

    def _latest_index_report_path(self) -> Path | None:
        index_state = self._load_json_if_exists(self._dbms_state_dir() / "last-index-run.json")
        reports_root = self._dbms_reports_dir().resolve()
        def is_safe_index_report(source_path: Path, resolved_path: Path) -> bool:
            if not source_path.exists() or not source_path.is_file() or source_path.is_symlink():
                return False
            try:
                resolved_path.relative_to(reports_root)
            except ValueError:
                return False
            return resolved_path.name.endswith("index-audit-report.md")

        if index_state is not None:
            last_report_path = index_state.get("last_report_path")
            if isinstance(last_report_path, str) and last_report_path:
                source_path = self.vault_root / last_report_path
                candidate = source_path.resolve()
                if candidate.exists() and is_safe_index_report(source_path, candidate):
                    return candidate

        report_candidates = [
            path for path in self._dbms_reports_dir().glob("*index-audit-report.md")
            if path.exists() and is_safe_index_report(path, path.resolve())
        ]
        if not report_candidates:
            return None
        return max(report_candidates, key=lambda path: path.stat().st_mtime)

    def _effective_role(self) -> str | None:
        decision = self._evaluate("governance_whoami", "L0", "system")
        if decision.get("decision") != "allow":
            return None
        return decision.get("effective_role")

    def _resource_by_uri(self, uri: str) -> dict | None:
        for resource in self._resource_catalog():
            if resource["uri"] == uri:
                return resource
        return None

    def _allowed_resource(self, resource: dict) -> bool:
        role = self._effective_role()
        if role is None:
            return False
        return role in resource.get("allowed_roles", [])

    def _resource_catalog(self) -> list[dict]:
        return [
            {
                "uri": "governance://rules/root",
                "name": "Root Rules",
                "description": "Human-readable root operating rules for the governed vault.",
                "mimeType": "text/markdown",
                "allowed_roles": ["vault-user", "vault-maintainer", "system-maintainer"],
            },
            {
                "uri": "governance://registry/vault",
                "name": "Vault Registry",
                "description": "Machine-readable topic and object registry source of truth.",
                "mimeType": "application/json",
                "allowed_roles": ["vault-user", "vault-maintainer", "system-maintainer"],
            },
            {
                "uri": "governance://registry/agent-roster",
                "name": "Agent Roster",
                "description": "Machine-readable agent role and layer authority registry.",
                "mimeType": "application/json",
                "allowed_roles": ["vault-maintainer", "system-maintainer"],
            },
            {
                "uri": "governance://registry/governance-proposals",
                "name": "Governance Proposals",
                "description": "Unified proposal store for registry, promotion, and snapshot workflows.",
                "mimeType": "application/json",
                "allowed_roles": ["vault-maintainer", "system-maintainer"],
            },
            {
                "uri": "governance://registry/promotion-queue",
                "name": "Promotion Queue",
                "description": "Promotion queue state for canonical promotion workflow.",
                "mimeType": "application/json",
                "allowed_roles": ["vault-maintainer", "system-maintainer"],
            },
            {
                "uri": "governance://local/compatibility-status",
                "name": "Compatibility Status",
                "description": "Local snapshot compatibility state.",
                "mimeType": "application/json",
                "allowed_roles": ["vault-maintainer", "system-maintainer"],
            },
            {
                "uri": "governance://snapshot/version",
                "name": "Snapshot Version",
                "description": "Current installed system snapshot version metadata.",
                "mimeType": "application/json",
                "allowed_roles": ["vault-maintainer", "system-maintainer"],
            },
            {
                "uri": "governance://registry/change-ledger",
                "name": "Change Ledger",
                "description": "Append-only governance change ledger.",
                "mimeType": "application/x-ndjson",
                "allowed_roles": ["vault-maintainer", "system-maintainer"],
            },
            {
                "uri": "governance://dbms/index/findings",
                "name": "DBMS Findings",
                "description": "Derived audit findings from the DBMS materialized index.",
                "mimeType": "application/json",
                "allowed_roles": ["vault-user", "vault-maintainer", "system-maintainer"],
            },
            {
                "uri": "governance://dbms/index/file-index",
                "name": "DBMS File Index",
                "description": "Derived whole-vault file coverage index for governance audit and scan tasks.",
                "mimeType": "application/x-ndjson",
                "allowed_roles": ["vault-user", "vault-maintainer", "system-maintainer"],
            },
            {
                "uri": "governance://dbms/index/topic-summary",
                "name": "DBMS Topic Summary",
                "description": "Derived topic-level summary of indexed files and registry coverage.",
                "mimeType": "application/json",
                "allowed_roles": ["vault-user", "vault-maintainer", "system-maintainer"],
            },
            {
                "uri": "governance://dbms/state/last-index-run",
                "name": "Last DBMS Index Run",
                "description": "Most recent DBMS index rebuild state and latest audit report pointer.",
                "mimeType": "application/json",
                "allowed_roles": ["vault-user", "vault-maintainer", "system-maintainer"],
            },
            {
                "uri": "governance://dbms/reports/latest-index-audit",
                "name": "Latest DBMS Index Audit",
                "description": "Latest DBMS index audit report markdown.",
                "mimeType": "text/markdown",
                "allowed_roles": ["vault-user", "vault-maintainer", "system-maintainer"],
            },
        ]

    def _tool_catalog(self) -> list[dict]:
        return [
            {
                "name": "governance_search_topics",
                "title": "Search Topics",
                "description": "Search the vault registry by topic title or alias.",
                "risk_level": "L0",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": DEFAULT_PAGE_LIMIT, "minimum": 1, "maximum": 100},
                        "offset": {"type": "integer", "default": 0, "minimum": 0},
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "total": {"type": "integer"},
                        "count": {"type": "integer"},
                        "offset": {"type": "integer"},
                        "has_more": {"type": "boolean"},
                        "next_offset": {"type": ["integer", "null"]},
                        "matches": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "topic_id": {"type": "string"},
                                    "title": {"type": "string"},
                                    "status": {"type": "string"},
                                    "canonical_home": {"type": ["string", "null"]},
                                },
                            },
                        },
                    },
                },
            },
            {
                "name": "governance_get_topic_context",
                "title": "Get Topic Context",
                "description": "Return registry, object, and finding context for a topic.",
                "risk_level": "L0",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["topic_id"],
                    "properties": {"topic_id": {"type": "string"}},
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "object"},
                        "objects": {"type": "array", "items": {"type": "object"}},
                        "findings": {"type": "array", "items": {"type": "object"}},
                        "objectCount": {"type": "integer"},
                        "findingCount": {"type": "integer"},
                        "source_of_truth": {"type": "string"},
                        "derived_state_used": {"type": "string"},
                    },
                },
            },
            {
                "name": "governance_list_topic_findings",
                "title": "List Topic Findings",
                "description": "List DBMS findings for a topic or the whole vault.",
                "risk_level": "L0",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic_id": {"type": "string"},
                        "limit": {"type": "integer", "default": DEFAULT_PAGE_LIMIT, "minimum": 1, "maximum": 100},
                        "offset": {"type": "integer", "default": 0, "minimum": 0},
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "topic_id": {"type": ["string", "null"]},
                        "total": {"type": "integer"},
                        "count": {"type": "integer"},
                        "offset": {"type": "integer"},
                        "has_more": {"type": "boolean"},
                        "next_offset": {"type": ["integer", "null"]},
                        "items": {"type": "array", "items": {"type": "object"}},
                    },
                },
            },
            {
                "name": "governance_validate_data_repo",
                "title": "Validate Data Repo",
                "description": "Run the governed data repository validator against the current vault.",
                "risk_level": "L1",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "exitCode": {"type": "integer"},
                        "stdout": {"type": "string"},
                        "stderr": {"type": "string"},
                    },
                },
            },
            {
                "name": "vault_list_paths",
                "title": "List Vault Paths",
                "description": "List allowed vault-relative paths without exposing raw filesystem access.",
                "risk_level": "L0",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["root"],
                    "properties": {
                        "root": {"type": "string"},
                        "glob": {"type": "string", "default": "*"},
                        "recursive": {"type": "boolean", "default": False},
                        "include_dirs": {"type": "boolean", "default": False},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "root": {"type": "string"},
                        "paths": {"type": "array", "items": {"type": "string"}},
                        "count": {"type": "integer"},
                        "truncated": {"type": "boolean"},
                    },
                },
            },
            {
                "name": "vault_read_markdown",
                "title": "Read Vault Markdown",
                "description": "Read an allowed vault Markdown file with optional heading or date filtering.",
                "risk_level": "L0",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string"},
                        "heading": {"type": "string"},
                        "date_filter": {"type": "string"},
                        "max_chars": {"type": "integer", "minimum": 1},
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "hash": {"type": "string"},
                        "found": {"type": "boolean"},
                        "content": {"type": "string"},
                        "section": {"type": ["string", "null"]},
                        "truncated": {"type": "boolean"},
                    },
                },
            },
            {
                "name": "vault_search_markdown",
                "title": "Search Vault Markdown",
                "description": "Search allowed vault Markdown paths or globs and return matching snippets.",
                "risk_level": "L0",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "paths": {"type": "array", "items": {"type": "string"}},
                        "glob": {"type": "string"},
                        "query": {"type": "string"},
                        "regex": {"type": "string"},
                        "date_filter": {"type": "string"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
                        "max_chars_per_hit": {"type": "integer", "minimum": 1, "maximum": 500},
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer"},
                        "matches": {"type": "array", "items": {"type": "object"}},
                    },
                },
            },
            {
                "name": "vault_check_artifacts",
                "title": "Check Vault Artifacts",
                "description": "Validate expected governed vault artifacts by glob, date, and content checks.",
                "risk_level": "L0",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["artifacts"],
                    "properties": {
                        "artifacts": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["path_glob"],
                                "properties": {
                                    "path_glob": {"type": "string"},
                                    "required_date": {"type": "string"},
                                    "content_contains": {"type": "string"},
                                    "must_exist": {"type": "boolean"},
                                },
                                "additionalProperties": False,
                            },
                        },
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "results": {"type": "array", "items": {"type": "object"}},
                        "missing": {"type": "integer"},
                        "content_failures": {"type": "integer"},
                    },
                },
            },
            {
                "name": "vault_scan_curation_gaps",
                "title": "Scan Curation Gaps",
                "description": "Return candidate topics whose intake coverage suggests missing curation artifacts.",
                "risk_level": "L1",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "min_intake_files": {"type": "integer", "minimum": 1, "default": 5},
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer"},
                        "items": {"type": "array", "items": {"type": "object"}},
                    },
                },
            },
            {
                "name": "vault_upsert_markdown",
                "title": "Upsert Vault Markdown",
                "description": "Create, replace, or upsert governed Markdown content in approved vault write roots.",
                "risk_level": "L2",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["path", "content", "mode"],
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "mode": {"type": "string", "enum": ["create", "replace", "upsert"]},
                        "expected_hash": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "operation": {"type": "string"},
                        "old_hash": {"type": ["string", "null"]},
                        "new_hash": {"type": "string"},
                        "actor": {"type": "string"},
                        "bytes_written": {"type": "integer"},
                    },
                },
            },
            {
                "name": "vault_append_markdown",
                "title": "Append Vault Markdown",
                "description": "Append governed Markdown content at EOF or within a heading or date section.",
                "risk_level": "L2",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["path", "content", "target"],
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "target": {"type": "string", "enum": ["eof", "heading", "date_section"]},
                        "heading": {"type": "string"},
                        "date": {"type": "string"},
                        "create_if_missing": {"type": "boolean", "default": False},
                        "expected_hash": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "operation": {"type": "string"},
                        "old_hash": {"type": ["string", "null"]},
                        "new_hash": {"type": "string"},
                        "actor": {"type": "string"},
                        "created_file": {"type": "boolean"},
                        "created_section": {"type": "boolean"},
                    },
                },
            },
            {
                "name": "governance_rebuild_dbms_index",
                "title": "Rebuild DBMS Index",
                "description": "Rebuild the derived DBMS materialized index, state, and latest audit report.",
                "risk_level": "L2",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "exitCode": {"type": "integer"},
                        "stdout": {"type": "string"},
                        "stderr": {"type": "string"},
                        "reportPath": {"type": ["string", "null"]},
                        "state": {"type": ["object", "null"]},
                    },
                },
            },
            {
                "name": "governance_reconcile_dbms_state",
                "title": "Reconcile DBMS State",
                "description": "Repair derived DBMS state and report pointers after index or report drift.",
                "risk_level": "L2",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "exitCode": {"type": "integer"},
                        "stdout": {"type": "string"},
                        "stderr": {"type": "string"},
                        "reportPath": {"type": ["string", "null"]},
                        "indexState": {"type": ["object", "null"]},
                        "dbmsState": {"type": ["object", "null"]},
                    },
                },
            },
            {
                "name": "governance_whoami",
                "title": "Who Am I",
                "description": "Return the current subject identity, effective role, and visible governance tools.",
                "risk_level": "L0",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "subjectId": {"type": "string"},
                        "authMode": {"type": "string"},
                        "mappedAgentId": {"type": ["string", "null"]},
                        "effectiveRole": {"type": "string"},
                        "visibleTools": {"type": "array", "items": {"type": "string"}},
                        "toolCount": {"type": "integer"},
                    },
                },
            },
            {
                "name": "governance_propose_registry_update",
                "title": "Propose Registry Update",
                "description": "Create and persist a structured registry update proposal without mutating the registry.",
                "risk_level": "L1",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["target_kind", "operation", "summary"],
                    "properties": {
                        "target_kind": {"type": "string", "enum": ["topic", "object", "adapter"]},
                        "operation": {"type": "string"},
                        "summary": {"type": "string"},
                        "topic_id": {"type": "string"},
                        "path": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "proposal": {"type": "object"},
                    },
                },
            },
            {
                "name": "governance_create_promotion_proposal",
                "title": "Create Promotion Proposal",
                "description": "Append a proposal to the promotion queue and record it in the ledger.",
                "risk_level": "L1",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["topic_id", "source_path", "candidate_path", "summary"],
                    "properties": {
                        "topic_id": {"type": "string"},
                        "source_path": {"type": "string"},
                        "candidate_path": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "proposal": {"type": "object"},
                    },
                },
            },
            {
                "name": "governance_list_promotion_queue",
                "title": "List Promotion Queue",
                "description": "Read the current promotion queue.",
                "risk_level": "L0",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": DEFAULT_PAGE_LIMIT, "minimum": 1, "maximum": 100},
                        "offset": {"type": "integer", "default": 0, "minimum": 0},
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"type": "object"}},
                        "total": {"type": "integer"},
                        "count": {"type": "integer"},
                        "offset": {"type": "integer"},
                        "has_more": {"type": "boolean"},
                        "next_offset": {"type": ["integer", "null"]},
                        "lastUpdated": {"type": ["string", "null"]},
                    },
                },
            },
            {
                "name": "governance_apply_registry_update",
                "title": "Apply Registry Update",
                "description": "Apply a registry upsert and append a change-ledger entry.",
                "risk_level": "L2",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["target_kind", "operation", "summary", "entry"],
                    "properties": {
                        "target_kind": {"type": "string", "enum": ["topic", "object", "adapter"]},
                        "operation": {"type": "string"},
                        "summary": {"type": "string"},
                        "proposal_id": {"type": "string"},
                        "entry": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "targetKind": {"type": "string"},
                        "operation": {"type": "string"},
                        "created": {"type": "boolean"},
                        "updated": {"type": "boolean"},
                        "ledgerEntry": {"type": "object"},
                        "updatedTopic": {"type": "object"},
                        "updatedObject": {"type": "object"},
                        "updatedAdapter": {"type": "object"},
                    },
                },
            },
            {
                "name": "governance_review_promotion_proposal",
                "title": "Review Promotion Proposal",
                "description": "Approve or reject a queued promotion proposal.",
                "risk_level": "L3",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["proposal_id", "decision", "summary"],
                    "properties": {
                        "proposal_id": {"type": "string"},
                        "decision": {"type": "string", "enum": ["approve", "reject"]},
                        "summary": {"type": "string"},
                        "approval": APPROVAL_INPUT_SCHEMA,
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "proposal": {"type": "object"},
                    },
                },
            },
            {
                "name": "governance_apply_promotion_proposal",
                "title": "Apply Promotion Proposal",
                "description": "Apply an approved promotion proposal to registry canonical placement.",
                "risk_level": "L3",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["proposal_id", "summary"],
                    "properties": {
                        "proposal_id": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "proposal": {"type": "object"},
                        "updatedTopic": {"type": "object"},
                    },
                },
            },
            {
                "name": "governance_evaluate_access",
                "title": "Evaluate Access",
                "description": "Evaluate the current subject against a requested governance action.",
                "risk_level": "L0",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["tool", "risk_level", "target_layer"],
                    "properties": {
                        "tool": {"type": "string"},
                        "risk_level": {"type": "string", "enum": ["L0", "L1", "L2", "L3", "L4"]},
                        "target_layer": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "decision": {"type": "string"},
                        "tool": {"type": "string"},
                        "risk_level": {"type": "string"},
                        "target_layer": {"type": "string"},
                        "effective_role": {"type": ["string", "null"]},
                        "mapped_agent_id": {"type": ["string", "null"]},
                    },
                },
            },
            {
                "name": "governance_request_snapshot_review",
                "title": "Request Snapshot Review",
                "description": "Create and persist a proposal for snapshot upgrade review.",
                "risk_level": "L1",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["summary"],
                    "properties": {"summary": {"type": "string"}},
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "proposal": {"type": "object"},
                    },
                },
            },
            {
                "name": "governance_review_snapshot_upgrade",
                "title": "Review Snapshot Upgrade",
                "description": "Compare the active snapshot with local compatibility state.",
                "risk_level": "L1",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "upgradeAvailable": {"type": "boolean"},
                        "snapshotRef": {"type": ["string", "null"]},
                        "compatibilityRef": {"type": ["string", "null"]},
                        "snapshotVersion": {"type": "object"},
                        "compatibilityStatus": {"type": "object"},
                    },
                },
            },
            {
                "name": "governance_apply_snapshot_upgrade",
                "title": "Apply Snapshot Upgrade",
                "description": "Sync the latest system snapshot into the vault and update compatibility state.",
                "risk_level": "L4",
                "target_layer": "system",
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["summary"],
                    "properties": {
                        "summary": {"type": "string"},
                        "proposal_id": {"type": "string"},
                        "approval": SNAPSHOT_APPROVAL_INPUT_SCHEMA,
                    },
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "snapshotRef": {"type": ["string", "null"]},
                        "status": {"type": "string"},
                        "compatibilityStatus": {"type": "object"},
                        "ledgerEntry": {"type": "object"},
                        "governanceProposal": {"type": "object"},
                    },
                },
            },
        ]

    def _paginate(self, items: list[dict], limit: int | None, offset: int | None) -> dict:
        limit = limit if limit is not None else DEFAULT_PAGE_LIMIT
        offset = offset if offset is not None else 0

        if not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if not isinstance(offset, int):
            raise ValueError("offset must be an integer")
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        total = len(items)
        paginated = items[offset:offset + limit]
        count = len(paginated)
        has_more = total > offset + count
        next_offset = offset + count if has_more else None
        return {
            "total": total,
            "count": count,
            "offset": offset,
            "has_more": has_more,
            "next_offset": next_offset,
            "items": paginated,
        }

    def _evaluate(self, tool_name: str, risk_level: str, target_layer: str) -> dict:
        return evaluate_access(
            self.vault_root,
            self.subject_id,
            self.auth_mode,
            tool_name,
            risk_level,
            target_layer,
        )

    def _allowed_tool(self, tool: dict) -> bool:
        decision = self._evaluate(tool["name"], tool["risk_level"], tool["target_layer"])
        return decision.get("decision") == "allow"

    def _validate_explicit_approval(self, approval: object, *, snapshot_review: dict | None = None) -> dict:
        if not isinstance(approval, dict):
            raise ValueError("approval must be an object")

        normalized = {}
        missing = []
        required_fields = ["approved_by", "approved_at", "evidence"]
        if snapshot_review is not None:
            required_fields.extend(["snapshot_ref", "compatibility_ref"])
        for field in required_fields:
            value = approval.get(field)
            if field == "compatibility_ref":
                if value is None:
                    normalized[field] = None
                    continue
                if not isinstance(value, str) or not value.strip():
                    missing.append(field)
                    continue
                normalized[field] = value.strip()
                continue
            if not isinstance(value, str) or not value.strip():
                missing.append(field)
                continue
            normalized[field] = value.strip()

        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"approval is missing required non-empty field(s): {joined}")
        if normalized["approved_by"] != self.subject_id:
            raise ValueError("approval.approved_by must match the authenticated subject")
        try:
            datetime.fromisoformat(normalized["approved_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("approval.approved_at must be a valid ISO-8601 timestamp") from exc
        if snapshot_review is not None:
            if normalized["snapshot_ref"] != snapshot_review.get("snapshotRef"):
                raise ValueError("approval.snapshot_ref must match the current snapshot review")
            if normalized["compatibility_ref"] != snapshot_review.get("compatibilityRef"):
                raise ValueError("approval.compatibility_ref must match the current snapshot review")
        return normalized

    def _approval_gate_error(
        self,
        name: str,
        decision: dict,
        *,
        detail: str,
        proposal: dict | None = None,
        required_evidence: list[str] | None = None,
    ) -> dict:
        if proposal is not None:
            detail = (
                f"{detail} proposal `{proposal['proposal_id']}` is currently `{proposal.get('status')}`."
            )

        structured = {
            **decision,
            "tool": name,
            "required_evidence": required_evidence or ["approved proposal", "explicit approval evidence"],
        }
        if proposal is not None:
            structured["proposal_status"] = proposal.get("status")
            structured["proposal_type"] = proposal.get("proposal_type")

        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Tool `{name}` requires additional approval. {detail}"}],
            "structuredContent": structured,
        }

    def _current_snapshot_review(self) -> dict:
        return current_snapshot_apply_context(self.vault_root)

    def _snapshot_proposal_matches_current_review(self, proposal: dict) -> bool:
        details = proposal.get("details") or {}
        current_review = self._current_snapshot_review()
        return (
            details.get("snapshotRef") == current_review.get("snapshotRef")
            and details.get("compatibilityRef") == current_review.get("compatibilityRef")
        )

    def _has_required_approval(self, name: str, decision: dict, arguments: dict) -> dict | None:
        if name not in {"governance_review_promotion_proposal", "governance_apply_snapshot_upgrade"}:
            return None
        if not decision.get("requires_approval") or decision.get("risk_level") not in {"L3", "L4"}:
            return None

        snapshot_review = self._current_snapshot_review() if name == "governance_apply_snapshot_upgrade" else None
        if snapshot_review is not None:
            arguments["_validated_snapshot_context"] = snapshot_review
        approval = arguments.get("approval")
        if approval is not None:
            arguments["approval"] = self._validate_explicit_approval(approval, snapshot_review=snapshot_review)

        proposal = None
        proposal_id = arguments.get("proposal_id")
        if isinstance(proposal_id, str) and proposal_id.strip():
            normalized_proposal_id = proposal_id.strip()
            arguments["proposal_id"] = normalized_proposal_id
            proposal = get_proposal(self.vault_root, normalized_proposal_id)

        if name == "governance_review_promotion_proposal":
            if approval is not None:
                return None
            return self._approval_gate_error(
                name,
                decision,
                detail="Provide explicit approval evidence.",
                proposal=proposal,
                required_evidence=["explicit approval evidence"],
            )

        if proposal is not None:
            if proposal.get("proposal_type") != "snapshot_upgrade":
                return self._approval_gate_error(
                    name,
                    decision,
                    detail="Provide an approved proposal or explicit approval evidence for `snapshot_upgrade`.",
                    proposal=proposal,
                )
            if not self._snapshot_proposal_matches_current_review(proposal):
                return self._approval_gate_error(
                    name,
                    decision,
                    detail="Provide an approved proposal or explicit approval evidence for the current `snapshot_upgrade`; the supplied proposal does not match the current snapshot review.",
                    proposal=proposal,
                )
            if proposal.get("status") in {"rejected", "applied"}:
                return self._approval_gate_error(
                    name,
                    decision,
                    detail="Provide an approved proposal or explicit approval evidence for the current `snapshot_upgrade`; the supplied proposal is not in a usable state.",
                    proposal=proposal,
                )
            if proposal.get("status") == "approved":
                return None
            if approval is not None:
                return None
            return self._approval_gate_error(
                name,
                decision,
                detail="Provide an approved proposal or explicit approval evidence for `snapshot_upgrade`.",
                proposal=proposal,
            )

        if approval is not None:
            return None

        return self._approval_gate_error(
            name,
            decision,
            detail="Provide an approved proposal or explicit approval evidence for `snapshot_upgrade`.",
            proposal=proposal,
        )

    def list_tools(self) -> list[dict]:
        return [tool for tool in self._tool_catalog() if self._allowed_tool(tool)]

    def list_resources(self) -> list[dict]:
        return [resource for resource in self._resource_catalog() if self._allowed_resource(resource)]

    def read_resource(self, uri: str) -> dict:
        resource_meta = self._resource_by_uri(uri)
        if resource_meta is None:
            raise ValueError(f"Unknown resource URI: {uri}")
        if not self._allowed_resource(resource_meta):
            raise ValueError(f"Access denied for resource `{uri}`")
        if uri == "governance://rules/root":
            text = self._safe_read_text(self.vault_root / "RULES.md")
            return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": text}]}
        if uri == "governance://registry/vault":
            text = json.dumps(self._registry(), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        if uri == "governance://registry/agent-roster":
            text = json.dumps(self._agent_roster(), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        if uri == "governance://registry/governance-proposals":
            text = json.dumps(self._safe_load_json(self.vault_root / ".knowledge-registry" / "governance-proposals.json"), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        if uri == "governance://registry/promotion-queue":
            text = json.dumps(self._safe_load_json(self.vault_root / ".knowledge-registry" / "promotion-queue.json"), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        if uri == "governance://local/compatibility-status":
            text = json.dumps(self._safe_load_json(self.vault_root / "LocalOverrides" / "compatibility-status.json"), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        if uri == "governance://snapshot/version":
            text = json.dumps(self._safe_load_json(self.vault_root / ".dbms-system" / "version.json"), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        if uri == "governance://registry/change-ledger":
            text = self._safe_read_text(self.vault_root / ".knowledge-registry" / "change-ledger.jsonl")
            return {"contents": [{"uri": uri, "mimeType": "application/x-ndjson", "text": text}]}
        if uri == "governance://dbms/index/findings":
            text = json.dumps(self._findings(), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        if uri == "governance://dbms/index/file-index":
            text = self._safe_read_text(self._dbms_index_dir() / "file-index.jsonl")
            return {"contents": [{"uri": uri, "mimeType": "application/x-ndjson", "text": text}]}
        if uri == "governance://dbms/index/topic-summary":
            text = json.dumps(self._safe_load_json(self._dbms_index_dir() / "topic-summary.json"), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        if uri == "governance://dbms/state/last-index-run":
            text = json.dumps(self._safe_load_json(self._dbms_state_dir() / "last-index-run.json"), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        if uri == "governance://dbms/reports/latest-index-audit":
            report_path = self._latest_index_report_path()
            if report_path is None:
                text = "# DBMS Index Audit Report\n\nNo DBMS index audit report is available yet.\n"
            else:
                text = report_path.read_text(encoding="utf-8")
            return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": text}]}
        raise ValueError(f"Unknown resource URI: {uri}")

    def list_prompts(self) -> list[dict]:
        return [
            {
                "name": "onboard_agent_to_vault",
                "description": "Guide an agent through the governed vault onboarding sequence.",
                "arguments": [],
            },
            {
                "name": "review_topic_health",
                "description": "Review the health of a specific topic using registry and findings context.",
                "arguments": [
                    {
                        "name": "topic_id",
                        "description": "Topic ID to review",
                        "required": True,
                    }
                ],
            },
            {
                "name": "prepare_registry_repair",
                "description": "Guide an operator through registry repair using findings and source-of-truth checks.",
                "arguments": [
                    {"name": "topic_id", "description": "Optional topic ID to narrow the repair scope", "required": False}
                ],
            },
            {
                "name": "governance_review_snapshot_upgrade",
                "description": "Guide a system maintainer through snapshot upgrade review and approval.",
                "arguments": [],
            },
            {
                "name": "governance_review_promotion_proposal",
                "description": "Guide a reviewer through promotion proposal approval criteria.",
                "arguments": [
                    {"name": "proposal_id", "description": "Promotion proposal ID", "required": True}
                ],
            },
        ]

    def get_prompt(self, name: str, arguments: dict) -> dict:
        if name == "onboard_agent_to_vault":
            text = (
                "First read `RULES.md`, then inspect `.knowledge-registry/vault-registry.json`, "
                "resolve your target topic and target layer, check `agent-roster.json`, "
                "and only then choose the appropriate workflow."
            )
            return {"messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
        if name == "review_topic_health":
            topic_id = arguments.get("topic_id")
            if not topic_id:
                raise ValueError("topic_id is required")
            text = (
                f"Review topic `{topic_id}` by reading its registry entry, matching governed objects, "
                "and any DBMS findings before suggesting remediation."
            )
            return {"messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
        if name == "prepare_registry_repair":
            topic_id = arguments.get("topic_id")
            suffix = f" for topic `{topic_id}`" if topic_id else ""
            text = (
                f"Review registry drift{suffix} by comparing registry facts, DBMS findings, and current vault paths "
                "before proposing any registry update."
            )
            return {"messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
        if name == "governance_review_snapshot_upgrade":
            text = (
                "Review the installed snapshot version, local compatibility status, and any open snapshot proposal "
                "before deciding whether to apply the latest system snapshot."
            )
            return {"messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
        if name == "governance_review_promotion_proposal":
            proposal_id = arguments.get("proposal_id")
            if not proposal_id:
                raise ValueError("proposal_id is required")
            text = (
                f"Review promotion proposal `{proposal_id}` against promotion criteria, source lineage, "
                "and canonical placement safety before approving or rejecting it."
            )
            return {"messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
        raise ValueError(f"Unknown prompt: {name}")

    def call_tool(self, name: str, arguments: dict) -> dict:
        catalog = {tool["name"]: tool for tool in self._tool_catalog()}
        if name not in catalog:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                "structuredContent": {"tool": name},
            }

        tool_meta = catalog[name]
        decision = self._evaluate(name, tool_meta["risk_level"], tool_meta["target_layer"])
        if decision.get("decision") != "allow":
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Access denied for tool `{name}`"}],
                "structuredContent": decision,
            }

        handler_name = f"_tool_{name}"
        handler = getattr(self, handler_name)
        try:
            approval_error = self._has_required_approval(name, decision, arguments)
            if approval_error is not None:
                return approval_error
            return handler(arguments)
        except (ValueError, RuntimeError) as exc:
            return {
                "isError": True,
                "content": [{"type": "text", "text": str(exc)}],
                "structuredContent": {"tool": name},
            }

    def _tool_governance_search_topics(self, arguments: dict) -> dict:
        query = arguments["query"].strip().lower()
        limit = arguments.get("limit")
        offset = arguments.get("offset")
        registry = self._registry()
        matches = []
        for topic in registry.get("topics", []):
            haystacks = [topic.get("title", "")] + topic.get("aliases", [])
            if any(query in value.lower() for value in haystacks):
                matches.append(
                    {
                        "topic_id": topic["topic_id"],
                        "title": topic["title"],
                        "status": topic["status"],
                        "canonical_home": topic.get("canonical_home"),
                    }
                )
        page = self._paginate(matches, limit, offset)
        text = f"Matched {page['total']} topic(s) for query `{arguments['query']}`; showing {page['count']}."
        return {
            "isError": False,
            "content": [{"type": "text", "text": text}],
            "structuredContent": {
                "query": arguments["query"],
                "total": page["total"],
                "count": page["count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "next_offset": page["next_offset"],
                "matches": page["items"],
            },
        }

    def _tool_governance_get_topic_context(self, arguments: dict) -> dict:
        topic_id = arguments["topic_id"]
        registry = self._registry()
        findings = self._findings().get("items", [])
        topic = next((item for item in registry.get("topics", []) if item.get("topic_id") == topic_id), None)
        if topic is None:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Unknown topic: {topic_id}"}],
                "structuredContent": {"topic_id": topic_id},
            }
        objects = [item for item in registry.get("objects", []) if item.get("topic_id") == topic_id]
        topic_findings = [item for item in findings if item.get("topic_id") == topic_id]
        text = (
            f"Topic `{topic_id}` has {len(objects)} registered object(s) and "
            f"{len(topic_findings)} DBMS finding(s)."
        )
        return {
            "isError": False,
            "content": [{"type": "text", "text": text}],
            "structuredContent": {
                "topic": topic,
                "objects": objects,
                "findings": topic_findings,
                "objectCount": len(objects),
                "findingCount": len(topic_findings),
                "source_of_truth": ".knowledge-registry/vault-registry.json",
                "derived_state_used": "01-Workflow/Knowledge-Governance/DBMS/index/findings.json",
            },
        }

    def _tool_governance_list_topic_findings(self, arguments: dict) -> dict:
        topic_id = arguments.get("topic_id")
        limit = arguments.get("limit")
        offset = arguments.get("offset")
        findings = self._findings().get("items", [])
        if topic_id:
            findings = [item for item in findings if item.get("topic_id") == topic_id]
        page = self._paginate(findings, limit, offset)
        text = f"Returned {page['total']} finding(s); showing {page['count']}."
        return {
            "isError": False,
            "content": [{"type": "text", "text": text}],
            "structuredContent": {
                "topic_id": topic_id,
                "total": page["total"],
                "count": page["count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "next_offset": page["next_offset"],
                "items": page["items"],
            },
        }

    def _tool_governance_validate_data_repo(self, arguments: dict) -> dict:
        result = subprocess.run(
            [sys.executable, str(self._script_path("validate_data_repo.py")), str(self.vault_root)],
            capture_output=True,
            text=True,
            cwd=self.vault_root.parents[0],
        )
        is_error = result.returncode != 0
        text = result.stdout.strip() if result.stdout.strip() else result.stderr.strip()
        return {
            "isError": is_error,
            "content": [{"type": "text", "text": text}],
            "structuredContent": {
                "exitCode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        }

    def _tool_vault_list_paths(self, arguments: dict) -> dict:
        result = list_paths(
            self.vault_root,
            root=arguments["root"],
            recursive=arguments.get("recursive", False),
            glob=arguments.get("glob", "*"),
            include_dirs=arguments.get("include_dirs", False),
            limit=arguments.get("limit", 100),
        )
        return {
            "isError": False,
            "content": [{"type": "text", "text": f"Listed {result['count']} path(s)."}],
            "structuredContent": result,
        }

    def _tool_vault_read_markdown(self, arguments: dict) -> dict:
        result = read_markdown(self.vault_root, **arguments)
        return {
            "isError": False,
            "content": [{"type": "text", "text": f"Read `{result['path']}`."}],
            "structuredContent": result,
        }

    def _tool_vault_search_markdown(self, arguments: dict) -> dict:
        result = search_markdown(self.vault_root, **arguments)
        return {
            "isError": False,
            "content": [{"type": "text", "text": f"Found {result['count']} matching snippet(s)."}],
            "structuredContent": result,
        }

    def _tool_vault_check_artifacts(self, arguments: dict) -> dict:
        result = check_artifacts(self.vault_root, **arguments)
        return {
            "isError": False,
            "content": [{"type": "text", "text": f"Checked {len(result['results'])} artifact spec(s)."}],
            "structuredContent": result,
        }

    def _tool_vault_scan_curation_gaps(self, arguments: dict) -> dict:
        result = scan_curation_gaps(self.vault_root, **arguments)
        return {
            "isError": False,
            "content": [{"type": "text", "text": f"Found {result['count']} curation-gap candidate(s)."}],
            "structuredContent": result,
        }

    def _tool_vault_upsert_markdown(self, arguments: dict) -> dict:
        result = upsert_markdown(
            self.vault_root,
            path=arguments["path"],
            content=arguments["content"],
            mode=arguments["mode"],
            actor=self.subject_id,
            expected_hash=arguments.get("expected_hash"),
        )
        return {
            "isError": False,
            "content": [{"type": "text", "text": f"Updated `{result['path']}` via {result['operation']}."}],
            "structuredContent": result,
        }

    def _tool_vault_append_markdown(self, arguments: dict) -> dict:
        result = append_markdown(
            self.vault_root,
            path=arguments["path"],
            content=arguments["content"],
            target=arguments["target"],
            actor=self.subject_id,
            heading=arguments.get("heading"),
            date=arguments.get("date"),
            create_if_missing=arguments.get("create_if_missing", False),
            expected_hash=arguments.get("expected_hash"),
        )
        return {
            "isError": False,
            "content": [{"type": "text", "text": f"Appended content to `{result['path']}`."}],
            "structuredContent": result,
        }

    def _tool_governance_rebuild_dbms_index(self, arguments: dict) -> dict:
        result = subprocess.run(
            [sys.executable, str(self._script_path("rebuild_dbms_index.py")), str(self.vault_root)],
            capture_output=True,
            text=True,
            cwd=self.vault_root.parents[0],
        )
        state = self._load_json_if_exists(self._dbms_state_dir() / "last-index-run.json")
        structured = {
            "exitCode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "reportPath": state.get("last_report_path") if state is not None else None,
            "state": state,
        }
        message = result.stdout.strip() or result.stderr.strip() or "DBMS index rebuild completed."
        return {
            "isError": result.returncode != 0,
            "content": [{"type": "text", "text": message}],
            "structuredContent": structured,
        }

    def _tool_governance_reconcile_dbms_state(self, arguments: dict) -> dict:
        result = subprocess.run(
            [sys.executable, str(self._script_path("reconcile_dbms_state.py")), str(self.vault_root)],
            capture_output=True,
            text=True,
            cwd=self.vault_root.parents[0],
        )
        index_state = self._load_json_if_exists(self._dbms_state_dir() / "last-index-run.json")
        dbms_state = self._load_json_if_exists(self._dbms_state_dir() / "last-dbms-run.json")
        structured = {
            "exitCode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "reportPath": dbms_state.get("last_report_path") if dbms_state is not None else None,
            "indexState": index_state,
            "dbmsState": dbms_state,
        }
        message = result.stdout.strip() or result.stderr.strip() or "DBMS state reconciliation completed."
        return {
            "isError": result.returncode != 0,
            "content": [{"type": "text", "text": message}],
            "structuredContent": structured,
        }

    def _tool_governance_whoami(self, arguments: dict) -> dict:
        visible_tools = [tool["name"] for tool in self.list_tools() if tool["name"] != "governance_whoami"]
        role = "unknown"
        mapped_agent_id = None
        for tool in self._tool_catalog():
            decision = self._evaluate(tool["name"], tool["risk_level"], tool["target_layer"])
            if "effective_role" in decision:
                role = decision["effective_role"]
                mapped_agent_id = decision.get("mapped_agent_id")
                break
        return {
            "isError": False,
            "content": [{"type": "text", "text": f"Current role: {role}"}],
            "structuredContent": {
                "subjectId": self.subject_id,
                "authMode": self.auth_mode,
                "mappedAgentId": mapped_agent_id,
                "effectiveRole": role,
                "visibleTools": visible_tools,
                "toolCount": len(visible_tools),
            },
        }

    def _tool_governance_propose_registry_update(self, arguments: dict) -> dict:
        proposal = propose_registry_update(
            self.vault_root,
            subject_id=self.subject_id,
            target_kind=arguments["target_kind"],
            operation=arguments["operation"],
            summary=arguments["summary"],
            details={
                "topic_id": arguments.get("topic_id"),
                "path": arguments.get("path"),
                "auth_mode": self.auth_mode,
                "requires_review_by": "system-maintainer",
                "writes_applied": False,
            },
        )
        return {
            "isError": False,
            "content": [{"type": "text", "text": "Created and persisted a registry update proposal. No registry changes were applied."}],
            "structuredContent": {"proposal": proposal},
        }

    def _tool_governance_create_promotion_proposal(self, arguments: dict) -> dict:
        result = create_promotion_proposal(
            self.vault_root,
            subject_id=self.subject_id,
            topic_id=arguments["topic_id"],
            source_path=arguments["source_path"],
            candidate_path=arguments["candidate_path"],
            summary=arguments["summary"],
        )
        return {
            "isError": False,
            "content": [{"type": "text", "text": "Promotion proposal created and queued for review."}],
            "structuredContent": result,
        }

    def _tool_governance_list_promotion_queue(self, arguments: dict) -> dict:
        limit = arguments.get("limit")
        offset = arguments.get("offset")
        result = list_promotion_queue(self.vault_root)
        items = result.get("items", [])
        page = self._paginate(items, limit, offset)
        return {
            "isError": False,
            "content": [{"type": "text", "text": f"Returned {page['total']} promotion queue item(s); showing {page['count']}."}],
            "structuredContent": {
                "items": page["items"],
                "total": page["total"],
                "count": page["count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "next_offset": page["next_offset"],
                "lastUpdated": result.get("lastUpdated"),
            },
        }

    def _tool_governance_apply_registry_update(self, arguments: dict) -> dict:
        result = apply_registry_update_with_proposal(
            self.vault_root,
            subject_id=self.subject_id,
            operation=arguments["operation"],
            target_kind=arguments["target_kind"],
            summary=arguments["summary"],
            entry=arguments["entry"],
            proposal_id=arguments.get("proposal_id"),
        )
        updated_entry = result["updatedEntry"]
        response = {
            "targetKind": result["targetKind"],
            "operation": result["operation"],
            "created": result["created"],
            "updated": result["updated"],
            "ledgerEntry": result["ledgerEntry"],
        }
        if arguments["target_kind"] == "topic":
            response["updatedTopic"] = updated_entry
        elif arguments["target_kind"] == "object":
            response["updatedObject"] = updated_entry
        else:
            response["updatedAdapter"] = updated_entry
        return {
            "isError": False,
            "content": [{"type": "text", "text": "Registry updated and ledger entry appended."}],
            "structuredContent": response,
        }

    def _tool_governance_review_promotion_proposal(self, arguments: dict) -> dict:
        result = review_promotion_proposal(
            self.vault_root,
            subject_id=self.subject_id,
            proposal_id=arguments["proposal_id"],
            decision=arguments["decision"],
            summary=arguments["summary"],
            approval=arguments.get("approval"),
        )
        return {
            "isError": False,
            "content": [{"type": "text", "text": "Promotion proposal reviewed and queue updated."}],
            "structuredContent": result,
        }

    def _tool_governance_apply_promotion_proposal(self, arguments: dict) -> dict:
        result = apply_promotion_proposal(
            self.vault_root,
            subject_id=self.subject_id,
            proposal_id=arguments["proposal_id"],
            summary=arguments["summary"],
        )
        return {
            "isError": False,
            "content": [{"type": "text", "text": "Promotion proposal applied to registry canonical placement."}],
            "structuredContent": result,
        }

    def _tool_governance_evaluate_access(self, arguments: dict) -> dict:
        decision = evaluate_access(
            self.vault_root,
            self.subject_id,
            self.auth_mode,
            arguments["tool"],
            arguments["risk_level"],
            arguments["target_layer"],
        )
        return {
            "isError": False,
            "content": [{"type": "text", "text": f"Decision: {decision['decision']}"}],
            "structuredContent": decision,
        }

    def _tool_governance_request_snapshot_review(self, arguments: dict) -> dict:
        result = request_snapshot_review(self.vault_root, subject_id=self.subject_id, summary=arguments["summary"])
        return {
            "isError": False,
            "content": [{"type": "text", "text": "Snapshot review proposal created."}],
            "structuredContent": result,
        }

    def _tool_governance_review_snapshot_upgrade(self, arguments: dict) -> dict:
        result = review_snapshot_upgrade(self.vault_root)
        return {
            "isError": False,
            "content": [{"type": "text", "text": f"Snapshot status: {result['status']}"}],
            "structuredContent": result,
        }

    def _tool_governance_apply_snapshot_upgrade(self, arguments: dict) -> dict:
        result = apply_snapshot_upgrade_with_proposal(
            self.vault_root,
            subject_id=self.subject_id,
            summary=arguments["summary"],
            proposal_id=arguments.get("proposal_id"),
            approval=arguments.get("approval"),
            expected_snapshot_context=arguments.get("_validated_snapshot_context"),
        )
        return {
            "isError": False,
            "content": [{"type": "text", "text": "Snapshot synced and compatibility status updated."}],
            "structuredContent": result,
        }
