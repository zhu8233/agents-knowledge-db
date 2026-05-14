from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DbmsIndexRebuildTests(unittest.TestCase):
    def test_install_with_snapshot_includes_index_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            self.assertTrue((vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "file-index.jsonl").exists())
            self.assertTrue((vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "topic-summary.json").exists())
            self.assertTrue((vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "findings.json").exists())
            self.assertTrue((vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-index-run.json").exists())
            self.assertTrue((vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-dbms-run.json").exists())

    def test_rebuild_index_reports_registry_and_scan_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            orphan_dir = vault / "ProjectRaw" / "Loose"
            orphan_dir.mkdir(parents=True, exist_ok=True)
            (orphan_dir / "orphan.md").write_text("# Orphan\n", encoding="utf-8")

            mismatch_path = "20-KnowledgeHub/stray-intake-note.md"
            (vault / "20-KnowledgeHub").mkdir(parents=True, exist_ok=True)
            (vault / mismatch_path).write_text("# Canonical Path But Intake Layer\n", encoding="utf-8")

            registry_path = vault / ".knowledge-registry" / "vault-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["topics"].append(
                {
                    "topic_id": "topic.test-index",
                    "title": "Test Index Topic",
                    "aliases": [],
                    "status": "active",
                    "source_domains": [],
                    "intake_paths": ["ProjectRaw/Loose"],
                    "curation_paths": [],
                    "canonical_home": None,
                    "related_topics": [],
                    "upstream_bindings": [],
                }
            )
            registry["objects"].extend(
                [
                    {
                        "kb_id": "kb.test.missing",
                        "path": "ProjectRaw/Missing/missing.md",
                        "kb_type": "source_note",
                        "kb_layer": "intake",
                        "topic_id": "topic.test-index",
                        "status": "active",
                        "managed_by": "human",
                        "source_system": "human",
                        "updated_at": "2026-04-20",
                    },
                    {
                        "kb_id": "kb.test.mismatch",
                        "path": mismatch_path,
                        "kb_type": "source_note",
                        "kb_layer": "intake",
                        "topic_id": "topic.test-index",
                        "status": "active",
                        "managed_by": "human",
                        "source_system": "human",
                        "updated_at": "2026-04-20",
                    },
                ]
            )
            registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "rebuild_dbms_index.py"), str(vault)],
                check=True,
                cwd=ROOT,
            )

            index_dir = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index"
            report_files = list((vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "reports").glob("*index-audit-report.md"))
            self.assertTrue((index_dir / "file-index.jsonl").exists())
            self.assertTrue((index_dir / "topic-summary.json").exists())
            self.assertTrue((index_dir / "findings.json").exists())
            self.assertTrue(report_files)

            findings = json.loads((index_dir / "findings.json").read_text(encoding="utf-8"))
            finding_types = {item["finding_type"] for item in findings["items"]}
            self.assertIn("unregistered_file", finding_types)
            self.assertIn("registry_missing_file", finding_types)
            self.assertIn("layer_path_mismatch", finding_types)

    def test_rebuild_index_appends_ledger_safely_when_file_lacks_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            ledger_path = vault / ".knowledge-registry" / "change-ledger.jsonl"
            ledger_text = ledger_path.read_text(encoding="utf-8").rstrip("\n")
            ledger_path.write_text(ledger_text, encoding="utf-8")

            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "rebuild_dbms_index.py"), str(vault)],
                check=True,
                cwd=ROOT,
            )

            lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            for line in lines:
                json.loads(line)

    def test_rebuild_index_uses_topic_curation_paths_before_root_layer_guess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            curation_dir = vault / "ProjectRaw" / "TopicA" / "Curated"
            curation_dir.mkdir(parents=True, exist_ok=True)
            curated_path = "ProjectRaw/TopicA/Curated/overview.md"
            (vault / curated_path).write_text("---\ntitle: Curated\n---\n# Curated\n", encoding="utf-8")

            registry_path = vault / ".knowledge-registry" / "vault-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["topics"].append(
                {
                    "topic_id": "topic.curated-under-projectraw",
                    "title": "Curated Under ProjectRaw",
                    "aliases": [],
                    "status": "active",
                    "source_domains": [],
                    "intake_paths": ["ProjectRaw/TopicA"],
                    "curation_paths": ["ProjectRaw/TopicA/Curated"],
                    "canonical_home": None,
                    "related_topics": [],
                    "upstream_bindings": [],
                }
            )
            registry["objects"].append(
                {
                    "kb_id": "kb.curation.topica.overview",
                    "path": curated_path,
                    "kb_type": "curation_note",
                    "kb_layer": "curation",
                    "topic_id": "topic.curated-under-projectraw",
                    "status": "active",
                    "managed_by": "human",
                    "source_system": "human",
                    "updated_at": "2026-04-20",
                }
            )
            registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "rebuild_dbms_index.py"), str(vault)],
                check=True,
                cwd=ROOT,
            )

            entries = []
            with (vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "file-index.jsonl").open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        entries.append(json.loads(line))

            entry = next(item for item in entries if item["path"] == curated_path)
            self.assertEqual(entry["kb_layer_guess"], "curation")
            self.assertEqual(entry["registry_status"], "registered")

    def test_rebuild_index_does_not_report_dbms_runtime_files_as_unregistered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "rebuild_dbms_index.py"), str(vault)],
                check=True,
                cwd=ROOT,
            )

            findings = json.loads(
                (vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "findings.json").read_text(encoding="utf-8")
            )
            runtime_findings = [
                item
                for item in findings["items"]
                if item["finding_type"] == "unregistered_file"
                and item["path"].startswith("01-Workflow/Knowledge-Governance/DBMS/")
            ]
            self.assertEqual(runtime_findings, [])

    def test_rebuild_index_marks_invalid_frontmatter_with_distinct_finding_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            invalid_path = "ProjectRaw/Invalid/frontmatter.md"
            (vault / "ProjectRaw" / "Invalid").mkdir(parents=True, exist_ok=True)
            (vault / invalid_path).write_text("---\ntitle: Broken\n# Missing closing fence\n", encoding="utf-8")

            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "rebuild_dbms_index.py"), str(vault)],
                check=True,
                cwd=ROOT,
            )

            findings = json.loads(
                (vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "findings.json").read_text(encoding="utf-8")
            )
            finding_types = {
                item["finding_type"]
                for item in findings["items"]
                if item["path"] == invalid_path
            }
            self.assertIn("frontmatter_invalid", finding_types)

    def test_findings_schema_includes_frontmatter_invalid(self) -> None:
        schema = json.loads((ROOT / "schemas" / "dbms-findings.schema.json").read_text(encoding="utf-8"))
        finding_type_enum = schema["properties"]["items"]["items"]["properties"]["finding_type"]["enum"]
        self.assertIn("frontmatter_invalid", finding_type_enum)

    def test_rebuild_index_topic_summary_tracks_missing_registry_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            registry_path = vault / ".knowledge-registry" / "vault-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["topics"].append(
                {
                    "topic_id": "topic.missing-summary",
                    "title": "Missing Summary",
                    "aliases": [],
                    "status": "active",
                    "source_domains": [],
                    "intake_paths": ["ProjectRaw/MissingSummary"],
                    "curation_paths": [],
                    "canonical_home": None,
                    "related_topics": [],
                    "upstream_bindings": [],
                }
            )
            registry["objects"].append(
                {
                    "kb_id": "kb.missing.summary",
                    "path": "ProjectRaw/MissingSummary/missing.md",
                    "kb_type": "source_note",
                    "kb_layer": "intake",
                    "topic_id": "topic.missing-summary",
                    "status": "active",
                    "managed_by": "human",
                    "source_system": "human",
                    "updated_at": "2026-04-20",
                }
            )
            registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "rebuild_dbms_index.py"), str(vault)],
                check=True,
                cwd=ROOT,
            )

            topic_summary = json.loads(
                (vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "topic-summary.json").read_text(encoding="utf-8")
            )
            topic_entry = next(item for item in topic_summary["topics"] if item["topic_id"] == "topic.missing-summary")
            self.assertEqual(topic_entry["registry_counts"]["registry_missing_file"], 1)

    def test_rebuild_index_skips_symlinked_files_outside_vault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            outside_file = Path(tmp) / "outside.md"
            outside_file.write_text("---\ntitle: Outside\n---\n# Outside\n", encoding="utf-8")
            symlink_path = vault / "ProjectRaw" / "symlinked-outside.md"
            symlink_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                symlink_path.symlink_to(outside_file)
            except (OSError, NotImplementedError, PermissionError):
                self.skipTest("symlinks are not available in this environment")

            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "rebuild_dbms_index.py"), str(vault)],
                check=True,
                cwd=ROOT,
            )

            entries = []
            with (vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "file-index.jsonl").open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        entries.append(json.loads(line))

            self.assertNotIn("ProjectRaw/symlinked-outside.md", {item["path"] for item in entries})

    def test_rebuild_index_classifies_google_drive_sync_data_as_intake(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install_to_vault.py"), str(vault), "--with-snapshot"],
                check=True,
                cwd=ROOT,
            )

            google_sync_path = "00-GoogleDrive_SyncData/Exports/note.md"
            (vault / "00-GoogleDrive_SyncData" / "Exports").mkdir(parents=True, exist_ok=True)
            (vault / google_sync_path).write_text("---\ntitle: Imported\n---\n# Imported\n", encoding="utf-8")

            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "rebuild_dbms_index.py"), str(vault)],
                check=True,
                cwd=ROOT,
            )

            entries = []
            with (vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "file-index.jsonl").open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        entries.append(json.loads(line))

            entry = next(item for item in entries if item["path"] == google_sync_path)
            self.assertEqual(entry["zone"], "intake")
            self.assertEqual(entry["kb_layer_guess"], "intake")


if __name__ == "__main__":
    unittest.main()
