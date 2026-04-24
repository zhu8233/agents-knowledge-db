from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DbmsStateReconcileTests(unittest.TestCase):
    def test_reconcile_repairs_missing_index_report_and_updates_dbms_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

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

            dbms_state_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-dbms-run.json"
            dbms_state_path.parent.mkdir(parents=True, exist_ok=True)
            dbms_state = {
                "version": "1.1",
                "last_dbms_run": "2026-04-20T04:00:00+00:00",
                "last_actor": "db-admin-agent",
                "last_task_type": "registry_repair",
                "last_report_path": "01-Workflow/Knowledge-Governance/DBMS/reports/2026-04-20-registry-coverage-audit.md",
                "last_status": "stale-state",
            }
            dbms_state.update(
                dbms_state
            )
            dbms_state_path.write_text(json.dumps(dbms_state, ensure_ascii=False, indent=2), encoding="utf-8")

            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "reconcile_dbms_state.py"), str(vault)],
                check=True,
                cwd=ROOT,
            )

            new_index_state = json.loads(index_state_path.read_text(encoding="utf-8"))
            new_dbms_state = json.loads(dbms_state_path.read_text(encoding="utf-8"))

            self.assertEqual(
                new_index_state["last_report_path"],
                "01-Workflow/Knowledge-Governance/DBMS/reports/2026-04-20-index-audit-report.md",
            )
            self.assertEqual(new_index_state["last_status"], "complete-zero-findings")

            self.assertEqual(new_dbms_state["last_task_type"], "system_guard")
            self.assertEqual(new_dbms_state["last_status"], "state-reconciled")
            self.assertTrue(new_dbms_state["last_report_path"].endswith("-state-reconciliation.md"))
            self.assertTrue((vault / new_dbms_state["last_report_path"]).exists())

            ledger_path = vault / ".knowledge-registry" / "change-ledger.jsonl"
            lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertTrue(any('"operation": "state_reconcile"' in line for line in lines))


if __name__ == "__main__":
    unittest.main()
