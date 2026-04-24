from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from mcp_access import evaluate_access, load_json
from promotion_queue import apply_promotion_proposal, create_promotion_proposal, list_promotion_queue, review_promotion_proposal
from proposal_store import list_proposals
from registry_updates import apply_registry_update_with_proposal, propose_registry_update
from snapshot_upgrade import apply_snapshot_upgrade_with_proposal, request_snapshot_review, review_snapshot_upgrade


SERVER_INFO = {
    "name": "agents-knowledge-db",
    "version": "0.1.0",
}

SUPPORTED_PROTOCOL_VERSIONS = ["2025-11-25"]


class GovernanceBackend:
    def __init__(self, vault_root: Path, *, subject_id: str, auth_mode: str) -> None:
        self.vault_root = Path(vault_root).resolve()
        self.subject_id = subject_id
        self.auth_mode = auth_mode

    def _registry(self) -> dict:
        return load_json(self.vault_root / ".knowledge-registry" / "vault-registry.json")

    def _agent_roster(self) -> dict:
        return load_json(self.vault_root / ".knowledge-registry" / "agent-roster.json")

    def _findings(self) -> dict:
        return load_json(self.vault_root / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "findings.json")

    def _resource_catalog(self) -> list[dict]:
        return [
            {
                "uri": "governance://rules/root",
                "name": "Root Rules",
                "description": "Human-readable root operating rules for the governed vault.",
                "mimeType": "text/markdown",
            },
            {
                "uri": "governance://registry/vault",
                "name": "Vault Registry",
                "description": "Machine-readable topic and object registry source of truth.",
                "mimeType": "application/json",
            },
            {
                "uri": "governance://registry/agent-roster",
                "name": "Agent Roster",
                "description": "Machine-readable agent role and layer authority registry.",
                "mimeType": "application/json",
            },
            {
                "uri": "governance://registry/governance-proposals",
                "name": "Governance Proposals",
                "description": "Unified proposal store for registry, promotion, and snapshot workflows.",
                "mimeType": "application/json",
            },
            {
                "uri": "governance://registry/promotion-queue",
                "name": "Promotion Queue",
                "description": "Promotion queue state for canonical promotion workflow.",
                "mimeType": "application/json",
            },
            {
                "uri": "governance://local/compatibility-status",
                "name": "Compatibility Status",
                "description": "Local snapshot compatibility state.",
                "mimeType": "application/json",
            },
            {
                "uri": "governance://snapshot/version",
                "name": "Snapshot Version",
                "description": "Current installed system snapshot version metadata.",
                "mimeType": "application/json",
            },
            {
                "uri": "governance://registry/change-ledger",
                "name": "Change Ledger",
                "description": "Append-only governance change ledger.",
                "mimeType": "application/x-ndjson",
            },
            {
                "uri": "governance://dbms/index/findings",
                "name": "DBMS Findings",
                "description": "Derived audit findings from the DBMS materialized index.",
                "mimeType": "application/json",
            },
        ]

    def _tool_catalog(self) -> list[dict]:
        return [
            {
                "name": "search_topics",
                "title": "Search Topics",
                "description": "Search the vault registry by topic title or alias.",
                "risk_level": "L0",
                "target_layer": "system",
                "annotations": {"readOnlyHint": True},
                "inputSchema": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_topic_context",
                "title": "Get Topic Context",
                "description": "Return registry, object, and finding context for a topic.",
                "risk_level": "L0",
                "target_layer": "system",
                "annotations": {"readOnlyHint": True},
                "inputSchema": {
                    "type": "object",
                    "required": ["topic_id"],
                    "properties": {"topic_id": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_topic_findings",
                "title": "List Topic Findings",
                "description": "List DBMS findings for a topic or the whole vault.",
                "risk_level": "L0",
                "target_layer": "system",
                "annotations": {"readOnlyHint": True},
                "inputSchema": {
                    "type": "object",
                    "properties": {"topic_id": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
            {
                "name": "validate_data_repo",
                "title": "Validate Data Repo",
                "description": "Run the governed data repository validator against the current vault.",
                "risk_level": "L1",
                "target_layer": "system",
                "annotations": {"readOnlyHint": True},
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "propose_registry_update",
                "title": "Propose Registry Update",
                "description": "Create and persist a structured registry update proposal without mutating the registry.",
                "risk_level": "L1",
                "target_layer": "system",
                "annotations": {"readOnlyHint": False},
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
            },
            {
                "name": "create_promotion_proposal",
                "title": "Create Promotion Proposal",
                "description": "Append a proposal to the promotion queue and record it in the ledger.",
                "risk_level": "L1",
                "target_layer": "system",
                "annotations": {"readOnlyHint": False},
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
            },
            {
                "name": "list_promotion_queue",
                "title": "List Promotion Queue",
                "description": "Read the current promotion queue.",
                "risk_level": "L0",
                "target_layer": "system",
                "annotations": {"readOnlyHint": True},
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "apply_registry_update",
                "title": "Apply Registry Update",
                "description": "Apply a registry upsert and append a change-ledger entry.",
                "risk_level": "L2",
                "target_layer": "system",
                "annotations": {"readOnlyHint": False},
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
            },
            {
                "name": "review_promotion_proposal",
                "title": "Review Promotion Proposal",
                "description": "Approve or reject a queued promotion proposal.",
                "risk_level": "L3",
                "target_layer": "system",
                "annotations": {"readOnlyHint": False},
                "inputSchema": {
                    "type": "object",
                    "required": ["proposal_id", "decision", "summary"],
                    "properties": {
                        "proposal_id": {"type": "string"},
                        "decision": {"type": "string", "enum": ["approve", "reject"]},
                        "summary": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "apply_promotion_proposal",
                "title": "Apply Promotion Proposal",
                "description": "Apply an approved promotion proposal to registry canonical placement.",
                "risk_level": "L3",
                "target_layer": "system",
                "annotations": {"readOnlyHint": False},
                "inputSchema": {
                    "type": "object",
                    "required": ["proposal_id", "summary"],
                    "properties": {
                        "proposal_id": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "evaluate_access",
                "title": "Evaluate Access",
                "description": "Evaluate the current subject against a requested governance action.",
                "risk_level": "L0",
                "target_layer": "system",
                "annotations": {"readOnlyHint": True},
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
            },
            {
                "name": "request_snapshot_review",
                "title": "Request Snapshot Review",
                "description": "Create and persist a proposal for snapshot upgrade review.",
                "risk_level": "L1",
                "target_layer": "system",
                "annotations": {"readOnlyHint": False},
                "inputSchema": {
                    "type": "object",
                    "required": ["summary"],
                    "properties": {"summary": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
            {
                "name": "review_snapshot_upgrade",
                "title": "Review Snapshot Upgrade",
                "description": "Compare the active snapshot with local compatibility state.",
                "risk_level": "L1",
                "target_layer": "system",
                "annotations": {"readOnlyHint": True},
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "apply_snapshot_upgrade",
                "title": "Apply Snapshot Upgrade",
                "description": "Sync the latest system snapshot into the vault and update compatibility state.",
                "risk_level": "L4",
                "target_layer": "system",
                "annotations": {"readOnlyHint": False},
                "inputSchema": {
                    "type": "object",
                    "required": ["summary"],
                    "properties": {
                        "summary": {"type": "string"},
                        "proposal_id": {"type": "string"}
                    },
                    "additionalProperties": False,
                },
            },
        ]

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

    def list_tools(self) -> list[dict]:
        return [tool for tool in self._tool_catalog() if self._allowed_tool(tool)]

    def list_resources(self) -> list[dict]:
        return self._resource_catalog()

    def read_resource(self, uri: str) -> dict:
        if uri == "governance://rules/root":
            text = (self.vault_root / "RULES.md").read_text(encoding="utf-8")
            return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": text}]}
        if uri == "governance://registry/vault":
            text = json.dumps(self._registry(), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        if uri == "governance://registry/agent-roster":
            text = json.dumps(self._agent_roster(), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        if uri == "governance://registry/governance-proposals":
            text = json.dumps(load_json(self.vault_root / ".knowledge-registry" / "governance-proposals.json"), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        if uri == "governance://registry/promotion-queue":
            text = json.dumps(load_json(self.vault_root / ".knowledge-registry" / "promotion-queue.json"), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        if uri == "governance://local/compatibility-status":
            text = json.dumps(load_json(self.vault_root / "LocalOverrides" / "compatibility-status.json"), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        if uri == "governance://snapshot/version":
            text = json.dumps(load_json(self.vault_root / ".dbms-system" / "version.json"), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        if uri == "governance://registry/change-ledger":
            text = (self.vault_root / ".knowledge-registry" / "change-ledger.jsonl").read_text(encoding="utf-8")
            return {"contents": [{"uri": uri, "mimeType": "application/x-ndjson", "text": text}]}
        if uri == "governance://dbms/index/findings":
            text = json.dumps(self._findings(), ensure_ascii=False, indent=2)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
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
                "name": "review_snapshot_upgrade",
                "description": "Guide a system maintainer through snapshot upgrade review and approval.",
                "arguments": [],
            },
            {
                "name": "review_promotion_proposal",
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
        if name == "review_snapshot_upgrade":
            text = (
                "Review the installed snapshot version, local compatibility status, and any open snapshot proposal "
                "before deciding whether to apply the latest system snapshot."
            )
            return {"messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
        if name == "review_promotion_proposal":
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
            return handler(arguments)
        except ValueError as exc:
            return {
                "isError": True,
                "content": [{"type": "text", "text": str(exc)}],
                "structuredContent": {"tool": name},
            }

    def _tool_search_topics(self, arguments: dict) -> dict:
        query = arguments["query"].strip().lower()
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
        text = f"Matched {len(matches)} topic(s) for query `{arguments['query']}`."
        return {
            "isError": False,
            "content": [{"type": "text", "text": text}],
            "structuredContent": {"query": arguments["query"], "totalMatches": len(matches), "matches": matches},
        }

    def _tool_get_topic_context(self, arguments: dict) -> dict:
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

    def _tool_list_topic_findings(self, arguments: dict) -> dict:
        topic_id = arguments.get("topic_id")
        findings = self._findings().get("items", [])
        if topic_id:
            findings = [item for item in findings if item.get("topic_id") == topic_id]
        text = f"Returned {len(findings)} finding(s)."
        return {
            "isError": False,
            "content": [{"type": "text", "text": text}],
            "structuredContent": {"topic_id": topic_id, "items": findings, "totalFindings": len(findings)},
        }

    def _tool_validate_data_repo(self, arguments: dict) -> dict:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "validate_data_repo.py"), str(self.vault_root)],
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

    def _tool_propose_registry_update(self, arguments: dict) -> dict:
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

    def _tool_create_promotion_proposal(self, arguments: dict) -> dict:
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

    def _tool_list_promotion_queue(self, arguments: dict) -> dict:
        result = list_promotion_queue(self.vault_root)
        return {
            "isError": False,
            "content": [{"type": "text", "text": f"Returned {result['totalItems']} promotion queue item(s)."}],
            "structuredContent": result,
        }

    def _tool_apply_registry_update(self, arguments: dict) -> dict:
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

    def _tool_review_promotion_proposal(self, arguments: dict) -> dict:
        result = review_promotion_proposal(
            self.vault_root,
            subject_id=self.subject_id,
            proposal_id=arguments["proposal_id"],
            decision=arguments["decision"],
            summary=arguments["summary"],
        )
        return {
            "isError": False,
            "content": [{"type": "text", "text": "Promotion proposal reviewed and queue updated."}],
            "structuredContent": result,
        }

    def _tool_apply_promotion_proposal(self, arguments: dict) -> dict:
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

    def _tool_evaluate_access(self, arguments: dict) -> dict:
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

    def _tool_request_snapshot_review(self, arguments: dict) -> dict:
        result = request_snapshot_review(self.vault_root, subject_id=self.subject_id, summary=arguments["summary"])
        return {
            "isError": False,
            "content": [{"type": "text", "text": "Snapshot review proposal created."}],
            "structuredContent": result,
        }

    def _tool_review_snapshot_upgrade(self, arguments: dict) -> dict:
        result = review_snapshot_upgrade(self.vault_root)
        return {
            "isError": False,
            "content": [{"type": "text", "text": f"Snapshot status: {result['status']}"}],
            "structuredContent": result,
        }

    def _tool_apply_snapshot_upgrade(self, arguments: dict) -> dict:
        result = apply_snapshot_upgrade_with_proposal(
            self.vault_root,
            subject_id=self.subject_id,
            summary=arguments["summary"],
            proposal_id=arguments.get("proposal_id"),
        )
        return {
            "isError": False,
            "content": [{"type": "text", "text": "Snapshot synced and compatibility status updated."}],
            "structuredContent": result,
        }
