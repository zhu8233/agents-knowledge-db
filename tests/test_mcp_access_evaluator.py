from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class McpAccessEvaluatorTests(unittest.TestCase):
    def _install_vault(self, vault: Path) -> None:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
            check=True,
            cwd=ROOT,
        )

    def _evaluate_access(
        self,
        vault: Path,
        *,
        subject_id: str,
        auth_mode: str,
        tool: str,
        risk_level: str,
        target_layer: str,
    ) -> dict:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "evaluate_mcp_access.py"),
                str(vault),
                "--subject-id",
                subject_id,
                "--auth-mode",
                auth_mode,
                "--tool",
                tool,
                "--risk-level",
                risk_level,
                "--target-layer",
                target_layer,
            ],
            check=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_install_with_snapshot_includes_mcp_access_policy_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_vault(vault)

            self.assertTrue((vault / "LocalOverrides" / "mcp-access-policy.json").exists())

    def test_system_maintainer_can_apply_registry_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_vault(vault)

            result = self._evaluate_access(
                vault,
                subject_id="owner@example.com",
                auth_mode="oauth",
                tool="governance_apply_registry_update",
                risk_level="L2",
                target_layer="system",
            )

            self.assertEqual(result["decision"], "allow")
            self.assertEqual(result["mapped_agent_id"], "human")
            self.assertEqual(result["effective_role"], "system-maintainer")
            self.assertFalse(result["requires_approval"])

    def test_repo_maintainer_is_forced_into_proposal_path_for_registry_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_vault(vault)

            result = self._evaluate_access(
                vault,
                subject_id="maintainer@example.com",
                auth_mode="oauth",
                tool="governance_apply_registry_update",
                risk_level="L2",
                target_layer="system",
            )

            self.assertEqual(result["decision"], "proposal-only")
            self.assertEqual(result["effective_role"], "vault-maintainer")
            self.assertEqual(result["suggested_tool"], "governance_propose_registry_update")

    def test_vault_user_cannot_run_dbms_admin_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_vault(vault)

            result = self._evaluate_access(
                vault,
                subject_id="reader@example.com",
                auth_mode="oauth",
                tool="governance_rebuild_dbms_index",
                risk_level="L2",
                target_layer="system",
            )

            self.assertEqual(result["decision"], "deny")
            self.assertEqual(result["effective_role"], "vault-user")

    def test_system_maintainer_can_run_dbms_admin_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_vault(vault)

            result = self._evaluate_access(
                vault,
                subject_id="owner@example.com",
                auth_mode="oauth",
                tool="governance_rebuild_dbms_index",
                risk_level="L2",
                target_layer="system",
            )

            self.assertEqual(result["decision"], "allow")
            self.assertEqual(result["effective_role"], "system-maintainer")
            self.assertFalse(result["requires_approval"])

    def test_vault_maintainer_cannot_run_dbms_admin_tool_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_vault(vault)

            result = self._evaluate_access(
                vault,
                subject_id="maintainer@example.com",
                auth_mode="oauth",
                tool="governance_rebuild_dbms_index",
                risk_level="L2",
                target_layer="system",
            )

            self.assertEqual(result["decision"], "deny")
            self.assertEqual(result["effective_role"], "vault-maintainer")

    def test_high_risk_system_action_requires_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_vault(vault)

            result = self._evaluate_access(
                vault,
                subject_id="owner@example.com",
                auth_mode="token",
                tool="governance_apply_snapshot_upgrade",
                risk_level="L4",
                target_layer="system",
            )

            self.assertEqual(result["decision"], "allow")
            self.assertTrue(result["requires_approval"])
            self.assertEqual(result["approval_reason"], "risk-threshold")

    def test_vault_maintainer_can_run_vault_scan_curation_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_vault(vault)

            result = self._evaluate_access(
                vault,
                subject_id="maintainer@example.com",
                auth_mode="oauth",
                tool="vault_scan_curation_gaps",
                risk_level="L1",
                target_layer="system",
            )

            self.assertEqual(result["decision"], "allow")
            self.assertEqual(result["effective_role"], "vault-maintainer")

    def test_vault_user_can_read_but_cannot_run_curation_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_vault(vault)

            read_result = self._evaluate_access(
                vault,
                subject_id="reader@example.com",
                auth_mode="oauth",
                tool="vault_read_markdown",
                risk_level="L0",
                target_layer="system",
            )
            scan_result = self._evaluate_access(
                vault,
                subject_id="reader@example.com",
                auth_mode="oauth",
                tool="vault_scan_curation_gaps",
                risk_level="L1",
                target_layer="system",
            )

            self.assertEqual(read_result["decision"], "allow")
            self.assertEqual(scan_result["decision"], "deny")
            self.assertEqual(scan_result["effective_role"], "vault-user")

    def test_vault_maintainer_snapshot_apply_suggests_snapshot_review_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_vault(vault)

            result = self._evaluate_access(
                vault,
                subject_id="maintainer@example.com",
                auth_mode="oauth",
                tool="governance_apply_snapshot_upgrade",
                risk_level="L4",
                target_layer="system",
            )

            self.assertEqual(result["decision"], "proposal-only")
            self.assertEqual(result["suggested_tool"], "governance_request_snapshot_review")


if __name__ == "__main__":
    unittest.main()
