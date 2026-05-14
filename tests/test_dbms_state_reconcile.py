from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DbmsStateReconcileTests(unittest.TestCase):
    def test_reconcile_state_handles_fresh_install_without_prior_index_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "reconcile_dbms_state.py"), str(vault)],
                check=True,
                cwd=ROOT,
            )

            index_state_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-index-run.json"
            dbms_state_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-dbms-run.json"
            index_state = json.loads(index_state_path.read_text(encoding="utf-8"))
            dbms_state = json.loads(dbms_state_path.read_text(encoding="utf-8"))

            self.assertIsNone(index_state["last_report_path"])
            self.assertEqual(index_state["last_status"], "not-run")
            self.assertEqual(dbms_state["last_status"], "state-reconciled")
            self.assertTrue((vault / dbms_state["last_report_path"]).exists())

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

    def test_reconcile_state_fails_when_broken_report_reference_has_no_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            index_state_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-index-run.json"
            index_state = json.loads(index_state_path.read_text(encoding="utf-8"))
            index_state.update(
                {
                    "last_report_path": "01-Workflow/Knowledge-Governance/DBMS/reports/missing-index-report.md",
                    "last_status": "complete-with-findings",
                }
            )
            index_state_path.write_text(json.dumps(index_state, ensure_ascii=False, indent=2), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "reconcile_dbms_state.py"), str(vault)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("No valid DBMS index audit report", result.stderr)

    def test_reconcile_state_rejects_outside_vault_report_path_and_uses_valid_audit_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            reports_dir = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            valid_report = reports_dir / "2026-04-20-index-audit-report.md"
            valid_report.write_text("# Index Audit Report\n", encoding="utf-8")

            outside_report = Path(tmp) / "outside-report.md"
            outside_report.write_text("OUTSIDE\n", encoding="utf-8")

            index_state_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-index-run.json"
            index_state = json.loads(index_state_path.read_text(encoding="utf-8"))
            index_state["last_report_path"] = str(outside_report)
            index_state_path.write_text(json.dumps(index_state, ensure_ascii=False, indent=2), encoding="utf-8")

            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "reconcile_dbms_state.py"), str(vault)],
                check=True,
                cwd=ROOT,
            )

            repaired_state = json.loads(index_state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                repaired_state["last_report_path"],
                "01-Workflow/Knowledge-Governance/DBMS/reports/2026-04-20-index-audit-report.md",
            )

    def test_reconcile_state_selects_audit_report_not_any_index_named_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            reports_dir = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            audit_report = reports_dir / "2026-04-20-index-audit-report.md"
            audit_report.write_text("# Index Audit Report\n", encoding="utf-8")
            notes_report = reports_dir / "topic-index-notes.md"
            notes_report.write_text("# Notes\n", encoding="utf-8")

            index_state_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-index-run.json"
            index_state = json.loads(index_state_path.read_text(encoding="utf-8"))
            index_state["last_report_path"] = "01-Workflow/Knowledge-Governance/DBMS/reports/missing-index-report.md"
            index_state_path.write_text(json.dumps(index_state, ensure_ascii=False, indent=2), encoding="utf-8")

            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "reconcile_dbms_state.py"), str(vault)],
                check=True,
                cwd=ROOT,
            )

            repaired_state = json.loads(index_state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                repaired_state["last_report_path"],
                "01-Workflow/Knowledge-Governance/DBMS/reports/2026-04-20-index-audit-report.md",
            )

    def test_reconcile_state_ignores_existing_non_audit_report_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            reports_dir = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            audit_report = reports_dir / "2026-04-20-index-audit-report.md"
            audit_report.write_text("# Index Audit Report\n", encoding="utf-8")

            index_state_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-index-run.json"
            index_state = json.loads(index_state_path.read_text(encoding="utf-8"))
            index_state["last_report_path"] = "01-Workflow/Knowledge-Governance/DBMS/reports/README.md"
            index_state_path.write_text(json.dumps(index_state, ensure_ascii=False, indent=2), encoding="utf-8")

            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "reconcile_dbms_state.py"), str(vault)],
                check=True,
                cwd=ROOT,
            )

            repaired_state = json.loads(index_state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                repaired_state["last_report_path"],
                "01-Workflow/Knowledge-Governance/DBMS/reports/2026-04-20-index-audit-report.md",
            )

    def test_reconcile_state_ignores_symlinked_audit_report_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            reports_dir = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            outside_report = Path(tmp) / "outside-index-audit-report.md"
            outside_report.write_text("OUTSIDE\n", encoding="utf-8")
            symlink_report = reports_dir / "9999-12-31-index-audit-report.md"
            try:
                symlink_report.symlink_to(outside_report)
            except (OSError, NotImplementedError, PermissionError):
                self.skipTest("symlinks are not available in this environment")

            audit_report = reports_dir / "2026-04-20-index-audit-report.md"
            audit_report.write_text("# Index Audit Report\n", encoding="utf-8")

            index_state_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-index-run.json"
            index_state = json.loads(index_state_path.read_text(encoding="utf-8"))
            index_state["last_report_path"] = "01-Workflow/Knowledge-Governance/DBMS/reports/missing-index-report.md"
            index_state_path.write_text(json.dumps(index_state, ensure_ascii=False, indent=2), encoding="utf-8")

            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "reconcile_dbms_state.py"), str(vault)],
                check=True,
                cwd=ROOT,
            )

            repaired_state = json.loads(index_state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                repaired_state["last_report_path"],
                "01-Workflow/Knowledge-Governance/DBMS/reports/2026-04-20-index-audit-report.md",
            )

    def test_reconcile_state_recreates_missing_reports_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            reports_dir = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "reports"
            if reports_dir.exists():
                for path in reports_dir.iterdir():
                    path.unlink()
                reports_dir.rmdir()

            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "reconcile_dbms_state.py"), str(vault)],
                check=True,
                cwd=ROOT,
            )

            dbms_state_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-dbms-run.json"
            dbms_state = json.loads(dbms_state_path.read_text(encoding="utf-8"))
            self.assertTrue(reports_dir.exists())
            self.assertTrue((vault / dbms_state["last_report_path"]).exists())


if __name__ == "__main__":
    unittest.main()
