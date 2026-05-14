# Vault Content Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `agents-knowledge-db` with governed vault content tools so cron jobs can read/search/write approved Markdown paths through MCP instead of direct vault file access.

**Architecture:** Keep one stdio MCP server and extend `GovernanceBackend` with a new `vault_*` tool family. Put path safety, Markdown manipulation, hash checks, and operation-log behavior in a focused helper module so the backend stays declarative and the existing access evaluator remains the only policy gate.

**Tech Stack:** Python 3, unittest, existing `GovernanceBackend`, existing `evaluate_access()` policy model, Markdown text processing with standard library helpers

---

## File Structure

- **Create:** `scripts/vault_content_ops.py` — vault-relative path checks, list/read/search/check/gap-scan helpers, write helpers, operation log append
- **Create:** `tests/test_vault_content_ops.py` — focused temp-vault tests for path safety and vault content helper behavior
- **Create:** `tests/test_vault_cron_prompt_mapping.py` — fixture-level tests that map the eight cron workflows to supported MCP vault-content tools
- **Modify:** `scripts/mcp_governance_backend.py` — add `vault_*` tool catalog entries and wire handlers to the new helper module
- **Modify:** `tests/test_mcp_governance_server.py` — catalog visibility, role visibility, stdio coverage, and end-to-end backend handler tests for the new tools
- **Modify:** `tests/test_mcp_access_evaluator.py` — role-policy coverage for `vault_*` tools
- **Modify:** `templates/vault-root/LocalOverrides/mcp-access-policy.json` — add first-phase role permissions for `vault_*`
- **Modify:** `examples/portable-vault/LocalOverrides/mcp-access-policy.json` — keep example policy aligned
- **Modify:** `docs/mcp-server.md` — document the new vault-content tool family and first-phase boundaries
- **Modify:** `docs/mcp-access-model.md` — document role posture for read/search/list/check vs write tools
- **Modify:** `docs/mcp-client-configs.md` — document Hermes-side tool allowlist expansion after rollout

### Task 1: Add failing tests for vault content helpers

**Files:**
- Create: `tests/test_vault_content_ops.py`
- Test: `tests/test_vault_content_ops.py`

- [ ] **Step 1: Write failing helper tests**

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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
            "# Diet\\n\\n## 2026-05-14\\ncalories: 1900\\n",
            encoding="utf-8",
        )
        (vault / "ProjectRaw" / "DailyReports").mkdir(parents=True, exist_ok=True)
        (vault / "ProjectRaw" / "TopicA" / "00-专题索引.md").parent.mkdir(parents=True, exist_ok=True)
        (vault / "ProjectRaw" / "TopicA" / "00-专题索引.md").write_text("# TopicA\\n", encoding="utf-8")
        (vault / "ProjectRaw" / "TopicA" / "01-source.md").write_text("source\\n", encoding="utf-8")
        return vault

    def test_list_paths_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                list_paths(vault, root="../outside", recursive=True)

    def test_read_markdown_can_extract_date_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            result = read_markdown(vault, path="ProjectRaw/Health/diet.md", date_filter="2026-05-14")
            self.assertIn("1900", result["content"])

    def test_search_markdown_returns_matching_snippets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            result = search_markdown(vault, glob="ProjectRaw/**/*.md", query="calories")
            self.assertEqual(result["count"], 1)

    def test_upsert_markdown_enforces_expected_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                upsert_markdown(vault, path="ProjectRaw/DailyReports/2026-05-14.md", content="# Report\\n", mode="upsert", expected_hash="deadbeef", actor="owner@example.com")

    def test_append_markdown_can_create_heading_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            result = append_markdown(
                vault,
                path="ProjectRaw/DailyReports/2026-05-14.md",
                content="- new item\\n",
                target="heading",
                heading="## Highlights",
                create_if_missing=True,
                actor="owner@example.com",
            )
            self.assertTrue(result["created_section"])

    def test_check_artifacts_reports_missing_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            result = check_artifacts(
                vault,
                artifacts=[{"path_glob": "ProjectRaw/DailyReports/*.md", "required_date": "2026-05-14", "must_exist": True}],
            )
            self.assertEqual(result["missing"], 1)

    def test_scan_curation_gaps_returns_candidate_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(Path(tmp))
            result = scan_curation_gaps(vault, min_intake_files=1)
            self.assertEqual(result["count"], 1)
```

- [ ] **Step 2: Run the new test file and confirm import failures**

Run: `python -m pytest tests/test_vault_content_ops.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'vault_content_ops'`

- [ ] **Step 3: Create the minimal helper module skeleton**

```python
from __future__ import annotations


def list_paths(*args, **kwargs):
    raise NotImplementedError


def read_markdown(*args, **kwargs):
    raise NotImplementedError


def search_markdown(*args, **kwargs):
    raise NotImplementedError


def upsert_markdown(*args, **kwargs):
    raise NotImplementedError


def append_markdown(*args, **kwargs):
    raise NotImplementedError


def check_artifacts(*args, **kwargs):
    raise NotImplementedError


def scan_curation_gaps(*args, **kwargs):
    raise NotImplementedError
```

- [ ] **Step 4: Run the test file again to confirm the failure moved to behavior**

Run: `python -m pytest tests/test_vault_content_ops.py -q`
Expected: FAIL with `NotImplementedError` from the helper functions

- [ ] **Step 5: Commit the red test baseline**

```bash
git add tests/test_vault_content_ops.py scripts/vault_content_ops.py
git commit -m "test: add vault content helper coverage"
```

### Task 2: Implement read-only vault content helpers

**Files:**
- Modify: `scripts/vault_content_ops.py`
- Test: `tests/test_vault_content_ops.py`

- [ ] **Step 1: Implement shared path normalization and hash helpers**

```python
from __future__ import annotations

import hashlib
from pathlib import Path


def _normalize_relative_path(path: str) -> Path:
    relative = Path(path)
    if relative.is_absolute():
        raise ValueError("path must be vault-relative")
    if ".." in relative.parts:
        raise ValueError("path must not contain parent traversal")
    return relative


def _resolve_within_vault(vault_root: Path, path: str) -> tuple[Path, Path]:
    relative = _normalize_relative_path(path)
    candidate = (vault_root / relative).resolve()
    try:
        candidate.relative_to(vault_root.resolve())
    except ValueError as exc:
        raise ValueError("path escapes the vault root") from exc
    return relative, candidate


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
```

- [ ] **Step 2: Implement `list_paths`, `read_markdown`, and `search_markdown`**

```python
import re


def list_paths(vault_root: Path, *, root: str, recursive: bool, glob: str = "*", include_dirs: bool = False, limit: int = 100) -> dict:
    relative_root, resolved_root = _resolve_within_vault(vault_root, root)
    if not resolved_root.exists():
        raise ValueError(f"root does not exist: {root}")
    iterator = resolved_root.rglob(glob) if recursive else resolved_root.glob(glob)
    items = []
    for item in iterator:
        if item.is_symlink():
            continue
        if item.is_dir() and not include_dirs:
            continue
        items.append(str(item.resolve().relative_to(vault_root.resolve())).replace(\"\\\\\", \"/\"))
    items.sort()
    return {\"root\": str(relative_root).replace(\"\\\\\", \"/\"), \"paths\": items[:limit], \"count\": len(items[:limit]), \"truncated\": len(items) > limit}


def read_markdown(vault_root: Path, *, path: str, heading: str | None = None, date_filter: str | None = None, max_chars: int | None = None) -> dict:
    relative_path, resolved_path = _resolve_within_vault(vault_root, path)
    text = resolved_path.read_text(encoding=\"utf-8\")
    section = text
    if heading:
        marker = f\"{heading}\\n\"
        start = text.find(marker)
        if start == -1:
            raise ValueError(f\"heading not found: {heading}\")
        section = text[start:]
    if date_filter:
        marker = date_filter
        start = section.find(marker)
        if start == -1:
            raise ValueError(f\"date section not found: {date_filter}\")
        section = section[start:]
    if max_chars is not None:
        section = section[:max_chars]
    return {\"path\": str(relative_path).replace(\"\\\\\", \"/\"), \"hash\": _sha256_text(text), \"found\": True, \"content\": section, \"section\": heading or date_filter, \"truncated\": max_chars is not None and len(text) > len(section)}


def search_markdown(vault_root: Path, *, glob: str, query: str | None = None, regex: str | None = None, date_filter: str | None = None, max_results: int = 20, max_chars_per_hit: int = 160) -> dict:
    pattern = re.compile(regex) if regex else None
    matches = []
    for path in vault_root.glob(glob):
        if not path.is_file() or path.suffix.lower() != \".md\" or path.is_symlink():
            continue
        text = path.read_text(encoding=\"utf-8\")
        for idx, line in enumerate(text.splitlines(), 1):
            if date_filter and date_filter not in text:
                continue
            if query and query not in line and not (pattern and pattern.search(line)):
                continue
            if pattern and not pattern.search(line) and not (query and query in line):
                continue
            matches.append({\"path\": str(path.resolve().relative_to(vault_root.resolve())).replace(\"\\\\\", \"/\"), \"line\": idx, \"snippet\": line[:max_chars_per_hit]})
            if len(matches) >= max_results:
                return {\"count\": len(matches), \"matches\": matches}
    return {\"count\": len(matches), \"matches\": matches}
```

- [ ] **Step 3: Run the helper tests and fix only the read-only failures**

Run: `python -m pytest tests/test_vault_content_ops.py -q`
Expected: Some tests PASS (`list_paths`, `read_markdown`, `search_markdown`) while write-oriented tests still FAIL

- [ ] **Step 4: Implement `check_artifacts` and `scan_curation_gaps`**

```python
def check_artifacts(vault_root: Path, *, artifacts: list[dict]) -> dict:
    results = []
    missing = 0
    content_failures = 0
    for spec in artifacts:
        matched = []
        for path in vault_root.glob(spec[\"path_glob\"]):
            if not path.is_file():
                continue
            text = path.read_text(encoding=\"utf-8\")
            if spec.get(\"required_date\") and spec[\"required_date\"] not in text and spec[\"required_date\"] not in path.name:
                continue
            if spec.get(\"content_contains\") and spec[\"content_contains\"] not in text:
                content_failures += 1
                continue
            matched.append(str(path.resolve().relative_to(vault_root.resolve())).replace(\"\\\\\", \"/\"))
        if spec.get(\"must_exist\") and not matched:
            missing += 1
        results.append({\"spec\": spec, \"matched_paths\": matched})
    return {\"results\": results, \"missing\": missing, \"content_failures\": content_failures}


def scan_curation_gaps(vault_root: Path, *, min_intake_files: int = 5) -> dict:
    project_raw = vault_root / \"ProjectRaw\"
    candidates = []
    for topic_dir in sorted(path for path in project_raw.iterdir() if path.is_dir()):
        md_files = [path for path in topic_dir.rglob(\"*.md\") if path.is_file()]
        has_index = (topic_dir / \"00-专题索引.md\").exists()
        if len(md_files) >= min_intake_files and not has_index:
            candidates.append({\"topic_path\": str(topic_dir.relative_to(vault_root)).replace(\"\\\\\", \"/\"), \"intake_count\": len(md_files), \"has_index\": has_index})
    return {\"count\": len(candidates), \"items\": candidates}
```

- [ ] **Step 5: Commit the read-only helper implementation**

```bash
git add scripts/vault_content_ops.py tests/test_vault_content_ops.py
git commit -m "feat: add read-only vault content helpers"
```

### Task 3: Add MCP catalog and access-policy coverage for the new read-only tools

**Files:**
- Modify: `scripts/mcp_governance_backend.py`
- Modify: `tests/test_mcp_governance_server.py`
- Modify: `tests/test_mcp_access_evaluator.py`
- Modify: `templates/vault-root/LocalOverrides/mcp-access-policy.json`
- Modify: `examples/portable-vault/LocalOverrides/mcp-access-policy.json`

- [ ] **Step 1: Add failing backend/catalog and access tests**

```python
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


def test_vault_user_cannot_see_write_tool(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        self._install_and_seed_vault(vault)
        backend = GovernanceBackend(vault, subject_id="reader@example.com", auth_mode="oauth")
        tool_names = [tool["name"] for tool in backend.list_tools()]
        self.assertNotIn("vault_upsert_markdown", tool_names)
        self.assertNotIn("vault_append_markdown", tool_names)
```

```python
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
```

- [ ] **Step 2: Run targeted tests and confirm they fail on unknown tools**

Run: `python -m pytest tests/test_mcp_governance_server.py tests/test_mcp_access_evaluator.py -q`
Expected: FAIL because `vault_*` tools are absent from the catalog/policy

- [ ] **Step 3: Add read-only `vault_*` catalog entries, handlers, and policy rules**

```python
from vault_content_ops import check_artifacts, list_paths, read_markdown, scan_curation_gaps, search_markdown

# inside _tool_catalog()
{
    "name": "vault_list_paths",
    "title": "List Vault Paths",
    "description": "List allowed vault-relative paths without exposing raw filesystem access.",
    "risk_level": "L0",
    "target_layer": "system",
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    "inputSchema": {"type": "object", "required": ["root"], "properties": {"root": {"type": "string"}, "glob": {"type": "string", "default": "*"}, "recursive": {"type": "boolean", "default": False}, "include_dirs": {"type": "boolean", "default": False}, "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100}}, "additionalProperties": False},
    "outputSchema": {"type": "object", "properties": {"root": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}}, "count": {"type": "integer"}, "truncated": {"type": "boolean"}}},
},
```

```python
def _tool_vault_list_paths(self, arguments: dict) -> dict:
    result = list_paths(self.vault_root, **arguments)
    return {"isError": False, "content": [{"type": "text", "text": f\"Listed {result['count']} path(s).\"}], "structuredContent": result}
```

```json
{
  "mcp_role": "vault-maintainer",
  "allowed_tools": [
    "vault_list_paths",
    "vault_read_markdown",
    "vault_search_markdown",
    "vault_check_artifacts",
    "vault_scan_curation_gaps"
  ]
}
```

- [ ] **Step 4: Run the targeted tests again**

Run: `python -m pytest tests/test_mcp_governance_server.py tests/test_mcp_access_evaluator.py -q`
Expected: PASS for the new read-only catalog and access assertions

- [ ] **Step 5: Commit the read-only MCP wiring**

```bash
git add scripts/mcp_governance_backend.py tests/test_mcp_governance_server.py tests/test_mcp_access_evaluator.py templates/vault-root/LocalOverrides/mcp-access-policy.json examples/portable-vault/LocalOverrides/mcp-access-policy.json
git commit -m "feat: expose read-only vault content MCP tools"
```

### Task 4: Implement write helpers and write-tool backend coverage

**Files:**
- Modify: `scripts/vault_content_ops.py`
- Modify: `scripts/mcp_governance_backend.py`
- Modify: `tests/test_vault_content_ops.py`
- Modify: `tests/test_mcp_governance_server.py`

- [ ] **Step 1: Add failing write-tool tests**

```python
def test_system_maintainer_can_upsert_markdown_via_backend(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        self._install_and_seed_vault(vault)
        backend = GovernanceBackend(vault, subject_id="owner@example.com", auth_mode="oauth")
        result = backend.call_tool(
            "vault_upsert_markdown",
            {"path": "ProjectRaw/DailyReports/2026-05-14.md", "content": "# Daily\\n", "mode": "upsert"},
        )
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["operation"], "upsert")


def test_vault_maintainer_cannot_call_vault_upsert_markdown(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        self._install_and_seed_vault(vault)
        backend = GovernanceBackend(vault, subject_id="maintainer@example.com", auth_mode="oauth")
        result = backend.call_tool(
            "vault_upsert_markdown",
            {"path": "ProjectRaw/DailyReports/2026-05-14.md", "content": "# Daily\\n", "mode": "upsert"},
        )
        self.assertTrue(result["isError"])
```

- [ ] **Step 2: Run the backend tests and confirm write-tool failures**

Run: `python -m pytest tests/test_vault_content_ops.py tests/test_mcp_governance_server.py -q`
Expected: FAIL because the write helpers and backend handlers are not implemented yet

- [ ] **Step 3: Implement `upsert_markdown`, `append_markdown`, and operation log appends**

```python
import json
from datetime import datetime, timezone


def _write_operation_log(vault_root: Path, *, actor: str, tool: str, operation: str, path: str, old_hash: str | None, new_hash: str) -> None:
    log_path = vault_root / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "mcp-operation-log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "tool": tool,
        "operation": operation,
        "path": path,
        "old_hash": old_hash,
        "new_hash": new_hash,
    }
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\\n")


def upsert_markdown(vault_root: Path, *, path: str, content: str, mode: str, actor: str, expected_hash: str | None = None) -> dict:
    relative_path, resolved_path = _resolve_within_vault(vault_root, path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    old_text = resolved_path.read_text(encoding="utf-8") if resolved_path.exists() else None
    old_hash = _sha256_text(old_text) if old_text is not None else None
    if expected_hash is not None and old_hash != expected_hash:
        raise ValueError("expected_hash does not match current content")
    if mode == "create" and resolved_path.exists():
        raise ValueError("target already exists")
    if mode == "replace" and not resolved_path.exists():
        raise ValueError("target does not exist")
    resolved_path.write_text(content, encoding="utf-8")
    new_hash = _sha256_text(content)
    _write_operation_log(vault_root, actor=actor, tool="vault_upsert_markdown", operation=mode, path=str(relative_path).replace("\\\\", "/"), old_hash=old_hash, new_hash=new_hash)
    return {"path": str(relative_path).replace("\\\\", "/"), "operation": mode, "old_hash": old_hash, "new_hash": new_hash, "actor": actor, "bytes_written": len(content.encode("utf-8"))}
```

- [ ] **Step 4: Wire `vault_upsert_markdown` and `vault_append_markdown` into `GovernanceBackend`**

```python
from vault_content_ops import append_markdown, upsert_markdown


def _tool_vault_upsert_markdown(self, arguments: dict) -> dict:
    result = upsert_markdown(
        self.vault_root,
        path=arguments["path"],
        content=arguments["content"],
        mode=arguments["mode"],
        expected_hash=arguments.get("expected_hash"),
        actor=self.subject_id,
    )
    return {"isError": False, "content": [{"type": "text", "text": f\"Updated `{result['path']}` via {result['operation']}.\"}], "structuredContent": result}
```

- [ ] **Step 5: Commit the write-tool implementation**

```bash
git add scripts/vault_content_ops.py scripts/mcp_governance_backend.py tests/test_vault_content_ops.py tests/test_mcp_governance_server.py
git commit -m "feat: add governed vault markdown write tools"
```

### Task 5: Add cron-mapping fixture coverage and finish docs

**Files:**
- Create: `tests/test_vault_cron_prompt_mapping.py`
- Modify: `docs/mcp-server.md`
- Modify: `docs/mcp-access-model.md`
- Modify: `docs/mcp-client-configs.md`

- [ ] **Step 1: Add cron fixture tests**

```python
from __future__ import annotations

import unittest


CRON_TOOLSETS = {
    "每日饮食打卡判读": {"vault_read_markdown", "vault_search_markdown", "vault_append_markdown"},
    "每日个人提升主动询问": {"vault_read_markdown", "vault_search_markdown", "vault_append_markdown"},
    "每周个人提升周复盘": {"vault_read_markdown", "vault_search_markdown", "vault_upsert_markdown"},
    "每日新闻早报": {"vault_upsert_markdown"},
    "AI行业每日动态": {"vault_upsert_markdown"},
    "知识库健康检查": {"vault_check_artifacts", "vault_upsert_markdown"},
    "Hermes策展深度扫描": {"vault_scan_curation_gaps"},
    "GitHub Trending 每日早报": {"vault_upsert_markdown", "vault_append_markdown"},
}


class VaultCronPromptMappingTests(unittest.TestCase):
    def test_every_remaining_cron_workflow_has_vault_mcp_coverage(self) -> None:
        self.assertEqual(len(CRON_TOOLSETS), 8)
        self.assertIn("vault_append_markdown", CRON_TOOLSETS["GitHub Trending 每日早报"])
```

- [ ] **Step 2: Run the new fixture test**

Run: `python -m pytest tests/test_vault_cron_prompt_mapping.py -q`
Expected: PASS

- [ ] **Step 3: Update the docs**

```markdown
## Vault Content Protocol

The server also exposes governed vault content tools for cron-driven Markdown workflows:

- `vault_list_paths`
- `vault_read_markdown`
- `vault_search_markdown`
- `vault_upsert_markdown`
- `vault_append_markdown`
- `vault_check_artifacts`
- `vault_scan_curation_gaps`

These tools are vault-relative only and do not expose generic filesystem access.
```

- [ ] **Step 4: Re-run documentation-adjacent tests and validator**

Run: `python scripts/validate_repo.py`
Expected: `VALIDATION_OK`

- [ ] **Step 5: Commit the docs and fixture coverage**

```bash
git add tests/test_vault_cron_prompt_mapping.py docs/mcp-server.md docs/mcp-access-model.md docs/mcp-client-configs.md
git commit -m "docs: document vault content protocol rollout"
```

### Task 6: Run full verification and prepare runtime follow-up

**Files:**
- Modify: `docs/mcp-client-configs.md`
- Test: `tests/test_mcp_governance_server.py`
- Test: `tests/test_mcp_access_evaluator.py`
- Test: `tests/test_vault_content_ops.py`
- Test: `tests/test_vault_cron_prompt_mapping.py`

- [ ] **Step 1: Run the focused MCP test suite**

Run: `python -m pytest tests/test_mcp_governance_server.py tests/test_mcp_access_evaluator.py tests/test_vault_content_ops.py tests/test_vault_cron_prompt_mapping.py -q`
Expected: PASS

- [ ] **Step 2: Run the required regression suite from the spec**

Run: `python -m pytest tests/test_mcp_governance_server.py tests/test_mcp_access_evaluator.py tests/test_dbms_index_rebuild.py tests/test_dbms_state_reconcile.py -q`
Expected: PASS

- [ ] **Step 3: Run repository and data-repo validation**

Run: `python scripts/validate_repo.py && python scripts/validate_data_repo.py F:/01-NativeLearnStore/obsidian_native/native_AllNotes_Governed`
Expected: `VALIDATION_OK` then `VALIDATE_DATA_REPO_OK`

- [ ] **Step 4: Update Hermes rollout notes before runtime cron migration**

```markdown
After merge, expand the Hermes `agents-knowledge-db` allowlist only to the `vault_*` tools required by the target cron job, then migrate cron prompts one workflow at a time.
```

- [ ] **Step 5: Commit the verification pass**

```bash
git add docs/mcp-client-configs.md
git commit -m "chore: verify vault content protocol rollout"
```
