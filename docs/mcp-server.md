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
- `review_snapshot_upgrade`
- `review_promotion_proposal`

## Current Tools

- `search_topics`
- `get_topic_context`
- `list_topic_findings`
- `validate_data_repo`
- `propose_registry_update`
- `create_promotion_proposal`
- `list_promotion_queue`
- `review_promotion_proposal`
- `apply_promotion_proposal`
- `apply_registry_update`
- `evaluate_access`
- `request_snapshot_review`
- `review_snapshot_upgrade`
- `apply_snapshot_upgrade`

Tool visibility is role-filtered at runtime.

## Design Boundary

This server does not replace:

- `RULES.md`
- `.knowledge-registry/`
- DBMS derived index files
- file-level recovery workflows

It is a protocol layer over the existing governance model.
