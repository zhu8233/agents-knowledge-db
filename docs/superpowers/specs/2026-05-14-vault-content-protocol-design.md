# Vault Content Protocol Design

**Date:** 2026-05-14  
**Status:** Approved for planning  
**Scope:** Extend `agents-knowledge-db` with governed vault content tools for cron-driven Markdown workflows.

## Problem

The current `agents-knowledge-db` MCP server covers governance and DBMS maintenance, but eight Hermes cron jobs still need governed access to Markdown content under the vault. Those jobs require controlled note reads, targeted append/upsert writes, artifact checks, and curation-gap scans. They do **not** need a generic filesystem MCP.

## Goals

1. Keep Hermes on the existing `agents-knowledge-db` stdio MCP server.
2. Expose governed, vault-relative content APIs instead of raw filesystem access.
3. Support cron-driven Markdown read/search/write workflows without direct vault file access.
4. Preserve the existing access model, risk levels, and approval boundaries.

## Non-Goals

1. Do not add a generic filesystem protocol.
2. Do not move web/news/GitHub fetching into this MCP.
3. Do not allow direct writes to canonical/protected zones in the first version.
4. Do not write content snapshots into Hermes memory.
5. Do not let curator scans modify `~/.hermes/skills` in the first version.

## Confirmed First-Version Boundary

First-version writes are limited to:

1. `ProjectRaw/`
2. Governance-allowed report/log paths under `01-Workflow/Knowledge-Governance/`

Direct writes to canonical or protected zones such as `20-KnowledgeHub/` remain outside this protocol and must continue to use proposal/approval workflows.

## Recommended Architecture

Extend the existing `GovernanceBackend` rather than creating a second MCP server. Keep the public tool surface in `scripts/mcp_governance_backend.py`, but move vault-content internals into a dedicated helper module so the backend stays declarative.

Recommended internal split:

1. `mcp_governance_backend.py`
   - declares new `vault_*` tools in `_tool_catalog()`
   - routes calls through `call_tool()`
   - keeps role visibility and risk evaluation unchanged
2. New helper module `scripts/vault_content_ops.py`
   - vault-relative path normalization and allowed-root checks
   - symlink / traversal rejection
   - Markdown read/search helpers
   - targeted append/upsert helpers
   - operation-log writes
3. Existing `mcp_access.py`
   - remains the single access evaluator
   - only policy data changes are needed to expose the new tools per role

## Tool Surface

| Tool | Risk | Layer | Purpose |
| --- | --- | --- | --- |
| `vault_list_paths` | `L0` | `system` | List allowed vault paths by root + glob + recursion. |
| `vault_read_markdown` | `L0` | `system` | Read one Markdown file with optional heading/date filtering. |
| `vault_search_markdown` | `L0` | `system` | Search across files or globs and return snippets plus paths. |
| `vault_upsert_markdown` | `L2` | `context` | Create/replace/upsert a governed Markdown file with hash preconditions. |
| `vault_append_markdown` | `L2` | `context` | Append at EOF or inside a heading/date section. |
| `vault_check_artifacts` | `L0` | `system` | Batch existence/content checks for cron health checks. |
| `vault_scan_curation_gaps` | `L1` | `system` | Return curation-gap statistics and candidate topics only. |

## Tool Contracts

### `vault_list_paths`

Input:

- `root`: allowed vault-relative root
- `glob`: optional glob
- `recursive`: boolean
- `include_dirs`: boolean
- `limit`: optional integer

Output:

- normalized `root`
- applied filters
- matched `paths`
- `count`
- `truncated`

### `vault_read_markdown`

Input:

- `path`: vault-relative Markdown path
- `heading`: optional heading selector
- `date_filter`: optional ISO date or date prefix
- `max_chars`: optional response limit

Output:

- `path`
- `hash`
- `found`
- `content`
- `section`
- `truncated`

### `vault_search_markdown`

Input:

- `paths` or `glob`
- `query` and/or `regex`
- `date_filter`
- `max_results`
- `max_chars_per_hit`

Output:

- search summary
- `matches` with `path`, `line`, `snippet`, and optional heading/date context

### `vault_upsert_markdown`

Input:

- `path`
- `content`
- `mode`: `create` | `replace` | `upsert`
- `expected_hash`: optional

Output:

- `path`
- `operation`
- `old_hash`
- `new_hash`
- `actor`
- `bytes_written`

### `vault_append_markdown`

Input:

- `path`
- `content`
- `target`: `eof` | `heading` | `date_section`
- `heading`: required when `target=heading`
- `date`: required when `target=date_section`
- `create_if_missing`
- `expected_hash`: optional

Output:

- `path`
- `operation`
- `old_hash`
- `new_hash`
- `actor`
- `created_file`
- `created_section`

### `vault_check_artifacts`

Input:

- `artifacts`: array of specs with fields such as:
  - `path_glob`
  - `required_date`
  - `content_contains`
  - `must_exist`

Output:

- per-artifact status
- `matched_paths`
- `missing`
- `content_failures`
- summary counts

### `vault_scan_curation_gaps`

Input:

- optional topic root filters
- thresholds such as minimum intake file count

Output:

- topic-level gap candidates
- intake/curation counts
- missing index flags
- empty output directory flags
- summary totals

This tool is analysis-only and must not mutate the vault or Hermes skills.

## Path and Safety Model

All tool paths must be **vault-relative**. The implementation must reject:

1. absolute paths
2. `..` traversal
3. symlink escapes
4. hidden/system directories outside the allowed tool scope

Allowed write roots in v1:

1. `ProjectRaw/`
2. approved governance report/log directories under `01-Workflow/Knowledge-Governance/`

Disallowed write roots in v1:

1. `20-KnowledgeHub/`
2. `.knowledge-registry/`
3. `.dbms-system/`
4. other protected/system-owned directories unless separately exposed by existing governance tools

## Access Model

The new tools should stay inside the current `evaluate_access()` contract.

Recommended first-phase role visibility:

| Role | Allowed vault content tools |
| --- | --- |
| `system-maintainer` | all `vault_*` tools |
| `vault-maintainer` | `vault_list_paths`, `vault_read_markdown`, `vault_search_markdown`, `vault_check_artifacts`, `vault_scan_curation_gaps` |
| `vault-user` | `vault_list_paths`, `vault_read_markdown`, `vault_search_markdown`, `vault_check_artifacts` |

Write tools remain `L2` and are intended for automation / system-maintainer sessions in the first phase.

## Operation Logging

Every successful write must record a lightweight operation log entry with at least:

1. `timestamp`
2. `actor`
3. `tool`
4. `operation`
5. `path`
6. `old_hash`
7. `new_hash`

The log should live under governance-controlled state, but it must not store full content snapshots.

## Cron Mapping

| Cron workflow | Vault MCP coverage |
| --- | --- |
| 饮食打卡判读 | `vault_read_markdown` + `vault_search_markdown` + `vault_append_markdown` |
| 每日个人提升主动询问 | `vault_read_markdown` + `vault_search_markdown` + `vault_append_markdown` |
| 每周个人提升周复盘 | `vault_search_markdown` + `vault_read_markdown` + `vault_upsert_markdown` |
| 每日新闻早报 | external search outside MCP + `vault_upsert_markdown` |
| AI 行业每日动态 | external search outside MCP + `vault_upsert_markdown` |
| 知识库健康检查 | `vault_check_artifacts` + `vault_upsert_markdown` |
| Hermes 策展深度扫描 | `vault_scan_curation_gaps` |
| GitHub Trending 每日早报 | external GitHub fetch outside MCP + `vault_upsert_markdown` + `vault_append_markdown` |

## Tests

1. Extend MCP catalog tests for name, schema, risk level, and role visibility.
2. Add temp-vault tests for:
   - path traversal rejection
   - symlink escape rejection
   - missing-file behavior
   - create / replace / upsert flows
   - append into heading/date targets
   - hash conflict rejection
3. Add prompt fixtures for the eight cron jobs to confirm their vault read/write portions are satisfiable through MCP.
4. Keep the current regression suite:
   - `python -m pytest tests/test_mcp_governance_server.py tests/test_mcp_access_evaluator.py tests/test_dbms_index_rebuild.py tests/test_dbms_state_reconcile.py -q`
   - `python scripts/validate_repo.py`
   - `python scripts/validate_data_repo.py F:/01-NativeLearnStore/obsidian_native/native_AllNotes_Governed`

## Rollout Notes

1. Add tool definitions and handlers first.
2. Update access-policy templates/examples and MCP docs in the same change.
3. Migrate cron jobs only after the new tool coverage is verified.
4. Keep the runtime `agents-knowledge-db` tool allowlist narrow and expand it only when the new tools are ready.

## Decision Summary

The approved direction is to keep a single governance-focused MCP server and extend it with a constrained vault content protocol. The protocol stays vault-relative, role-filtered, and audit-friendly, and it deliberately stops short of generic filesystem access or canonical-zone direct writes.
