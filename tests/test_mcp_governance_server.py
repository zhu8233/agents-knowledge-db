from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from mcp_governance_backend import GovernanceBackend  # type: ignore  # noqa: E402


def _framed_message_bytes(message: dict) -> bytes:
    payload = json.dumps(message).encode("utf-8")
    return f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload


def _write_framed_message(stream, message: dict) -> None:
    stream.write(_framed_message_bytes(message))
    stream.flush()


def _read_framed_messages(data: bytes) -> list[dict]:
    messages: list[dict] = []
    cursor = 0
    while cursor < len(data):
        header_end = data.find(b"\r\n\r\n", cursor)
        if header_end == -1:
            break
        header_blob = data[cursor:header_end].decode("ascii")
        headers = {}
        for line in header_blob.split("\r\n"):
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        length = int(headers["content-length"])
        body_start = header_end + 4
        body_end = body_start + length
        body = data[body_start:body_end]
        messages.append(json.loads(body.decode("utf-8")))
        cursor = body_end
    return messages


def _run_stdio_sequence(vault: Path, subject_id: str, auth_mode: str, requests: list[dict]) -> list[dict]:
    chunks = [
        _framed_message_bytes(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"},
                },
            }
        ),
        _framed_message_bytes({"jsonrpc": "2.0", "method": "notifications/initialized"}),
    ]
    for request in requests:
        chunks.append(_framed_message_bytes(request))
    stdin_payload = b"".join(chunks)

    proc = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts" / "mcp_governance_server.py"),
            str(vault),
            "--subject-id",
            subject_id,
            "--auth-mode",
            auth_mode,
        ],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = proc.communicate(input=stdin_payload, timeout=10)
    if proc.returncode != 0:
        raise AssertionError(stderr.decode("utf-8"))
    return _read_framed_messages(stdout)


class McpGovernanceServerTests(unittest.TestCase):
    def _install_and_seed_vault(self, vault: Path) -> None:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
            check=True,
            cwd=ROOT,
        )

        registry_path = vault / ".knowledge-registry" / "vault-registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["topics"].append(
            {
                "topic_id": "topic.python",
                "title": "Python",
                "aliases": ["py"],
                "status": "active",
                "source_domains": ["language"],
                "intake_paths": ["ProjectRaw/Python"],
                "curation_paths": ["20-KnowledgeHub/Python"],
                "canonical_home": "20-KnowledgeHub/Python/index.md",
                "related_topics": [],
                "upstream_bindings": [],
            }
        )
        registry["objects"].append(
            {
                "kb_id": "kb.python.index",
                "path": "20-KnowledgeHub/Python/index.md",
                "kb_type": "canonical_index",
                "kb_layer": "canonical",
                "topic_id": "topic.python",
                "status": "active",
                "managed_by": "human",
                "source_system": "human",
                "updated_at": "2026-04-24",
            }
        )
        registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

        canonical_path = vault / "20-KnowledgeHub" / "Python" / "index.md"
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        canonical_path.write_text("# Python\n", encoding="utf-8")

        findings_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "findings.json"
        findings = {
            "items": [
                {
                    "finding_id": "finding.python.frontmatter",
                    "finding_type": "frontmatter_missing",
                    "topic_id": "topic.python",
                    "path": "20-KnowledgeHub/Python/index.md",
                    "severity": "medium",
                    "status": "open",
                }
            ]
        }
        findings_path.write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_vault_user_tool_list_hides_admin_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")
            tools = backend.list_tools()
            tool_names = [tool["name"] for tool in tools]

            self.assertIn("search_topics", tool_names)
            self.assertIn("get_topic_context", tool_names)
            self.assertNotIn("validate_data_repo", tool_names)
            self.assertNotIn("propose_registry_update", tool_names)

    def test_whoami_returns_effective_role_and_visible_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            reader_backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")
            owner_backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")

            reader_result = reader_backend.call_tool("whoami", {})
            owner_result = owner_backend.call_tool("whoami", {})

            self.assertFalse(reader_result["isError"])
            self.assertFalse(owner_result["isError"])
            self.assertEqual(reader_result["structuredContent"]["effectiveRole"], "vault-user")
            self.assertEqual(owner_result["structuredContent"]["effectiveRole"], "system-maintainer")
            self.assertIn("search_topics", reader_result["structuredContent"]["visibleTools"])
            self.assertNotIn("apply_registry_update", reader_result["structuredContent"]["visibleTools"])
            self.assertIn("apply_registry_update", owner_result["structuredContent"]["visibleTools"])

    def test_system_maintainer_tool_list_includes_governance_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            tools = backend.list_tools()
            tool_names = [tool["name"] for tool in tools]

            self.assertIn("validate_data_repo", tool_names)
            self.assertIn("propose_registry_update", tool_names)
            self.assertIn("apply_registry_update", tool_names)
            self.assertIn("list_promotion_queue", tool_names)
            self.assertIn("review_snapshot_upgrade", tool_names)
            self.assertIn("apply_snapshot_upgrade", tool_names)
            self.assertIn("review_promotion_proposal", tool_names)
            self.assertIn("apply_promotion_proposal", tool_names)
            self.assertIn("evaluate_access", tool_names)

    def test_search_topics_matches_title_and_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")

            by_title = backend.call_tool("search_topics", {"query": "python"})
            by_alias = backend.call_tool("search_topics", {"query": "py"})

            self.assertEqual(by_title["structuredContent"]["totalMatches"], 1)
            self.assertEqual(by_alias["structuredContent"]["totalMatches"], 1)
            self.assertEqual(by_title["structuredContent"]["matches"][0]["topic_id"], "topic.python")

    def test_get_topic_context_returns_topic_objects_and_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")
            result = backend.call_tool("get_topic_context", {"topic_id": "topic.python"})

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["topic"]["topic_id"], "topic.python")
            self.assertEqual(result["structuredContent"]["objectCount"], 1)
            self.assertEqual(result["structuredContent"]["findingCount"], 1)

    def test_prompts_and_resources_are_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")
            prompts = backend.list_prompts()
            resources = backend.list_resources()
            prompt = backend.get_prompt("onboard_agent_to_vault", {})
            rules = backend.read_resource("governance://rules/root")

            self.assertIn("onboard_agent_to_vault", [item["name"] for item in prompts])
            self.assertIn("prepare_registry_repair", [item["name"] for item in prompts])
            self.assertIn("review_snapshot_upgrade", [item["name"] for item in prompts])
            self.assertIn("review_promotion_proposal", [item["name"] for item in prompts])
            self.assertIn("governance://rules/root", [item["uri"] for item in resources])
            self.assertIn("governance://registry/governance-proposals", [item["uri"] for item in resources])
            self.assertIn("governance://registry/promotion-queue", [item["uri"] for item in resources])
            self.assertIn("governance://local/compatibility-status", [item["uri"] for item in resources])
            self.assertIn("governance://snapshot/version", [item["uri"] for item in resources])
            self.assertIn("governance://registry/change-ledger", [item["uri"] for item in resources])
            self.assertEqual(prompt["messages"][0]["role"], "user")
            self.assertIn("read `RULES.md`", prompt["messages"][0]["content"]["text"])
            self.assertIn("This is the single rule source for the governed vault.", rules["contents"][0]["text"])

            queue_resource = backend.read_resource("governance://registry/promotion-queue")
            compat_resource = backend.read_resource("governance://local/compatibility-status")
            ledger_resource = backend.read_resource("governance://registry/change-ledger")
            self.assertIn('"items"', queue_resource["contents"][0]["text"])
            self.assertIn('"status"', compat_resource["contents"][0]["text"])
            self.assertIn('"bootstrap"', ledger_resource["contents"][0]["text"])

    def test_propose_registry_update_persists_governance_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            result = backend.call_tool(
                "propose_registry_update",
                {
                    "target_kind": "topic",
                    "operation": "upsert_topic",
                    "summary": "Propose a new topic registration",
                    "topic_id": "topic.registry-proposal",
                    "path": "ProjectRaw/RegistryProposal",
                },
            )

            self.assertFalse(result["isError"])
            proposal = result["structuredContent"]["proposal"]
            self.assertEqual(proposal["proposal_type"], "registry_update")

            proposals = json.loads((vault / ".knowledge-registry" / "governance-proposals.json").read_text(encoding="utf-8"))
            self.assertEqual(len(proposals["items"]), 1)
            self.assertEqual(proposals["items"][0]["proposal_id"], proposal["proposal_id"])

    def test_request_snapshot_review_persists_governance_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            result = backend.call_tool("request_snapshot_review", {"summary": "Request snapshot review before upgrade"})

            self.assertFalse(result["isError"])
            proposal = result["structuredContent"]["proposal"]
            self.assertEqual(proposal["proposal_type"], "snapshot_upgrade")

    def test_apply_promotion_proposal_requires_approved_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            registry_path = vault / ".knowledge-registry" / "vault-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["topics"].append(
                {
                    "topic_id": "topic.unapproved",
                    "title": "Unapproved",
                    "aliases": [],
                    "status": "active",
                    "source_domains": ["example"],
                    "intake_paths": ["ProjectRaw/Unapproved"],
                    "curation_paths": ["10-Curation/Unapproved"],
                    "canonical_home": None,
                    "related_topics": [],
                    "upstream_bindings": [],
                }
            )
            registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

            maintainer_backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            proposal = maintainer_backend.call_tool(
                "create_promotion_proposal",
                {
                    "topic_id": "topic.unapproved",
                    "source_path": "10-Curation/Unapproved/summary.md",
                    "candidate_path": "20-KnowledgeHub/Unapproved/index.md",
                    "summary": "Create but do not approve",
                },
            )["structuredContent"]["proposal"]

            owner_backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            result = owner_backend.call_tool(
                "apply_promotion_proposal",
                {
                    "proposal_id": proposal["proposal_id"],
                    "summary": "Try to apply before approval",
                },
            )

            self.assertTrue(result["isError"])
            self.assertIn("must be approved", result["content"][0]["text"])

    def test_review_promotion_proposal_rejects_unknown_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            owner_backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            result = owner_backend.call_tool(
                "review_promotion_proposal",
                {
                    "proposal_id": "proposal.missing",
                    "decision": "approve",
                    "summary": "Missing proposal",
                },
            )

            self.assertTrue(result["isError"])
            self.assertIn("Unknown proposal_id", result["content"][0]["text"])

    def test_apply_promotion_proposal_rejects_duplicate_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            registry_path = vault / ".knowledge-registry" / "vault-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["topics"].append(
                {
                    "topic_id": "topic.duplicate-apply",
                    "title": "Duplicate Apply",
                    "aliases": [],
                    "status": "active",
                    "source_domains": ["example"],
                    "intake_paths": ["ProjectRaw/DuplicateApply"],
                    "curation_paths": ["10-Curation/DuplicateApply"],
                    "canonical_home": None,
                    "related_topics": [],
                    "upstream_bindings": [],
                }
            )
            registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

            maintainer_backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            proposal_id = maintainer_backend.call_tool(
                "create_promotion_proposal",
                {
                    "topic_id": "topic.duplicate-apply",
                    "source_path": "10-Curation/DuplicateApply/summary.md",
                    "candidate_path": "20-KnowledgeHub/DuplicateApply/index.md",
                    "summary": "Duplicate apply scenario",
                },
            )["structuredContent"]["proposal"]["proposal_id"]

            owner_backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            owner_backend.call_tool(
                "review_promotion_proposal",
                {
                    "proposal_id": proposal_id,
                    "decision": "approve",
                    "summary": "Approved",
                },
            )
            owner_backend.call_tool(
                "apply_promotion_proposal",
                {
                    "proposal_id": proposal_id,
                    "summary": "First apply",
                },
            )
            duplicate = owner_backend.call_tool(
                "apply_promotion_proposal",
                {
                    "proposal_id": proposal_id,
                    "summary": "Second apply",
                },
            )

            self.assertTrue(duplicate["isError"])
            self.assertIn("already applied", duplicate["content"][0]["text"])

    def test_system_maintainer_can_apply_topic_registry_update_and_append_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            result = backend.call_tool(
                "apply_registry_update",
                {
                    "target_kind": "topic",
                    "operation": "upsert_topic",
                    "summary": "Register a new MCP topic",
                    "entry": {
                        "topic_id": "topic.mcp",
                        "title": "Model Context Protocol",
                        "aliases": ["mcp"],
                        "status": "active",
                        "source_domains": ["protocol"],
                        "intake_paths": ["ProjectRaw/MCP"],
                        "curation_paths": ["20-KnowledgeHub/MCP"],
                        "canonical_home": "20-KnowledgeHub/MCP/index.md",
                        "related_topics": ["topic.python"],
                        "upstream_bindings": []
                    }
                },
            )

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["updatedTopic"]["topic_id"], "topic.mcp")

            registry = json.loads((vault / ".knowledge-registry" / "vault-registry.json").read_text(encoding="utf-8"))
            self.assertIn("topic.mcp", [item["topic_id"] for item in registry["topics"]])

            ledger_lines = [line for line in (vault / ".knowledge-registry" / "change-ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            last_entry = json.loads(ledger_lines[-1])
            self.assertEqual(last_entry["operation"], "upsert_topic")
            self.assertEqual(last_entry["topic_id"], "topic.mcp")
            self.assertTrue(last_entry["registry_updated"])

    def test_vault_maintainer_cannot_apply_registry_update_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            result = backend.call_tool(
                "apply_registry_update",
                {
                    "target_kind": "topic",
                    "operation": "upsert_topic",
                    "summary": "Attempt direct write",
                    "entry": {
                        "topic_id": "topic.blocked",
                        "title": "Blocked",
                        "aliases": [],
                        "status": "active",
                        "source_domains": [],
                        "intake_paths": [],
                        "curation_paths": [],
                        "canonical_home": None,
                        "related_topics": [],
                        "upstream_bindings": []
                    }
                },
            )

            self.assertTrue(result["isError"])
            self.assertEqual(result["structuredContent"]["decision"], "proposal-only")

    def test_system_maintainer_can_review_snapshot_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            compat_path = vault / "LocalOverrides" / "compatibility-status.json"
            compat_path.write_text(
                json.dumps(
                    {
                        "system_tag": "stale-tag",
                        "override_checked_at": "2026-04-01T00:00:00Z",
                        "status": "review-needed",
                        "notes": "Behind latest snapshot"
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            result = backend.call_tool("review_snapshot_upgrade", {})

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["status"], "review-needed")
            self.assertTrue(result["structuredContent"]["upgradeAvailable"])

    def test_vault_maintainer_can_create_promotion_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            result = backend.call_tool(
                "create_promotion_proposal",
                {
                    "topic_id": "topic.python",
                    "source_path": "20-KnowledgeHub/Python/index.md",
                    "candidate_path": "20-KnowledgeHub/Python/index.md",
                    "summary": "Promote Python index to reviewed canonical state",
                },
            )

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["proposal"]["topic_id"], "topic.python")

            queue = json.loads((vault / ".knowledge-registry" / "promotion-queue.json").read_text(encoding="utf-8"))
            self.assertEqual(len(queue["items"]), 1)
            self.assertEqual(queue["items"][0]["topic_id"], "topic.python")
            self.assertEqual(queue["items"][0]["status"], "proposed")

            ledger_lines = [line for line in (vault / ".knowledge-registry" / "change-ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            last_entry = json.loads(ledger_lines[-1])
            self.assertEqual(last_entry["operation"], "promotion_proposal_create")
            self.assertEqual(last_entry["topic_id"], "topic.python")

    def test_vault_maintainer_can_list_promotion_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            backend.call_tool(
                "create_promotion_proposal",
                {
                    "topic_id": "topic.python",
                    "source_path": "20-KnowledgeHub/Python/index.md",
                    "candidate_path": "20-KnowledgeHub/Python/index.md",
                    "summary": "Promote Python index",
                },
            )
            result = backend.call_tool("list_promotion_queue", {})

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["totalItems"], 1)
            self.assertEqual(result["structuredContent"]["items"][0]["status"], "proposed")

    def test_system_maintainer_can_approve_promotion_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            maintainer_backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            proposal_result = maintainer_backend.call_tool(
                "create_promotion_proposal",
                {
                    "topic_id": "topic.python",
                    "source_path": "20-KnowledgeHub/Python/index.md",
                    "candidate_path": "20-KnowledgeHub/Python/index.md",
                    "summary": "Promote Python index",
                },
            )
            proposal_id = proposal_result["structuredContent"]["proposal"]["proposal_id"]

            owner_backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            review_result = owner_backend.call_tool(
                "review_promotion_proposal",
                {
                    "proposal_id": proposal_id,
                    "decision": "approve",
                    "summary": "Promotion approved for canonical review",
                },
            )

            self.assertFalse(review_result["isError"])
            self.assertEqual(review_result["structuredContent"]["proposal"]["status"], "approved")
            self.assertEqual(review_result["structuredContent"]["proposal"]["reviewed_by"], "owner@example.com")

            queue = json.loads((vault / ".knowledge-registry" / "promotion-queue.json").read_text(encoding="utf-8"))
            item = next(item for item in queue["items"] if item["proposal_id"] == proposal_id)
            self.assertEqual(item["status"], "approved")

            ledger_lines = [line for line in (vault / ".knowledge-registry" / "change-ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            last_entry = json.loads(ledger_lines[-1])
            self.assertEqual(last_entry["operation"], "promotion_proposal_review")
            self.assertEqual(last_entry["topic_id"], "topic.python")

    def test_system_maintainer_can_apply_approved_promotion_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            registry_path = vault / ".knowledge-registry" / "vault-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["topics"].append(
                {
                    "topic_id": "topic.promote-me",
                    "title": "Promote Me",
                    "aliases": [],
                    "status": "active",
                    "source_domains": ["example"],
                    "intake_paths": ["ProjectRaw/PromoteMe"],
                    "curation_paths": ["10-Curation/PromoteMe"],
                    "canonical_home": None,
                    "related_topics": [],
                    "upstream_bindings": [],
                }
            )
            registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

            maintainer_backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            proposal_result = maintainer_backend.call_tool(
                "create_promotion_proposal",
                {
                    "topic_id": "topic.promote-me",
                    "source_path": "10-Curation/PromoteMe/summary.md",
                    "candidate_path": "20-KnowledgeHub/PromoteMe/index.md",
                    "summary": "Promote curated summary into canonical home",
                },
            )
            proposal_id = proposal_result["structuredContent"]["proposal"]["proposal_id"]

            owner_backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            owner_backend.call_tool(
                "review_promotion_proposal",
                {
                    "proposal_id": proposal_id,
                    "decision": "approve",
                    "summary": "Promotion approved",
                },
            )
            apply_result = owner_backend.call_tool(
                "apply_promotion_proposal",
                {
                    "proposal_id": proposal_id,
                    "summary": "Apply approved promotion to registry canonical home",
                },
            )

            self.assertFalse(apply_result["isError"])
            self.assertEqual(apply_result["structuredContent"]["proposal"]["status"], "applied")
            self.assertEqual(apply_result["structuredContent"]["updatedTopic"]["canonical_home"], "20-KnowledgeHub/PromoteMe/index.md")

            updated_registry = json.loads(registry_path.read_text(encoding="utf-8"))
            topic = next(item for item in updated_registry["topics"] if item["topic_id"] == "topic.promote-me")
            self.assertEqual(topic["canonical_home"], "20-KnowledgeHub/PromoteMe/index.md")

            queue = json.loads((vault / ".knowledge-registry" / "promotion-queue.json").read_text(encoding="utf-8"))
            item = next(item for item in queue["items"] if item["proposal_id"] == proposal_id)
            self.assertEqual(item["status"], "applied")

            ledger_lines = [line for line in (vault / ".knowledge-registry" / "change-ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            last_entry = json.loads(ledger_lines[-1])
            self.assertEqual(last_entry["operation"], "promotion_proposal_apply")
            self.assertEqual(last_entry["topic_id"], "topic.promote-me")

    def test_vault_maintainer_cannot_review_promotion_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            maintainer_backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            proposal_result = maintainer_backend.call_tool(
                "create_promotion_proposal",
                {
                    "topic_id": "topic.python",
                    "source_path": "20-KnowledgeHub/Python/index.md",
                    "candidate_path": "20-KnowledgeHub/Python/index.md",
                    "summary": "Promote Python index",
                },
            )
            proposal_id = proposal_result["structuredContent"]["proposal"]["proposal_id"]

            result = maintainer_backend.call_tool(
                "review_promotion_proposal",
                {
                    "proposal_id": proposal_id,
                    "decision": "approve",
                    "summary": "Attempt unauthorized approval",
                },
            )

            self.assertTrue(result["isError"])
            self.assertEqual(result["structuredContent"]["decision"], "deny")

    def test_vault_maintainer_cannot_apply_promotion_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            registry_path = vault / ".knowledge-registry" / "vault-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["topics"].append(
                {
                    "topic_id": "topic.promote-blocked",
                    "title": "Promote Blocked",
                    "aliases": [],
                    "status": "active",
                    "source_domains": ["example"],
                    "intake_paths": ["ProjectRaw/PromoteBlocked"],
                    "curation_paths": ["10-Curation/PromoteBlocked"],
                    "canonical_home": None,
                    "related_topics": [],
                    "upstream_bindings": [],
                }
            )
            registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

            maintainer_backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            proposal_result = maintainer_backend.call_tool(
                "create_promotion_proposal",
                {
                    "topic_id": "topic.promote-blocked",
                    "source_path": "10-Curation/PromoteBlocked/summary.md",
                    "candidate_path": "20-KnowledgeHub/PromoteBlocked/index.md",
                    "summary": "Prepare blocked promotion",
                },
            )
            proposal_id = proposal_result["structuredContent"]["proposal"]["proposal_id"]

            result = maintainer_backend.call_tool(
                "apply_promotion_proposal",
                {
                    "proposal_id": proposal_id,
                    "summary": "Attempt unauthorized promotion apply",
                },
            )

            self.assertTrue(result["isError"])
            self.assertEqual(result["structuredContent"]["decision"], "deny")

    def test_vault_user_cannot_create_promotion_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")
            result = backend.call_tool(
                "create_promotion_proposal",
                {
                    "topic_id": "topic.python",
                    "source_path": "20-KnowledgeHub/Python/index.md",
                    "candidate_path": "20-KnowledgeHub/Python/index.md",
                    "summary": "Attempt unauthorized promotion",
                },
            )

            self.assertTrue(result["isError"])
            self.assertEqual(result["structuredContent"]["decision"], "deny")

    def test_system_maintainer_can_apply_snapshot_upgrade_and_update_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            compat_path = vault / "LocalOverrides" / "compatibility-status.json"
            compat_path.write_text(
                json.dumps(
                    {
                        "system_tag": "stale-tag",
                        "override_checked_at": "2026-04-01T00:00:00Z",
                        "status": "review-needed",
                        "notes": "Behind latest snapshot"
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            result = backend.call_tool("apply_snapshot_upgrade", {"summary": "Apply latest system snapshot"})

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["status"], "compatible")

            compat = json.loads(compat_path.read_text(encoding="utf-8"))
            version = json.loads((vault / ".dbms-system" / "version.json").read_text(encoding="utf-8"))
            expected_ref = version.get("release_tag") or version.get("source_commit")
            self.assertEqual(compat["system_tag"], expected_ref)
            self.assertEqual(compat["status"], "compatible")

            ledger_lines = [line for line in (vault / ".knowledge-registry" / "change-ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            last_entry = json.loads(ledger_lines[-1])
            self.assertEqual(last_entry["operation"], "system_snapshot_apply")
            self.assertTrue(last_entry["registry_updated"])

    def test_vault_maintainer_cannot_apply_snapshot_upgrade_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            result = backend.call_tool("apply_snapshot_upgrade", {"summary": "Attempt direct snapshot apply"})

            self.assertTrue(result["isError"])
            self.assertEqual(result["structuredContent"]["decision"], "proposal-only")

    def test_stdio_server_supports_initialize_and_tools_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            stdin_payload = b"".join(
                [
                    _framed_message_bytes(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {
                                "protocolVersion": "2025-11-25",
                                "capabilities": {},
                                "clientInfo": {"name": "test-client", "version": "1.0.0"},
                            },
                        }
                    ),
                    _framed_message_bytes({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                    _framed_message_bytes({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
                ]
            )

            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "mcp_governance_server.py"),
                    str(vault),
                    "--subject-id",
                    "reader@example.com",
                    "--auth-mode",
                    "oauth",
                ],
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            stdout, stderr = proc.communicate(input=stdin_payload, timeout=10)
            self.assertEqual(proc.returncode, 0, stderr.decode("utf-8"))

            messages = _read_framed_messages(stdout)
            init_response = next(item for item in messages if item.get("id") == 1)
            tools_response = next(item for item in messages if item.get("id") == 2)

            self.assertEqual(init_response["result"]["serverInfo"]["name"], "agents-knowledge-db")
            tool_names = [item["name"] for item in tools_response["result"]["tools"]]
            self.assertIn("search_topics", tool_names)
            self.assertNotIn("validate_data_repo", tool_names)

    def test_launcher_script_supports_stdio_initialize_and_tools_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_mcp_server.py"),
                    str(vault),
                    "--subject-id",
                    "reader@example.com",
                    "--auth-mode",
                    "oauth",
                ],
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            assert proc.stdin is not None
            _write_framed_message(
                proc.stdin,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "launcher-test", "version": "1.0.0"},
                    },
                },
            )
            _write_framed_message(proc.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            _write_framed_message(proc.stdin, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            proc.stdin.close()

            stdout, stderr = proc.communicate(timeout=10)
            self.assertEqual(proc.returncode, 0, stderr.decode("utf-8"))
            messages = _read_framed_messages(stdout)
            tools_response = next(item for item in messages if item.get("id") == 2)
            tool_names = [item["name"] for item in tools_response["result"]["tools"]]
            self.assertIn("whoami", tool_names)
            self.assertNotIn("apply_snapshot_upgrade", tool_names)

    def test_stdio_end_to_end_promotion_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            registry_path = vault / ".knowledge-registry" / "vault-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["topics"].append(
                {
                    "topic_id": "topic.stdio-promote",
                    "title": "Stdio Promote",
                    "aliases": [],
                    "status": "active",
                    "source_domains": ["example"],
                    "intake_paths": ["ProjectRaw/StdioPromote"],
                    "curation_paths": ["10-Curation/StdioPromote"],
                    "canonical_home": None,
                    "related_topics": [],
                    "upstream_bindings": []
                }
            )
            registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

            maintainer_messages = _run_stdio_sequence(
                vault,
                "maintainer@example.com",
                "oauth",
                [
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "create_promotion_proposal",
                            "arguments": {
                                "topic_id": "topic.stdio-promote",
                                "source_path": "10-Curation/StdioPromote/summary.md",
                                "candidate_path": "20-KnowledgeHub/StdioPromote/index.md",
                                "summary": "Create promotion via stdio",
                            },
                        },
                    }
                ],
            )
            create_response = next(item for item in maintainer_messages if item.get("id") == 2)
            proposal_id = create_response["result"]["structuredContent"]["proposal"]["proposal_id"]

            owner_messages = _run_stdio_sequence(
                vault,
                "owner@example.com",
                "oauth",
                [
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "review_promotion_proposal",
                            "arguments": {
                                "proposal_id": proposal_id,
                                "decision": "approve",
                                "summary": "Approve via stdio",
                            },
                        },
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "apply_promotion_proposal",
                            "arguments": {
                                "proposal_id": proposal_id,
                                "summary": "Apply via stdio",
                            },
                        },
                    },
                ],
            )
            apply_response = next(item for item in owner_messages if item.get("id") == 3)
            self.assertFalse(apply_response["result"]["isError"])
            self.assertEqual(apply_response["result"]["structuredContent"]["proposal"]["status"], "applied")


if __name__ == "__main__":
    unittest.main()
