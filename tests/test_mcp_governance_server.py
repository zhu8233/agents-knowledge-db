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
    return json.dumps(message).encode("utf-8") + b"\n"


def _write_framed_message(stream, message: dict) -> None:
    stream.write(_framed_message_bytes(message))
    stream.flush()


def _read_framed_messages(data: bytes) -> list[dict]:
    messages: list[dict] = []
    for line in data.splitlines():
        if line.strip():
            messages.append(json.loads(line.decode("utf-8")))
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

        health_path = vault / "ProjectRaw" / "Health"
        health_path.mkdir(parents=True, exist_ok=True)
        (health_path / "diet.md").write_text(
            "# Diet\n\n## 2026-05-14\ncalories: 1900\n",
            encoding="utf-8",
        )

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

    def _snapshot_approval(self, vault: Path, **overrides: object) -> dict:
        version = json.loads((vault / ".dbms-system" / "version.json").read_text(encoding="utf-8"))
        compat = json.loads((vault / "LocalOverrides" / "compatibility-status.json").read_text(encoding="utf-8"))
        approval = {
            "approved_by": "owner@example.com",
            "approved_at": "2026-05-13T12:00:00Z",
            "evidence": "Manual approval recorded for snapshot apply",
            "snapshot_ref": version.get("snapshot_ref") or version.get("release_tag") or version.get("source_commit"),
            "compatibility_ref": compat.get("system_tag"),
        }
        approval.update(overrides)
        return approval

    def test_vault_user_tool_list_hides_admin_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")
            tools = backend.list_tools()
            tool_names = [tool["name"] for tool in tools]

            self.assertIn("governance_search_topics", tool_names)
            self.assertIn("governance_get_topic_context", tool_names)
            self.assertNotIn("governance_validate_data_repo", tool_names)
            self.assertNotIn("governance_rebuild_dbms_index", tool_names)
            self.assertNotIn("governance_reconcile_dbms_state", tool_names)
            self.assertNotIn("governance_propose_registry_update", tool_names)

    def test_whoami_returns_effective_role_and_visible_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            reader_backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")
            owner_backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")

            reader_result = reader_backend.call_tool("governance_whoami", {})
            owner_result = owner_backend.call_tool("governance_whoami", {})

            self.assertFalse(reader_result["isError"])
            self.assertFalse(owner_result["isError"])
            self.assertEqual(reader_result["structuredContent"]["effectiveRole"], "vault-user")
            self.assertEqual(owner_result["structuredContent"]["effectiveRole"], "system-maintainer")
            self.assertIn("governance_search_topics", reader_result["structuredContent"]["visibleTools"])
            self.assertNotIn("governance_apply_registry_update", reader_result["structuredContent"]["visibleTools"])
            self.assertIn("governance_apply_registry_update", owner_result["structuredContent"]["visibleTools"])

    def test_system_maintainer_tool_list_includes_governance_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            tools = backend.list_tools()
            tool_names = [tool["name"] for tool in tools]

            self.assertIn("governance_validate_data_repo", tool_names)
            self.assertIn("governance_propose_registry_update", tool_names)
            self.assertIn("governance_apply_registry_update", tool_names)
            self.assertIn("governance_list_promotion_queue", tool_names)
            self.assertIn("governance_review_snapshot_upgrade", tool_names)
            self.assertIn("governance_apply_snapshot_upgrade", tool_names)
            self.assertIn("governance_review_promotion_proposal", tool_names)
            self.assertIn("governance_apply_promotion_proposal", tool_names)
            self.assertIn("governance_evaluate_access", tool_names)
            self.assertIn("governance_rebuild_dbms_index", tool_names)
            self.assertIn("governance_reconcile_dbms_state", tool_names)

    def test_system_maintainer_tool_list_includes_vault_content_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            tool_names = [tool["name"] for tool in backend.list_tools()]

            self.assertIn("vault_list_paths", tool_names)
            self.assertIn("vault_read_markdown", tool_names)
            self.assertIn("vault_search_markdown", tool_names)
            self.assertIn("vault_check_artifacts", tool_names)
            self.assertIn("vault_scan_curation_gaps", tool_names)

    def test_vault_user_tool_list_includes_read_only_vault_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")
            tool_names = [tool["name"] for tool in backend.list_tools()]

            self.assertIn("vault_list_paths", tool_names)
            self.assertIn("vault_read_markdown", tool_names)
            self.assertIn("vault_search_markdown", tool_names)
            self.assertIn("vault_check_artifacts", tool_names)
            self.assertNotIn("vault_scan_curation_gaps", tool_names)

    def test_search_topics_matches_title_and_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")

            by_title = backend.call_tool("governance_search_topics", {"query": "python"})
            by_alias = backend.call_tool("governance_search_topics", {"query": "py"})

            self.assertEqual(by_title["structuredContent"]["total"], 1)
            self.assertEqual(by_alias["structuredContent"]["total"], 1)
            self.assertEqual(by_title["structuredContent"]["matches"][0]["topic_id"], "topic.python")
            self.assertEqual(by_title["structuredContent"]["count"], 1)
            self.assertEqual(by_title["structuredContent"]["offset"], 0)
            self.assertEqual(by_title["structuredContent"]["has_more"], False)
            self.assertIsNone(by_title["structuredContent"]["next_offset"])

    def test_get_topic_context_returns_topic_objects_and_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")
            result = backend.call_tool("governance_get_topic_context", {"topic_id": "topic.python"})

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["topic"]["topic_id"], "topic.python")
            self.assertEqual(result["structuredContent"]["objectCount"], 1)
            self.assertEqual(result["structuredContent"]["findingCount"], 1)

    def test_vault_read_markdown_tool_returns_structured_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")
            result = backend.call_tool(
                "vault_read_markdown",
                {"path": "ProjectRaw/Health/diet.md", "date_filter": "2026-05-14"},
            )

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["path"], "ProjectRaw/Health/diet.md")
            self.assertIn("1900", result["structuredContent"]["content"])

    def test_vault_list_paths_tool_applies_backend_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")
            result = backend.call_tool("vault_list_paths", {"root": "ProjectRaw/Health"})

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["root"], "ProjectRaw/Health")
            self.assertIn("ProjectRaw/Health/diet.md", result["structuredContent"]["paths"])

    def test_vault_scan_curation_gaps_tool_returns_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)
            registry_path = vault / ".knowledge-registry" / "vault-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["topics"].append(
                {
                    "topic_id": "topic.deep_scan",
                    "title": "Deep Scan",
                    "aliases": [],
                    "status": "active",
                    "source_domains": ["research"],
                    "intake_paths": ["ProjectRaw/DeepScan"],
                    "curation_paths": ["20-KnowledgeHub/DeepScan"],
                    "canonical_home": "20-KnowledgeHub/DeepScan/index.md",
                    "related_topics": [],
                    "upstream_bindings": [],
                }
            )
            registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
            topic_dir = vault / "ProjectRaw" / "DeepScan"
            topic_dir.mkdir(parents=True, exist_ok=True)
            for index in range(2):
                (topic_dir / f"0{index + 1}-source.md").write_text("source\n", encoding="utf-8")

            backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            result = backend.call_tool("vault_scan_curation_gaps", {"min_intake_files": 2})

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["count"], 1)
            self.assertEqual(result["structuredContent"]["items"][0]["topic_path"], "ProjectRaw/DeepScan")

    def test_system_maintainer_can_upsert_markdown_via_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            result = backend.call_tool(
                "vault_upsert_markdown",
                {"path": "ProjectRaw/DailyReports/2026-05-14.md", "content": "# Daily\n", "mode": "upsert"},
            )

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["operation"], "upsert")
            self.assertEqual(result["structuredContent"]["path"], "ProjectRaw/DailyReports/2026-05-14.md")

    def test_vault_maintainer_cannot_call_vault_upsert_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            result = backend.call_tool(
                "vault_upsert_markdown",
                {"path": "ProjectRaw/DailyReports/2026-05-14.md", "content": "# Daily\n", "mode": "upsert"},
            )

            self.assertTrue(result["isError"])

    def test_system_maintainer_can_append_markdown_via_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)
            report = vault / "ProjectRaw" / "DailyReports" / "2026-05-14.md"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("# Daily\n", encoding="utf-8")

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            result = backend.call_tool(
                "vault_append_markdown",
                {"path": "ProjectRaw/DailyReports/2026-05-14.md", "content": "- extra\n", "target": "eof"},
            )

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["operation"], "append")

    def test_prompts_and_resources_are_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            prompts = backend.list_prompts()
            resources = backend.list_resources()
            prompt = backend.get_prompt("onboard_agent_to_vault", {})
            rules = backend.read_resource("governance://rules/root")

            self.assertIn("onboard_agent_to_vault", [item["name"] for item in prompts])
            self.assertIn("prepare_registry_repair", [item["name"] for item in prompts])
            self.assertIn("governance_review_snapshot_upgrade", [item["name"] for item in prompts])
            self.assertIn("governance_review_promotion_proposal", [item["name"] for item in prompts])
            self.assertIn("governance://rules/root", [item["uri"] for item in resources])
            self.assertIn("governance://registry/governance-proposals", [item["uri"] for item in resources])
            self.assertIn("governance://registry/promotion-queue", [item["uri"] for item in resources])
            self.assertIn("governance://local/compatibility-status", [item["uri"] for item in resources])
            self.assertIn("governance://snapshot/version", [item["uri"] for item in resources])
            self.assertIn("governance://registry/change-ledger", [item["uri"] for item in resources])
            self.assertIn("governance://dbms/index/file-index", [item["uri"] for item in resources])
            self.assertIn("governance://dbms/index/topic-summary", [item["uri"] for item in resources])
            self.assertEqual(prompt["messages"][0]["role"], "user")
            self.assertIn("read `RULES.md`", prompt["messages"][0]["content"]["text"])
            self.assertIn("This is the single rule source for the governed vault.", rules["contents"][0]["text"])

            queue_resource = backend.read_resource("governance://registry/promotion-queue")
            compat_resource = backend.read_resource("governance://local/compatibility-status")
            ledger_resource = backend.read_resource("governance://registry/change-ledger")
            self.assertIn('"items"', queue_resource["contents"][0]["text"])
            self.assertIn('"status"', compat_resource["contents"][0]["text"])
            self.assertIn('"bootstrap"', ledger_resource["contents"][0]["text"])

    def test_vault_user_resource_list_hides_sensitive_governance_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")
            resource_uris = [item["uri"] for item in backend.list_resources()]

            self.assertIn("governance://rules/root", resource_uris)
            self.assertIn("governance://registry/vault", resource_uris)
            self.assertIn("governance://dbms/index/findings", resource_uris)
            self.assertIn("governance://dbms/index/file-index", resource_uris)
            self.assertNotIn("governance://registry/agent-roster", resource_uris)
            self.assertNotIn("governance://registry/governance-proposals", resource_uris)
            self.assertNotIn("governance://registry/change-ledger", resource_uris)
            self.assertNotIn("governance://local/compatibility-status", resource_uris)

    def test_vault_user_cannot_read_hidden_resource(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")
            with self.assertRaises(ValueError):
                backend.read_resource("governance://registry/change-ledger")

    def test_read_resource_rejects_symlinked_file_backing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = base / "vault"
            self._install_and_seed_vault(vault)
            outside = base / "outside-compatibility-status.json"
            outside.write_text('{"status":"outside"}\n', encoding="utf-8")
            compat_path = vault / "LocalOverrides" / "compatibility-status.json"
            compat_path.unlink()
            try:
                compat_path.symlink_to(outside)
            except OSError:
                self.skipTest("Cannot create a symlink on this system")

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            with self.assertRaises(ValueError):
                backend.read_resource("governance://local/compatibility-status")

    def test_system_maintainer_can_rebuild_dbms_index_and_read_dbms_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            orphan_dir = vault / "ProjectRaw" / "Loose"
            orphan_dir.mkdir(parents=True, exist_ok=True)
            (orphan_dir / "orphan.md").write_text("# Orphan\n", encoding="utf-8")

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            result = backend.call_tool("governance_rebuild_dbms_index", {})

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["exitCode"], 0)
            self.assertIn("DBMS_INDEX_REBUILT", result["structuredContent"]["stdout"])
            self.assertEqual(result["structuredContent"]["state"]["last_task_type"], "index_rebuild")
            self.assertTrue(result["structuredContent"]["reportPath"].endswith("-index-audit-report.md"))
            self.assertTrue((vault / result["structuredContent"]["reportPath"]).exists())

            file_index_resource = backend.read_resource("governance://dbms/index/file-index")
            topic_summary_resource = backend.read_resource("governance://dbms/index/topic-summary")
            index_state_resource = backend.read_resource("governance://dbms/state/last-index-run")
            latest_report_resource = backend.read_resource("governance://dbms/reports/latest-index-audit")

            self.assertIn('"path": "20-KnowledgeHub/Python/index.md"', file_index_resource["contents"][0]["text"])
            self.assertIn('"topics"', topic_summary_resource["contents"][0]["text"])
            self.assertIn('"last_task_type": "index_rebuild"', index_state_resource["contents"][0]["text"])
            self.assertIn("# DBMS Index Audit Report", latest_report_resource["contents"][0]["text"])

            ledger_lines = [line for line in (vault / ".knowledge-registry" / "change-ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(json.loads(ledger_lines[-1])["operation"], "index_rebuild")

    def test_latest_dbms_report_resource_does_not_follow_paths_outside_vault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            outside_report = Path(tmp) / "outside-report.md"
            outside_report.write_text("SENSITIVE_OUTSIDE_REPORT\n", encoding="utf-8")

            index_state_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-index-run.json"
            index_state = json.loads(index_state_path.read_text(encoding="utf-8"))
            index_state["last_report_path"] = str(outside_report)
            index_state_path.write_text(json.dumps(index_state, ensure_ascii=False, indent=2), encoding="utf-8")

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            report_resource = backend.read_resource("governance://dbms/reports/latest-index-audit")

            self.assertNotIn("SENSITIVE_OUTSIDE_REPORT", report_resource["contents"][0]["text"])

    def test_latest_dbms_report_resource_ignores_non_audit_report_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            reports_dir = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "reports"
            audit_report = reports_dir / "2026-04-20-index-audit-report.md"
            audit_report.write_text("# DBMS Index Audit Report\n\nVALID_AUDIT\n", encoding="utf-8")

            index_state_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-index-run.json"
            index_state = json.loads(index_state_path.read_text(encoding="utf-8"))
            index_state["last_report_path"] = "01-Workflow/Knowledge-Governance/DBMS/reports/README.md"
            index_state_path.write_text(json.dumps(index_state, ensure_ascii=False, indent=2), encoding="utf-8")

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            report_resource = backend.read_resource("governance://dbms/reports/latest-index-audit")

            self.assertIn("VALID_AUDIT", report_resource["contents"][0]["text"])

    def test_latest_dbms_report_resource_ignores_symlinked_audit_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            reports_dir = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "reports"
            outside_report = Path(tmp) / "outside-index-audit-report.md"
            outside_report.write_text("SENSITIVE_SYMLINK_TARGET\n", encoding="utf-8")
            symlink_report = reports_dir / "9999-12-31-index-audit-report.md"
            try:
                symlink_report.symlink_to(outside_report)
            except (OSError, NotImplementedError, PermissionError):
                self.skipTest("symlinks are not available in this environment")

            audit_report = reports_dir / "2026-04-20-index-audit-report.md"
            audit_report.write_text("# DBMS Index Audit Report\n\nVALID_AUDIT\n", encoding="utf-8")

            index_state_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-index-run.json"
            index_state = json.loads(index_state_path.read_text(encoding="utf-8"))
            index_state["last_report_path"] = None
            index_state_path.write_text(json.dumps(index_state, ensure_ascii=False, indent=2), encoding="utf-8")

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            report_resource = backend.read_resource("governance://dbms/reports/latest-index-audit")

            self.assertIn("VALID_AUDIT", report_resource["contents"][0]["text"])
            self.assertNotIn("SENSITIVE_SYMLINK_TARGET", report_resource["contents"][0]["text"])

    def test_system_maintainer_can_reconcile_dbms_state_via_mcp_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            reports_dir = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            index_report = reports_dir / "2026-04-20-index-audit-report.md"
            archive_report = reports_dir / "2026-04-20-archive-review.md"
            index_report.write_text("# Index Audit Report\n", encoding="utf-8")
            archive_report.write_text("# Archive Review\n", encoding="utf-8")

            index_state_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-index-run.json"
            index_state = json.loads(index_state_path.read_text(encoding="utf-8"))
            index_state.update(
                {
                    "version": "1.3",
                    "last_index_run": "2026-04-20T05:00:00+00:00",
                    "last_actor": "db-admin-agent",
                    "last_task_type": "index_rebuild",
                    "last_report_path": "01-Workflow/Knowledge-Governance/DBMS/reports/missing-index-report.md",
                    "last_status": "complete-zero-findings",
                    "total_files": 100,
                    "total_findings": 0,
                    "findings_by_type": {},
                }
            )
            index_state_path.write_text(json.dumps(index_state, ensure_ascii=False, indent=2), encoding="utf-8")

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            result = backend.call_tool("governance_reconcile_dbms_state", {})

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["exitCode"], 0)
            self.assertIn("DBMS_STATE_RECONCILED", result["structuredContent"]["stdout"])
            self.assertEqual(
                result["structuredContent"]["indexState"]["last_report_path"],
                "01-Workflow/Knowledge-Governance/DBMS/reports/2026-04-20-index-audit-report.md",
            )
            self.assertEqual(result["structuredContent"]["dbmsState"]["last_status"], "state-reconciled")
            self.assertTrue(result["structuredContent"]["reportPath"].endswith("-state-reconciliation.md"))
            self.assertTrue((vault / result["structuredContent"]["reportPath"]).exists())

            ledger_lines = [line for line in (vault / ".knowledge-registry" / "change-ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(json.loads(ledger_lines[-1])["operation"], "state_reconcile")

    def test_propose_registry_update_persists_governance_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            result = backend.call_tool(
                "governance_propose_registry_update",
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

    def test_propose_registry_update_tool_schema_matches_response_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            tool = next(item for item in backend.list_tools() if item["name"] == "governance_propose_registry_update")

            self.assertEqual(set(tool["outputSchema"]["properties"].keys()), {"proposal"})

    def test_request_snapshot_review_persists_governance_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            result = backend.call_tool("governance_request_snapshot_review", {"summary": "Request snapshot review before upgrade"})

            self.assertFalse(result["isError"])
            proposal = result["structuredContent"]["proposal"]
            self.assertEqual(proposal["proposal_type"], "snapshot_upgrade")

    def test_system_maintainer_can_apply_snapshot_upgrade_with_explicit_approval_and_pending_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            maintainer_backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            request_result = maintainer_backend.call_tool(
                "governance_request_snapshot_review",
                {"summary": "Request snapshot review before upgrade"},
            )
            proposal_id = request_result["structuredContent"]["proposal"]["proposal_id"]

            owner_backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            result = owner_backend.call_tool(
                "governance_apply_snapshot_upgrade",
                {
                    "summary": "Apply latest system snapshot",
                    "proposal_id": proposal_id,
                    "approval": self._snapshot_approval(
                        vault,
                        evidence="Manual approval recorded for requested snapshot apply",
                    ),
                },
            )

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["governanceProposal"]["status"], "applied")
            self.assertEqual(result["structuredContent"]["governanceProposal"]["approval_evidence"]["approved_by"], "owner@example.com")

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
                "governance_create_promotion_proposal",
                {
                    "topic_id": "topic.unapproved",
                    "source_path": "10-Curation/Unapproved/summary.md",
                    "candidate_path": "20-KnowledgeHub/Unapproved/index.md",
                    "summary": "Create but do not approve",
                },
            )["structuredContent"]["proposal"]

            owner_backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            result = owner_backend.call_tool(
                "governance_apply_promotion_proposal",
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
                "governance_review_promotion_proposal",
                {
                    "proposal_id": "proposal.missing",
                    "decision": "approve",
                    "summary": "Missing proposal",
                    "approval": {
                        "approved_by": "owner@example.com",
                        "approved_at": "2026-05-13T12:00:00Z",
                        "evidence": "Manual approval recorded for canonical-impacting review",
                    },
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
                "governance_create_promotion_proposal",
                {
                    "topic_id": "topic.duplicate-apply",
                    "source_path": "10-Curation/DuplicateApply/summary.md",
                    "candidate_path": "20-KnowledgeHub/DuplicateApply/index.md",
                    "summary": "Duplicate apply scenario",
                },
            )["structuredContent"]["proposal"]["proposal_id"]

            owner_backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            owner_backend.call_tool(
                "governance_review_promotion_proposal",
                {
                    "proposal_id": proposal_id,
                    "decision": "approve",
                    "summary": "Approved",
                    "approval": {
                        "approved_by": "owner@example.com",
                        "approved_at": "2026-05-13T12:00:00Z",
                        "evidence": "Manual approval recorded for canonical-impacting review",
                    },
                },
            )
            owner_backend.call_tool(
                "governance_apply_promotion_proposal",
                {
                    "proposal_id": proposal_id,
                    "summary": "First apply",
                },
            )
            duplicate = owner_backend.call_tool(
                "governance_apply_promotion_proposal",
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
                "governance_apply_registry_update",
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
                "governance_apply_registry_update",
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
            result = backend.call_tool("governance_review_snapshot_upgrade", {})

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["status"], "review-needed")
            self.assertTrue(result["structuredContent"]["upgradeAvailable"])

    def test_vault_maintainer_can_create_promotion_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            result = backend.call_tool(
                "governance_create_promotion_proposal",
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
                "governance_create_promotion_proposal",
                {
                    "topic_id": "topic.python",
                    "source_path": "20-KnowledgeHub/Python/index.md",
                    "candidate_path": "20-KnowledgeHub/Python/index.md",
                    "summary": "Promote Python index",
                },
            )
            result = backend.call_tool("governance_list_promotion_queue", {})

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["total"], 1)
            self.assertEqual(result["structuredContent"]["count"], 1)
            self.assertEqual(result["structuredContent"]["offset"], 0)
            self.assertEqual(result["structuredContent"]["has_more"], False)
            self.assertIsNone(result["structuredContent"]["next_offset"])
            self.assertEqual(result["structuredContent"]["items"][0]["status"], "proposed")

    def test_system_maintainer_can_approve_promotion_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            maintainer_backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            proposal_result = maintainer_backend.call_tool(
                "governance_create_promotion_proposal",
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
                "governance_review_promotion_proposal",
                {
                    "proposal_id": proposal_id,
                    "decision": "approve",
                    "summary": "Promotion approved for canonical review",
                    "approval": {
                        "approved_by": "owner@example.com",
                        "approved_at": "2026-05-13T12:00:00Z",
                        "evidence": "Manual approval recorded for canonical-impacting review",
                    },
                },
            )

            self.assertFalse(review_result["isError"])
            self.assertEqual(review_result["structuredContent"]["proposal"]["status"], "approved")
            self.assertEqual(review_result["structuredContent"]["proposal"]["reviewed_by"], "owner@example.com")

            queue = json.loads((vault / ".knowledge-registry" / "promotion-queue.json").read_text(encoding="utf-8"))
            item = next(item for item in queue["items"] if item["proposal_id"] == proposal_id)
            self.assertEqual(item["status"], "approved")
            self.assertEqual(item["approval_evidence"]["approved_by"], "owner@example.com")

            ledger_lines = [line for line in (vault / ".knowledge-registry" / "change-ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            last_entry = json.loads(ledger_lines[-1])
            self.assertEqual(last_entry["operation"], "promotion_proposal_review")
            self.assertEqual(last_entry["topic_id"], "topic.python")
            self.assertEqual(last_entry["approval_evidence"]["approved_by"], "owner@example.com")

    def test_system_maintainer_cannot_review_promotion_proposal_without_approval_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            maintainer_backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            proposal_result = maintainer_backend.call_tool(
                "governance_create_promotion_proposal",
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
                "governance_review_promotion_proposal",
                {
                    "proposal_id": proposal_id,
                    "decision": "approve",
                    "summary": "Promotion approved for canonical review",
                },
            )

            self.assertTrue(review_result["isError"])
            self.assertEqual(review_result["structuredContent"]["decision"], "allow")
            self.assertTrue(review_result["structuredContent"]["requires_approval"])
            self.assertIn("explicit approval evidence", review_result["content"][0]["text"])

    def test_system_maintainer_cannot_review_promotion_proposal_with_mismatched_approval_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            maintainer_backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            proposal_result = maintainer_backend.call_tool(
                "governance_create_promotion_proposal",
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
                "governance_review_promotion_proposal",
                {
                    "proposal_id": proposal_id,
                    "decision": "approve",
                    "summary": "Promotion approved for canonical review",
                    "approval": {
                        "approved_by": "maintainer@example.com",
                        "approved_at": "2026-05-13T12:00:00Z",
                        "evidence": "Spoofed approval identity",
                    },
                },
            )

            self.assertTrue(review_result["isError"])
            self.assertIn("must match the authenticated subject", review_result["content"][0]["text"])

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
                "governance_create_promotion_proposal",
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
                "governance_review_promotion_proposal",
                {
                    "proposal_id": proposal_id,
                    "decision": "approve",
                    "summary": "Promotion approved",
                    "approval": {
                        "approved_by": "owner@example.com",
                        "approved_at": "2026-05-13T12:00:00Z",
                        "evidence": "Manual approval recorded for canonical-impacting review",
                    },
                },
            )
            apply_result = owner_backend.call_tool(
                "governance_apply_promotion_proposal",
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

    def test_list_topic_findings_pagination_respects_limit_and_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            findings_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "findings.json"
            findings = json.loads(findings_path.read_text(encoding="utf-8"))
            for i in range(1, 6):
                findings["items"].append(
                    {
                        "finding_id": f"finding.pag{i}",
                        "finding_type": "frontmatter_missing",
                        "topic_id": "topic.python",
                        "path": f"20-KnowledgeHub/Python/page{i}.md",
                        "severity": "medium",
                        "status": "open",
                    }
                )
            findings_path.write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")

            page1 = backend.call_tool("governance_list_topic_findings", {"topic_id": "topic.python", "limit": 2, "offset": 0})
            self.assertEqual(page1["structuredContent"]["total"], 6)
            self.assertEqual(page1["structuredContent"]["count"], 2)
            self.assertEqual(page1["structuredContent"]["offset"], 0)
            self.assertTrue(page1["structuredContent"]["has_more"])
            self.assertEqual(page1["structuredContent"]["next_offset"], 2)

            page2 = backend.call_tool("governance_list_topic_findings", {"topic_id": "topic.python", "limit": 2, "offset": 2})
            self.assertEqual(page2["structuredContent"]["count"], 2)
            self.assertEqual(page2["structuredContent"]["offset"], 2)
            self.assertTrue(page2["structuredContent"]["has_more"])
            self.assertEqual(page2["structuredContent"]["next_offset"], 4)

            page3 = backend.call_tool("governance_list_topic_findings", {"topic_id": "topic.python", "limit": 2, "offset": 4})
            self.assertEqual(page3["structuredContent"]["count"], 2)
            self.assertEqual(page3["structuredContent"]["offset"], 4)
            self.assertFalse(page3["structuredContent"]["has_more"])
            self.assertIsNone(page3["structuredContent"]["next_offset"])

    def test_list_promotion_queue_pagination_respects_limit_and_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            for i in range(1, 6):
                backend.call_tool(
                    "governance_create_promotion_proposal",
                    {
                        "topic_id": "topic.python",
                        "source_path": f"20-KnowledgeHub/Python/page{i}.md",
                        "candidate_path": f"20-KnowledgeHub/Python/page{i}.md",
                        "summary": f"Promote page {i}",
                    },
                )

            page1 = backend.call_tool("governance_list_promotion_queue", {"limit": 2, "offset": 0})
            self.assertEqual(page1["structuredContent"]["total"], 5)
            self.assertEqual(page1["structuredContent"]["count"], 2)
            self.assertEqual(page1["structuredContent"]["offset"], 0)
            self.assertTrue(page1["structuredContent"]["has_more"])
            self.assertEqual(page1["structuredContent"]["next_offset"], 2)

            page2 = backend.call_tool("governance_list_promotion_queue", {"limit": 2, "offset": 2})
            self.assertEqual(page2["structuredContent"]["count"], 2)
            self.assertEqual(page2["structuredContent"]["offset"], 2)
            self.assertTrue(page2["structuredContent"]["has_more"])
            self.assertEqual(page2["structuredContent"]["next_offset"], 4)

            page3 = backend.call_tool("governance_list_promotion_queue", {"limit": 2, "offset": 4})
            self.assertEqual(page3["structuredContent"]["count"], 1)
            self.assertEqual(page3["structuredContent"]["offset"], 4)
            self.assertFalse(page3["structuredContent"]["has_more"])
            self.assertIsNone(page3["structuredContent"]["next_offset"])

    def test_search_topics_pagination_edge_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            registry_path = vault / ".knowledge-registry" / "vault-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            for i in range(1, 4):
                registry["topics"].append(
                    {
                        "topic_id": f"topic.edge{i}",
                        "title": f"Edge Topic {i}",
                        "aliases": [f"edge{i}"],
                        "status": "active",
                        "source_domains": ["test"],
                        "intake_paths": [f"ProjectRaw/Edge{i}"],
                        "curation_paths": [f"20-KnowledgeHub/Edge{i}"],
                        "canonical_home": None,
                        "related_topics": [],
                        "upstream_bindings": [],
                    }
                )
            registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")

            # offset beyond total returns empty, has_more=False
            beyond = backend.call_tool("governance_search_topics", {"query": "edge", "limit": 2, "offset": 10})
            self.assertEqual(beyond["structuredContent"]["total"], 3)
            self.assertEqual(beyond["structuredContent"]["count"], 0)
            self.assertEqual(beyond["structuredContent"]["offset"], 10)
            self.assertFalse(beyond["structuredContent"]["has_more"])
            self.assertIsNone(beyond["structuredContent"]["next_offset"])

            # limit larger than total returns all, has_more=False
            large_limit = backend.call_tool("governance_search_topics", {"query": "edge", "limit": 100, "offset": 0})
            self.assertEqual(large_limit["structuredContent"]["total"], 3)
            self.assertEqual(large_limit["structuredContent"]["count"], 3)
            self.assertFalse(large_limit["structuredContent"]["has_more"])
            self.assertIsNone(large_limit["structuredContent"]["next_offset"])

            # default values (no limit/offset provided)
            defaults = backend.call_tool("governance_search_topics", {"query": "edge"})
            self.assertEqual(defaults["structuredContent"]["total"], 3)
            self.assertEqual(defaults["structuredContent"]["count"], 3)
            self.assertEqual(defaults["structuredContent"]["offset"], 0)
            self.assertFalse(defaults["structuredContent"]["has_more"])
            self.assertIsNone(defaults["structuredContent"]["next_offset"])

    def test_pagination_parameter_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")

            invalid_limit = backend.call_tool("governance_search_topics", {"query": "python", "limit": 0})
            self.assertTrue(invalid_limit["isError"])
            self.assertIn("limit must be >= 1", invalid_limit["content"][0]["text"])

            invalid_offset = backend.call_tool("governance_search_topics", {"query": "python", "offset": -1})
            self.assertTrue(invalid_offset["isError"])
            self.assertIn("offset must be >= 0", invalid_offset["content"][0]["text"])

    def test_search_topics_pagination_respects_limit_and_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            registry_path = vault / ".knowledge-registry" / "vault-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            for i in range(1, 6):
                registry["topics"].append(
                    {
                        "topic_id": f"topic.pag{i}",
                        "title": f"Pagination Topic {i}",
                        "aliases": [f"pag{i}"],
                        "status": "active",
                        "source_domains": ["test"],
                        "intake_paths": [f"ProjectRaw/Pag{i}"],
                        "curation_paths": [f"20-KnowledgeHub/Pag{i}"],
                        "canonical_home": None,
                        "related_topics": [],
                        "upstream_bindings": [],
                    }
                )
            registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

            backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")

            page1 = backend.call_tool("governance_search_topics", {"query": "pag", "limit": 2, "offset": 0})
            self.assertEqual(page1["structuredContent"]["total"], 5)
            self.assertEqual(page1["structuredContent"]["count"], 2)
            self.assertEqual(page1["structuredContent"]["offset"], 0)
            self.assertTrue(page1["structuredContent"]["has_more"])
            self.assertEqual(page1["structuredContent"]["next_offset"], 2)

            page2 = backend.call_tool("governance_search_topics", {"query": "pag", "limit": 2, "offset": 2})
            self.assertEqual(page2["structuredContent"]["count"], 2)
            self.assertEqual(page2["structuredContent"]["offset"], 2)
            self.assertTrue(page2["structuredContent"]["has_more"])
            self.assertEqual(page2["structuredContent"]["next_offset"], 4)

            page3 = backend.call_tool("governance_search_topics", {"query": "pag", "limit": 2, "offset": 4})
            self.assertEqual(page3["structuredContent"]["count"], 1)
            self.assertEqual(page3["structuredContent"]["offset"], 4)
            self.assertFalse(page3["structuredContent"]["has_more"])
            self.assertIsNone(page3["structuredContent"]["next_offset"])

    def test_vault_maintainer_cannot_review_promotion_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            maintainer_backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            proposal_result = maintainer_backend.call_tool(
                "governance_create_promotion_proposal",
                {
                    "topic_id": "topic.python",
                    "source_path": "20-KnowledgeHub/Python/index.md",
                    "candidate_path": "20-KnowledgeHub/Python/index.md",
                    "summary": "Promote Python index",
                },
            )
            proposal_id = proposal_result["structuredContent"]["proposal"]["proposal_id"]

            result = maintainer_backend.call_tool(
                "governance_review_promotion_proposal",
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
                "governance_create_promotion_proposal",
                {
                    "topic_id": "topic.promote-blocked",
                    "source_path": "10-Curation/PromoteBlocked/summary.md",
                    "candidate_path": "20-KnowledgeHub/PromoteBlocked/index.md",
                    "summary": "Prepare blocked promotion",
                },
            )
            proposal_id = proposal_result["structuredContent"]["proposal"]["proposal_id"]

            result = maintainer_backend.call_tool(
                "governance_apply_promotion_proposal",
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
                "governance_create_promotion_proposal",
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
            result = backend.call_tool(
                "governance_apply_snapshot_upgrade",
                {
                    "summary": "Apply latest system snapshot",
                    "approval": self._snapshot_approval(
                        vault,
                        evidence="Manual approval recorded for L4 snapshot apply",
                    ),
                },
            )

            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["status"], "compatible")

            compat = json.loads(compat_path.read_text(encoding="utf-8"))
            version = json.loads((vault / ".dbms-system" / "version.json").read_text(encoding="utf-8"))
            expected_ref = version.get("snapshot_ref") or version.get("release_tag") or version.get("source_commit")
            self.assertEqual(compat["system_tag"], expected_ref)
            self.assertEqual(compat["status"], "compatible")
            self.assertEqual(compat["approval_evidence"]["approved_by"], "owner@example.com")

            ledger_lines = [line for line in (vault / ".knowledge-registry" / "change-ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            last_entry = json.loads(ledger_lines[-1])
            self.assertEqual(last_entry["operation"], "system_snapshot_apply")
            self.assertTrue(last_entry["registry_updated"])
            self.assertEqual(last_entry["approval_evidence"]["approved_by"], "owner@example.com")

    def test_system_maintainer_cannot_apply_snapshot_upgrade_without_approval_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            result = backend.call_tool("governance_apply_snapshot_upgrade", {"summary": "Apply latest system snapshot"})

            self.assertTrue(result["isError"])
            self.assertEqual(result["structuredContent"]["decision"], "allow")
            self.assertTrue(result["structuredContent"]["requires_approval"])
            self.assertIn("approved proposal or explicit approval evidence", result["content"][0]["text"])

    def test_system_maintainer_cannot_apply_snapshot_upgrade_with_mismatched_approval_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            result = backend.call_tool(
                "governance_apply_snapshot_upgrade",
                {
                    "summary": "Apply latest system snapshot",
                    "approval": self._snapshot_approval(
                        vault,
                        approved_by="maintainer@example.com",
                        evidence="Spoofed approval identity",
                    ),
                },
            )

            self.assertTrue(result["isError"])
            self.assertIn("must match the authenticated subject", result["content"][0]["text"])

    def test_system_maintainer_cannot_apply_snapshot_upgrade_with_unrelated_approved_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            maintainer_backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            proposal_result = maintainer_backend.call_tool(
                "governance_create_promotion_proposal",
                {
                    "topic_id": "topic.python",
                    "source_path": "20-KnowledgeHub/Python/index.md",
                    "candidate_path": "20-KnowledgeHub/Python/index.md",
                    "summary": "Promote Python index",
                },
            )
            proposal_id = proposal_result["structuredContent"]["proposal"]["proposal_id"]

            owner_backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            owner_backend.call_tool(
                "governance_review_promotion_proposal",
                {
                    "proposal_id": proposal_id,
                    "decision": "approve",
                    "summary": "Promotion approved",
                    "approval": {
                        "approved_by": "owner@example.com",
                        "approved_at": "2026-05-13T12:00:00Z",
                        "evidence": "Manual approval recorded for canonical-impacting review",
                    },
                },
            )

            result = owner_backend.call_tool(
                "governance_apply_snapshot_upgrade",
                {
                    "summary": "Attempt snapshot apply with wrong proposal type",
                    "proposal_id": proposal_id,
                },
            )

            self.assertTrue(result["isError"])
            self.assertIn("snapshot_upgrade", result["content"][0]["text"])

    def test_system_maintainer_cannot_apply_snapshot_upgrade_with_stale_snapshot_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            maintainer_backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            request_result = maintainer_backend.call_tool(
                "governance_request_snapshot_review",
                {"summary": "Request snapshot review before upgrade"},
            )
            proposal_id = request_result["structuredContent"]["proposal"]["proposal_id"]

            proposals_path = vault / ".knowledge-registry" / "governance-proposals.json"
            proposals = json.loads(proposals_path.read_text(encoding="utf-8"))
            for item in proposals["items"]:
                if item["proposal_id"] == proposal_id:
                    item["status"] = "approved"
                    item["reviewed_by"] = "owner@example.com"
                    item["reviewed_at"] = "2026-05-13T12:00:00Z"
                    item["details"]["snapshotRef"] = "stale-snapshot-ref"
                    break
            proposals_path.write_text(json.dumps(proposals, ensure_ascii=False, indent=2), encoding="utf-8")

            owner_backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            result = owner_backend.call_tool(
                "governance_apply_snapshot_upgrade",
                {
                    "summary": "Attempt stale snapshot apply",
                    "proposal_id": proposal_id,
                },
            )

            self.assertTrue(result["isError"])
            self.assertIn("does not match the current snapshot review", result["content"][0]["text"])

    def test_system_maintainer_cannot_apply_snapshot_upgrade_with_replayed_snapshot_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
            result = backend.call_tool(
                "governance_apply_snapshot_upgrade",
                {
                    "summary": "Attempt replayed snapshot approval",
                    "approval": self._snapshot_approval(vault, snapshot_ref="stale-snapshot-ref"),
                },
            )

            self.assertTrue(result["isError"])
            self.assertIn("approval.snapshot_ref must match the current snapshot review", result["content"][0]["text"])

    def test_vault_maintainer_cannot_apply_snapshot_upgrade_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
            result = backend.call_tool("governance_apply_snapshot_upgrade", {"summary": "Attempt direct snapshot apply"})

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
            self.assertIn("governance_search_topics", tool_names)
            self.assertNotIn("governance_validate_data_repo", tool_names)

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
            self.assertIn("governance_whoami", tool_names)
            self.assertNotIn("governance_apply_snapshot_upgrade", tool_names)

    def test_stdio_server_lists_dbms_tools_and_resources_for_system_maintainer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_and_seed_vault(vault)

            messages = _run_stdio_sequence(
                vault,
                "owner@example.com",
                "oauth",
                [
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                    {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}},
                ],
            )

            tools_response = next(item for item in messages if item.get("id") == 2)
            resources_response = next(item for item in messages if item.get("id") == 3)
            tool_names = [item["name"] for item in tools_response["result"]["tools"]]
            resource_uris = [item["uri"] for item in resources_response["result"]["resources"]]

            self.assertIn("governance_rebuild_dbms_index", tool_names)
            self.assertIn("governance_reconcile_dbms_state", tool_names)
            self.assertIn("governance://dbms/index/file-index", resource_uris)
            self.assertIn("governance://dbms/index/topic-summary", resource_uris)
            self.assertIn("governance://dbms/state/last-index-run", resource_uris)
            self.assertIn("governance://dbms/reports/latest-index-audit", resource_uris)

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
                            "name": "governance_create_promotion_proposal",
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
                            "name": "governance_review_promotion_proposal",
                            "arguments": {
                                "proposal_id": proposal_id,
                                "decision": "approve",
                                "summary": "Approve via stdio",
                                "approval": {
                                    "approved_by": "owner@example.com",
                                    "approved_at": "2026-05-13T12:00:00Z",
                                    "evidence": "Manual approval recorded for canonical-impacting review",
                                },
                            },
                        },
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "governance_apply_promotion_proposal",
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
