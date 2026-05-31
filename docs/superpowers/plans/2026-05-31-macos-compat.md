# macOS Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the APFS case-insensitive path mismatch bug on macOS, add two macOS-specific regression tests, and document the implicit `vault_root.resolve()` contract in `GovernanceBackend`.

**Architecture:** Three targeted edits across two source files and one test file. No new abstractions, no new files. Each task is independently releasable.

**Tech Stack:** Python 3.9+, pathlib, unittest, sys.platform

---

## Files

| Action | Path |
|--------|------|
| Modify | `scripts/vault_content_ops.py` |
| Modify | `scripts/mcp_governance_backend.py` |
| Modify | `tests/test_vault_content_ops.py` |

---

## Task 1: Fix `_relative_is_within_root` for macOS case-insensitivity

**Files:**
- Modify: `scripts/vault_content_ops.py:1-10` (imports), `scripts/vault_content_ops.py:50-56` (function body)
- Test: `tests/test_vault_content_ops.py`

**Context:** APFS/HFS+ on macOS is case-insensitive by default. The OS treats `projectraw/health` and `ProjectRaw/Health` as the same directory. The current access-control check only applies case-folding on Windows (`os.name == "nt"`), so macOS callers supplying lower-case root paths get a `ValueError` even though the filesystem would accept the path.

- [ ] **Step 1: Write the failing test**

Add this method to `VaultContentOpsTests` in `tests/test_vault_content_ops.py`, immediately after `test_list_paths_accepts_case_insensitive_allowed_root_on_windows` (line 316):

```python
def test_list_paths_accepts_case_insensitive_allowed_root_on_macos(self) -> None:
    if sys.platform != "darwin":
        self.skipTest("macOS case-insensitive filesystem behavior only")
    with tempfile.TemporaryDirectory() as tmp:
        vault = self._make_vault(Path(tmp))

        result = list_paths(vault, root="projectraw/health", recursive=True)

        self.assertEqual(result["root"], "projectraw/health")
        self.assertIn("ProjectRaw/Health/diet.md", result["paths"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_vault_content_ops.py::VaultContentOpsTests::test_list_paths_accepts_case_insensitive_allowed_root_on_macos -v
```

Expected: `FAILED` with `ValueError: path must be inside an allowed read root`

- [ ] **Step 3: Add `import sys` to `vault_content_ops.py`**

`scripts/vault_content_ops.py` currently imports `os` but not `sys`. Add `sys` to the standard-library imports at the top of the file:

Replace:
```python
import hashlib
import json
import os
import re
```

With:
```python
import hashlib
import json
import os
import re
import sys
```

- [ ] **Step 4: Extend case-folding to macOS**

In `scripts/vault_content_ops.py`, replace the `_relative_is_within_root` function body:

Replace:
```python
def _relative_is_within_root(relative: Path, root: Path) -> bool:
    relative_parts = relative.parts
    root_parts = root.parts
    if os.name == "nt":
        relative_parts = tuple(part.casefold() for part in relative_parts)
        root_parts = tuple(part.casefold() for part in root_parts)
    return relative_parts == root_parts or relative_parts[: len(root_parts)] == root_parts
```

With:
```python
def _relative_is_within_root(relative: Path, root: Path) -> bool:
    relative_parts = relative.parts
    root_parts = root.parts
    # Apply case-folding on filesystems that are case-insensitive by default:
    # Windows (NTFS) and macOS (APFS/HFS+). Linux (ext4, etc.) is case-sensitive,
    # so strict matching is correct there.
    if os.name == "nt" or sys.platform == "darwin":
        relative_parts = tuple(part.casefold() for part in relative_parts)
        root_parts = tuple(part.casefold() for part in root_parts)
    return relative_parts == root_parts or relative_parts[: len(root_parts)] == root_parts
```

- [ ] **Step 5: Run the new test to verify it passes**

```bash
python3 -m pytest tests/test_vault_content_ops.py::VaultContentOpsTests::test_list_paths_accepts_case_insensitive_allowed_root_on_macos -v
```

Expected: `PASSED`

- [ ] **Step 6: Run the full test suite to check for regressions**

```bash
python3 -m pytest tests/ -v
```

Expected: all previously passing tests still pass, new macOS test passes.

- [ ] **Step 7: Commit**

```bash
git add scripts/vault_content_ops.py tests/test_vault_content_ops.py
git commit -m "fix: extend case-insensitive path matching to macOS (APFS/HFS+)"
```

---

## Task 2: Add macOS `/var → /private/var` operation-log regression test

**Files:**
- Test: `tests/test_vault_content_ops.py`

**Context:** On macOS, `tempfile.TemporaryDirectory()` returns paths under `/var/folders/...`. The system-level `/var` is a symlink to `/private/var`, so `Path('/var/folders/...').resolve()` returns `/private/var/folders/...`. The `_write_operation_log` function now resolves each parent-path candidate before comparing against the resolved vault root. This test pins that behavior so a future regression is caught immediately.

The test does NOT create an artificial symlink — it relies on the real macOS filesystem topology. It is skipped on Linux and Windows where the scenario does not apply.

- [ ] **Step 1: Write the regression test**

Add this method to `VaultContentOpsTests` in `tests/test_vault_content_ops.py`, immediately after `test_upsert_markdown_records_operation_log` (line 357):

```python
def test_operation_log_does_not_raise_when_vault_path_traverses_os_level_symlink(self) -> None:
    # On macOS, /var is a symlink to /private/var. Paths returned by
    # tempfile.TemporaryDirectory() go through this OS-level symlink, so
    # vault_root.resolve() returns a /private/var/... path while the unresolved
    # vault_root path is /var/folders/.... _write_operation_log must not raise
    # "operation log path must not be a symlink" when traversing these parents.
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
```

- [ ] **Step 2: Run test to verify it passes**

```bash
python3 -m pytest tests/test_vault_content_ops.py::VaultContentOpsTests::test_operation_log_does_not_raise_when_vault_path_traverses_os_level_symlink -v
```

Expected: `PASSED` (the fix from the earlier session already ensures this passes; the test documents it)

- [ ] **Step 3: Run the full test suite to check for regressions**

```bash
python3 -m pytest tests/ -v
```

Expected: all previously passing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_vault_content_ops.py
git commit -m "test: add macOS /var symlink regression test for operation log boundary check"
```

---

## Task 3: Document the implicit `vault_root.resolve()` contract in `GovernanceBackend`

**Files:**
- Modify: `scripts/mcp_governance_backend.py:57-60`

**Context:** `_safe_resolve_file` and `_latest_index_report_path` both call `resolved_path.relative_to(self.vault_root)`. This boundary check is only correct on macOS if `self.vault_root` is pre-resolved (so that the comparison is `/private/var/...` vs `/private/var/...`, not `/var/...` vs `/private/var/...`). The `__init__` already calls `.resolve()`, but there is no comment explaining that downstream methods depend on this invariant.

- [ ] **Step 1: Add invariant comment to `__init__`**

In `scripts/mcp_governance_backend.py`, replace:

```python
    def __init__(self, vault_root: Path, *, subject_id: str, auth_mode: str) -> None:
        self.vault_root = Path(vault_root).resolve()
        self.subject_id = subject_id
        self.auth_mode = auth_mode
```

With:

```python
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
```

- [ ] **Step 2: Run the full test suite to check nothing broke**

```bash
python3 -m pytest tests/ -v
```

Expected: all previously passing tests still pass.

- [ ] **Step 3: Commit**

```bash
git add scripts/mcp_governance_backend.py
git commit -m "docs: document vault_root.resolve() invariant in GovernanceBackend.__init__"
```

---

## Final Verification

- [ ] **Run validate_repo and validate_system_repo**

```bash
python3 scripts/validate_repo.py && python3 scripts/validate_system_repo.py
```

Expected:
```
VALIDATION_OK
VALIDATE_SYSTEM_REPO_OK
```

- [ ] **Confirm test counts**

```bash
python3 -m pytest tests/ -v 2>&1 | tail -3
```

Expected: at least `132 passed, 1 skipped` (130 original passing + 2 new tests; 1 Windows skip unchanged).
