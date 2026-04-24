from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ValidateDataRepoTests(unittest.TestCase):
    def _install_vault(self, vault: Path) -> None:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
            check=True,
            cwd=ROOT,
        )

    def test_validate_data_repo_accepts_consistent_governance_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_vault(vault)

            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "validate_data_repo.py"), str(vault)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("VALIDATE_DATA_REPO_OK", result.stdout)

    def test_validate_data_repo_rejects_promotion_queue_item_without_matching_governance_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            self._install_vault(vault)

            queue_path = vault / ".knowledge-registry" / "promotion-queue.json"
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            queue["items"].append(
                {
                    "proposal_id": "proposal.missing",
                    "topic_id": "topic.example-governance",
                    "source_path": "01-Workflow/Knowledge-Governance/00-Agent-Onboarding.md",
                    "candidate_path": "20-KnowledgeHub/00-Example-Index.md",
                    "status": "approved",
                    "submitted_by": "maintainer@example.com",
                    "submitted_at": "2026-04-24T00:00:00Z",
                    "reviewed_by": "owner@example.com",
                    "reviewed_at": "2026-04-24T01:00:00Z"
                }
            )
            queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "validate_data_repo.py"), str(vault)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("promotion queue item references unknown governance proposal", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
