from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_MODULE = ROOT / "scripts" / "vault_content_ops.py"

if SCRIPT_MODULE.exists():
    sys.path.insert(0, str(SCRIPT_MODULE.parent))

from vault_content_ops import (
    append_markdown,
    check_artifacts,
    list_paths,
    read_markdown,
    scan_curation_gaps,
    search_markdown,
    upsert_markdown,
)


class VaultContentOpsTests(unittest.TestCase):
    def _make_vault(self, root: Path) -> Path:
        vault = root / "vault"
        (vault / "ProjectRaw" / "Health").mkdir(parents=True, exist_ok=True)
        (vault / "ProjectRaw" / "Health" / "diet.md").write_text(
            "# Diet\n\n## 2026-05-14\ncalories: 1900\n",
            encoding="utf-8",
        )
        (vault / "ProjectRaw" / "DailyReports").mkdir(parents=True, exist_ok=True)
        (vault / "ProjectRaw" / "TopicA" / "00-专题索引.md").parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        (vault / "ProjectRaw" / "TopicA" / "00-专题索引.md").write_text(
            "# TopicA\n",
            encoding="utf-8",
        )
        (vault / "ProjectRaw" / "TopicA" / "01-source.md").write_text(
            "source\n",
            encoding="utf-8",
        )
        return vault

    def test_list_paths_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                list_paths(vault, root="../outside", recursive=True)

    def test_list_paths_rejects_file_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                list_paths(vault, root="ProjectRaw/Health/diet.md", recursive=True)

    def test_list_paths_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = self._make_vault(base)
            outside = base / "outside"
            outside.mkdir()
            link = vault / "ProjectRaw" / "Health" / "escape"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                if sys.platform != "win32":
                    self.skipTest("Cannot create a symlink on this system")
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                    capture_output=True,
                )
                if result.returncode != 0:
                    self.skipTest("Cannot create a symlink or junction on this system")
            # The escape should be detected by resolving the link target, not by
            # checking is_symlink() alone. On Windows the fallback above is a
            # junction, which still resolves outside the vault.
            with self.assertRaises(ValueError):
                list_paths(vault, root="ProjectRaw/Health/escape", recursive=True)

    def test_read_markdown_can_extract_date_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            result = read_markdown(
                vault,
                path="ProjectRaw/Health/diet.md",
                date_filter="2026-05-14",
            )
            self.assertIn("1900", result["content"])

    def test_read_markdown_isolates_heading_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            note = vault / "ProjectRaw" / "Health" / "sections.md"
            note.write_text(
                "# Report\n\n"
                "## Highlights\n"
                "alpha\n\n"
                "### Detail\n"
                "nested detail\n\n"
                "## Next Steps\n"
                "beta\n",
                encoding="utf-8",
            )

            result = read_markdown(
                vault,
                path="ProjectRaw/Health/sections.md",
                heading="## Highlights",
            )

            self.assertIn("alpha", result["content"])
            self.assertIn("nested detail", result["content"])
            self.assertNotIn("## Next Steps", result["content"])
            self.assertNotIn("beta", result["content"])

    def test_read_markdown_isolates_date_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            note = vault / "ProjectRaw" / "Health" / "journal.md"
            note.write_text(
                "# Journal\n\n"
                "## 2026-05-14\n"
                "day one\n\n"
                "## 2026-05-15\n"
                "day two\n",
                encoding="utf-8",
            )

            result = read_markdown(
                vault,
                path="ProjectRaw/Health/journal.md",
                date_filter="2026-05-14",
            )

            self.assertIn("day one", result["content"])
            self.assertNotIn("## 2026-05-15", result["content"])
            self.assertNotIn("day two", result["content"])

    def test_read_markdown_accepts_date_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            note = vault / "ProjectRaw" / "Health" / "journal.md"
            note.write_text(
                "# Journal\n\n"
                "## 2026-05-14\n"
                "day one\n\n"
                "## 2026-06-01\n"
                "day two\n",
                encoding="utf-8",
            )

            result = read_markdown(
                vault,
                path="ProjectRaw/Health/journal.md",
                date_filter="2026-05",
            )

            self.assertIn("day one", result["content"])
            self.assertNotIn("## 2026-06-01", result["content"])
            self.assertNotIn("day two", result["content"])

    def test_read_markdown_rejects_non_markdown_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = self._make_vault(base)
            note = vault / "ProjectRaw" / "Health" / "diet.txt"
            note.write_text("plain text\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_markdown(vault, path="ProjectRaw/Health/diet.txt")

            link = vault / "ProjectRaw" / "Health" / "diet-link.md"
            try:
                link.symlink_to(note)
            except OSError:
                self.skipTest("Cannot create a symlink on this system")
            with self.assertRaises(ValueError):
                read_markdown(vault, path="ProjectRaw/Health/diet-link.md")

    def test_read_markdown_rejects_disallowed_read_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            outside = vault / "Canonical"
            outside.mkdir(parents=True, exist_ok=True)
            (outside / "summary.md").write_text("# Summary\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                read_markdown(vault, path="Canonical/summary.md")

    def test_read_markdown_rejects_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                read_markdown(vault, path="ProjectRaw/Health/missing.md")

    def test_search_markdown_returns_matching_snippets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            result = search_markdown(
                vault,
                glob="ProjectRaw/**/*.md",
                query="calories",
            )
            self.assertEqual(result["count"], 1)

    def test_search_markdown_ignores_symlinked_markdown_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            link = vault / "ProjectRaw" / "Health" / "diet-link.md"
            try:
                link.symlink_to(vault / "ProjectRaw" / "Health" / "diet.md")
            except OSError:
                self.skipTest("Cannot create a symlink on this system")

            result = search_markdown(vault, glob="ProjectRaw/Health/*.md", query="calories")
            paths_hit = [match["path"] for match in result["matches"]]
            self.assertIn("ProjectRaw/Health/diet.md", paths_hit)
            self.assertNotIn("ProjectRaw/Health/diet-link.md", paths_hit)

    def test_search_markdown_date_filter_limits_matches_to_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            note = vault / "ProjectRaw" / "Health" / "journal.md"
            note.write_text(
                "# Journal\n\n"
                "## 2026-05-14\n"
                "calories: 1800\n\n"
                "## 2026-05-15\n"
                "calories: 2400\n",
                encoding="utf-8",
            )

            result = search_markdown(
                vault,
                glob="ProjectRaw/Health/*.md",
                query="2400",
                date_filter="2026-05-14",
            )

            self.assertEqual(result["count"], 0)
            self.assertEqual(result["matches"], [])

    def test_search_markdown_date_prefix_matches_all_prefix_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            note = vault / "ProjectRaw" / "Health" / "journal.md"
            note.write_text(
                "# Journal\n\n"
                "## 2026-05-14\n"
                "calories: 1800\n\n"
                "## 2026-05-15\n"
                "calories: 2400\n",
                encoding="utf-8",
            )

            result = search_markdown(
                vault,
                glob="ProjectRaw/Health/*.md",
                query="2400",
                date_filter="2026-05",
            )

            self.assertEqual(result["count"], 1)
            self.assertEqual(result["matches"][0]["path"], "ProjectRaw/Health/journal.md")

    def test_search_markdown_rejects_empty_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                search_markdown(vault, glob="ProjectRaw/**/*.md")

    def test_search_markdown_rejects_explicit_outside_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = self._make_vault(base)
            outside = base / "outside.md"
            outside.write_text("calories\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                search_markdown(vault, paths=[str(outside)], query="calories")

    def test_search_markdown_rejects_invalid_regex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                search_markdown(vault, glob="ProjectRaw/**/*.md", regex="(")

    def test_search_markdown_rejects_non_positive_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                search_markdown(vault, glob="ProjectRaw/**/*.md", query="calories", max_results=0)
            with self.assertRaises(ValueError):
                search_markdown(vault, glob="ProjectRaw/**/*.md", query="calories", max_chars_per_hit=0)

    def test_list_paths_rejects_disallowed_read_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            (vault / "Canonical").mkdir(parents=True, exist_ok=True)

            with self.assertRaises(ValueError):
                list_paths(vault, root="Canonical", recursive=True)

    def test_list_paths_accepts_case_insensitive_allowed_root_on_windows(self) -> None:
        if sys.platform != "win32":
            self.skipTest("Windows-only path case-insensitivity behavior")
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))

            result = list_paths(vault, root="projectraw/health", recursive=True)

            self.assertEqual(result["root"], "projectraw/health")
            self.assertIn("ProjectRaw/Health/diet.md", result["paths"])

    def test_list_paths_accepts_case_insensitive_allowed_root_on_macos(self) -> None:
        if sys.platform != "darwin":
            self.skipTest("macOS case-insensitive filesystem behavior only")
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))

            result = list_paths(vault, root="projectraw/health", recursive=True)

            # On macOS, pathlib.Path.resolve() does not normalize case — the returned
            # paths preserve the case submitted by the caller (e.g. "projectraw/health/..."
            # rather than "ProjectRaw/Health/..."). This is self-consistent: subsequent
            # calls that use the returned paths are accepted because _relative_is_within_root
            # now case-folds on macOS (verified: read_markdown(vault, path=returned_path) works).
            self.assertEqual(result["root"], "projectraw/health")
            self.assertIn("projectraw/health/diet.md", result["paths"])

    def test_list_paths_rejects_non_positive_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                list_paths(vault, root="ProjectRaw/Health", recursive=True, limit=0)

    def test_list_paths_rejects_glob_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                list_paths(vault, root="ProjectRaw/Health", recursive=False, glob="../*.md")

    def test_upsert_markdown_enforces_expected_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                upsert_markdown(
                    vault,
                    path="ProjectRaw/DailyReports/2026-05-14.md",
                    content="# Report\n",
                    mode="upsert",
                    expected_hash="deadbeef",
                    actor="owner@example.com",
                )

    def test_upsert_markdown_records_operation_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            result = upsert_markdown(
                vault,
                path="ProjectRaw/DailyReports/2026-05-14.md",
                content="# Report\n",
                mode="upsert",
                actor="owner@example.com",
            )

            log_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "mcp-operation-log.jsonl"
            self.assertTrue(log_path.exists())
            self.assertEqual(result["operation"], "upsert")
            self.assertIn("owner@example.com", log_path.read_text(encoding="utf-8"))

    def test_operation_log_does_not_raise_when_vault_path_traverses_os_level_symlink(self) -> None:
        # On macOS, /var is a symlink to /private/var. Paths returned by
        # tempfile.TemporaryDirectory() go through this OS-level symlink, so
        # vault_root.resolve() returns a /private/var/... path while the unresolved
        # vault_root path is /var/folders/.... _write_operation_log must not raise
        # "operation log path must not be a symlink" when traversing these parents.
        # Regression guard for the boundary-check fix in vault_content_ops.py.
        if sys.platform != "darwin":
            self.skipTest("macOS /var -> /private/var OS-level symlink scenario only")
        with tempfile.TemporaryDirectory() as tmp:
            # Do NOT resolve tmp here — keep the /var/folders/... form to exercise
            # the OS-level symlink path through the parent-traversal boundary check.
            vault = self._make_vault(Path(tmp))

            result = upsert_markdown(
                vault,
                path="ProjectRaw/DailyReports/2026-05-31.md",
                content="# OS-level symlink test\n",
                mode="upsert",
                actor="owner@example.com",
            )

            log_path = (
                vault
                / "01-Workflow"
                / "Knowledge-Governance"
                / "DBMS"
                / "state"
                / "mcp-operation-log.jsonl"
            )
            self.assertTrue(log_path.exists(), "operation log must be created")
            self.assertEqual(result["operation"], "upsert")

    def test_upsert_markdown_rejects_disallowed_governance_write_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                upsert_markdown(
                    vault,
                    path="01-Workflow/Knowledge-Governance/Policies/unsafe.md",
                    content="# Unsafe\n",
                    mode="upsert",
                    actor="owner@example.com",
                )

    def test_upsert_markdown_rejects_symlinked_operation_log_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = self._make_vault(base)
            outside = base / "outside"
            outside.mkdir()
            state_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                state_path.symlink_to(outside, target_is_directory=True)
            except OSError:
                if sys.platform != "win32":
                    self.skipTest("Cannot create a symlink on this system")
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(state_path), str(outside)],
                    capture_output=True,
                )
                if result.returncode != 0:
                    self.skipTest("Cannot create a symlink or junction on this system")

            with self.assertRaises(ValueError):
                upsert_markdown(
                    vault,
                    path="ProjectRaw/DailyReports/2026-05-14.md",
                    content="# Report\n",
                    mode="upsert",
                    actor="owner@example.com",
                )

    def test_read_markdown_rejects_non_positive_max_chars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                read_markdown(vault, path="ProjectRaw/Health/diet.md", max_chars=0)

    def test_append_markdown_can_create_heading_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            result = append_markdown(
                vault,
                path="ProjectRaw/DailyReports/2026-05-14.md",
                content="- new item\n",
                target="heading",
                heading="## Highlights",
                create_if_missing=True,
                actor="owner@example.com",
            )
            self.assertTrue(result["created_section"])

    def test_append_markdown_enforces_expected_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            report = vault / "ProjectRaw" / "DailyReports" / "2026-05-14.md"
            report.write_text("# Report\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                append_markdown(
                    vault,
                    path="ProjectRaw/DailyReports/2026-05-14.md",
                    content="- extra\n",
                    target="eof",
                    expected_hash="deadbeef",
                    actor="owner@example.com",
                )

    def test_append_markdown_records_operation_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            report = vault / "ProjectRaw" / "DailyReports" / "2026-05-14.md"
            report.write_text("# Report\n", encoding="utf-8")

            result = append_markdown(
                vault,
                path="ProjectRaw/DailyReports/2026-05-14.md",
                content="- extra\n",
                target="eof",
                actor="owner@example.com",
            )

            log_path = vault / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "mcp-operation-log.jsonl"
            self.assertEqual(result["operation"], "append")
            self.assertTrue(log_path.exists())
            self.assertIn("vault_append_markdown", log_path.read_text(encoding="utf-8"))

    def test_check_artifacts_reports_missing_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            result = check_artifacts(
                vault,
                artifacts=[
                    {
                        "path_glob": "ProjectRaw/DailyReports/*.md",
                        "required_date": "2026-05-14",
                        "must_exist": True,
                    }
                ],
            )
            self.assertEqual(result["missing"], 1)

    def test_check_artifacts_rejects_missing_path_glob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                check_artifacts(vault, artifacts=[{"must_exist": True}])

    def test_check_artifacts_does_not_mark_content_mismatch_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            report = vault / "ProjectRaw" / "DailyReports" / "2026-05-14.md"
            report.write_text("# Report\nstatus: draft\n", encoding="utf-8")

            result = check_artifacts(
                vault,
                artifacts=[
                    {
                        "path_glob": "ProjectRaw/DailyReports/*.md",
                        "required_date": "2026-05-14",
                        "content_contains": "status: final",
                        "must_exist": True,
                    }
                ],
            )

            self.assertEqual(result["missing"], 0)
            self.assertEqual(result["content_failures"], 1)

    def test_check_artifacts_ignores_out_of_vault_junction_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = self._make_vault(base)
            outside = base / "outside"
            outside.mkdir()
            (outside / "escape.md").write_text("outside content\n", encoding="utf-8")
            link = vault / "ProjectRaw" / "Health" / "escape"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                if sys.platform != "win32":
                    self.skipTest("Cannot create a symlink on this system")
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                    capture_output=True,
                )
                if result.returncode != 0:
                    self.skipTest("Cannot create a symlink or junction on this system")

            result = check_artifacts(
                vault,
                artifacts=[
                    {
                        "path_glob": "ProjectRaw/Health/escape/*.md",
                        "must_exist": True,
                    }
                ],
            )
            self.assertEqual(result["missing"], 1)
            self.assertEqual(result["content_failures"], 0)
            self.assertEqual(result["results"][0]["matched_paths"], [])

    def test_scan_curation_gaps_skips_out_of_vault_junctions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = self._make_vault(base)
            outside = base / "outside"
            outside.mkdir()
            (outside / "escape.md").write_text("outside content\n", encoding="utf-8")
            (outside / "escape-2.md").write_text("outside content\n", encoding="utf-8")
            topic_dir = vault / "ProjectRaw" / "Escapes"
            topic_dir.mkdir(parents=True, exist_ok=True)
            link = topic_dir / "linked-topic"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                if sys.platform != "win32":
                    self.skipTest("Cannot create a symlink on this system")
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                    capture_output=True,
                )
                if result.returncode != 0:
                    self.skipTest("Cannot create a symlink or junction on this system")

            result = scan_curation_gaps(vault, min_intake_files=2)
            self.assertEqual(result["count"], 0)
            self.assertEqual(result["items"], [])

    def test_scan_curation_gaps_ignores_symlinked_index_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = self._make_vault(base)
            outside = base / "outside-index.md"
            outside.write_text("# index\n", encoding="utf-8")
            topic_dir = vault / "ProjectRaw" / "SymlinkIndex"
            topic_dir.mkdir(parents=True, exist_ok=True)
            (topic_dir / "01-source.md").write_text("source one\n", encoding="utf-8")
            (topic_dir / "02-source.md").write_text("source two\n", encoding="utf-8")
            index_link = topic_dir / "00-专题索引.md"
            try:
                index_link.symlink_to(outside)
            except OSError:
                self.skipTest("Cannot create a symlink on this system")

            result = scan_curation_gaps(vault, min_intake_files=2)
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["items"][0]["topic_path"], "ProjectRaw/SymlinkIndex")

    def test_scan_curation_gaps_returns_candidate_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            result = scan_curation_gaps(vault, min_intake_files=1)
            self.assertEqual(result["count"], 1)

    def test_scan_curation_gaps_ignores_operational_output_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            reports_dir = vault / "ProjectRaw" / "DailyReports"
            (reports_dir / "2026-05-14.md").write_text("# Daily\n", encoding="utf-8")
            (reports_dir / "2026-05-15.md").write_text("# Daily\n", encoding="utf-8")

            result = scan_curation_gaps(vault, min_intake_files=2)

            self.assertEqual(result["count"], 0)
            self.assertEqual(result["items"], [])

    def test_scan_curation_gaps_rejects_non_positive_min_intake_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                scan_curation_gaps(vault, min_intake_files=0)

    def test_scan_curation_gaps_excludes_index_files_from_intake_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            topic_dir = vault / "ProjectRaw" / "Borderline"
            topic_dir.mkdir(parents=True, exist_ok=True)
            (topic_dir / "01-source.md").write_text("source\n", encoding="utf-8")
            archive_dir = topic_dir / "Archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            (archive_dir / "00-专题索引.md").write_text("# archived index\n", encoding="utf-8")

            result = scan_curation_gaps(vault, min_intake_files=2)

            self.assertEqual(result["count"], 0)
            self.assertEqual(result["items"], [])
