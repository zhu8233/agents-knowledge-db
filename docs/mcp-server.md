# MCP Server

## Purpose

This repository includes a minimal governance-focused MCP server for governed data repositories.

The current server is designed to:

- expose governed vault context through MCP `resources`
- expose guided governance workflows through MCP `prompts`
- expose role-filtered query and proposal actions through MCP `tools`
- expose DBMS maintenance operations through guarded MCP tools instead of direct file access
- enforce OpenMetadata-style identity mapping and tool visibility using `LocalOverrides/mcp-access-policy.json`

## Current Entry Point

Run the server over stdio:

```bash
python scripts/mcp_governance_server.py /path/to/your-vault --subject-id owner@example.com --auth-mode oauth
```

## Current Transport

- stdio only

## Current Auth Model

The current implementation expects the caller identity to be provided at process start:

- `--subject-id`
- `--auth-mode` (`oauth` or `token`)

The server then evaluates access by combining:

- `.knowledge-registry/agent-roster.json`
- `LocalOverrides/mcp-access-policy.json`

## Current Resources

- `governance://rules/root`
- `governance://registry/vault`
- `governance://registry/agent-roster`
- `governance://registry/governance-proposals`
- `governance://registry/promotion-queue`
- `governance://local/compatibility-status`
- `governance://snapshot/version`
- `governance://registry/change-ledger`
- `governance://dbms/index/findings`
- `governance://dbms/index/file-index`
- `governance://dbms/index/topic-summary`
- `governance://dbms/state/last-index-run`
- `governance://dbms/reports/latest-index-audit`

## Current Prompts

- `onboard_agent_to_vault`
- `review_topic_health`
- `prepare_registry_repair`
- `governance_review_snapshot_upgrade`
- `governance_review_promotion_proposal`

## Current Tools

- `governance_search_topics`
- `governance_get_topic_context`
- `governance_list_topic_findings`
- `governance_validate_data_repo`
- `governance_rebuild_dbms_index`
- `governance_reconcile_dbms_state`
- `governance_whoami`
- `vault_list_paths`
- `vault_read_markdown`
- `vault_search_markdown`
- `vault_upsert_markdown`
- `vault_append_markdown`
- `vault_check_artifacts`
- `vault_scan_curation_gaps`
- `governance_propose_registry_update`
- `governance_create_promotion_proposal`
- `governance_list_promotion_queue`
- `governance_review_promotion_proposal`
- `governance_apply_promotion_proposal`
- `governance_apply_registry_update`
- `governance_evaluate_access`
- `governance_request_snapshot_review`
- `governance_review_snapshot_upgrade`
- `governance_apply_snapshot_upgrade`

Tool and resource visibility are role-filtered at runtime. Public read-only DBMS views remain available to mapped read-only users, while proposal stores, change ledgers, agent-roster state, and snapshot compatibility resources stay limited to maintainer roles. `governance_rebuild_dbms_index` and `governance_reconcile_dbms_state` are `L2` system-plane maintenance tools intended for `system-maintainer` sessions only. `L3-L4` executions still require an approved proposal or explicit approval evidence even when the tool is visible. Snapshot apply additionally binds approval to the current `snapshotRef` / `compatibilityRef`.

## Vault Content Protocol

The server also exposes governed vault content tools for cron-driven Markdown workflows:

- `vault_list_paths`
- `vault_read_markdown`
- `vault_search_markdown`
- `vault_upsert_markdown`
- `vault_append_markdown`
- `vault_check_artifacts`
- `vault_scan_curation_gaps`

These tools are vault-relative only. They do not expose generic filesystem access, and v1 write scope is limited to `ProjectRaw/` plus approved governance report/log paths.

## Hermes Integration Notes

- Prefer stdio launch through `scripts/run_mcp_server.py`.
- Hermes cron jobs that maintain a governed data repo should call MCP tools, not read or write vault files directly.
- Recommended maintenance flow: `governance_whoami` -> `governance_validate_data_repo` -> `governance_rebuild_dbms_index` / `governance_reconcile_dbms_state` when needed -> `governance_list_topic_findings`.
- Keep `.knowledge-registry/` as the source of truth and treat `DBMS/index/` plus `DBMS/state/` as derived state.

## Design Boundary

This server does not replace:

- `RULES.md`
- `.knowledge-registry/`
- DBMS derived index files
- file-level recovery workflows

It is a protocol layer over the existing governance model.
