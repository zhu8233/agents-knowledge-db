# MCP Server

## Purpose

This repository includes a minimal governance-focused MCP server for governed data repositories.

The current server is designed to:

- expose governed vault context through MCP `resources`
- expose guided governance workflows through MCP `prompts`
- expose role-filtered query and proposal actions through MCP `tools`
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

Tool visibility is role-filtered at runtime, and `L3-L4` executions require an approved proposal or explicit approval evidence even when the tool is visible. Snapshot apply additionally binds approval to the current `snapshotRef` / `compatibilityRef`.

## Design Boundary

This server does not replace:

- `RULES.md`
- `.knowledge-registry/`
- DBMS derived index files
- file-level recovery workflows

It is a protocol layer over the existing governance model.
