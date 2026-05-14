# MCP Access Model

## Purpose

Define a portable MCP access contract for governed data repositories.

This model is designed to support:

- user sessions authenticated through `oauth`
- service or agent sessions authenticated through `token`
- identity-to-agent mapping without moving local auth details into the registry source of truth

## Design Boundary

`.knowledge-registry/agent-roster.json` remains the source of truth for:

- agent identity
- authority boundaries
- allowed layers
- default operations

`LocalOverrides/mcp-access-policy.json` defines environment-specific MCP access mapping for:

- authenticated subject IDs
- auth mode
- MCP-facing role buckets
- tool visibility, resource visibility, and write posture

This keeps transport and identity integration local while preserving portable governance rules.

## Evaluation Model

An MCP access evaluation should resolve:

1. authenticated `subject_id`
2. `auth_mode`
3. mapped `agent_id`
4. mapped MCP role
5. requested tool
6. requested risk level
7. target layer

The result should then return one of:

- `allow`
- `proposal-only`
- `deny`

and whether elevated approval is required.

When the resolved action is `L3-L4` and `requires_approval` is `true`, execution must still stop unless the caller supplies either:

- an approved governance `proposal_id`
- explicit approval evidence attached to the MCP tool call

For snapshot apply, both approval paths must stay bound to the current apply context:

- approved proposals must be `snapshot_upgrade` proposals that match the current `snapshotRef` and `compatibilityRef`
- explicit approval evidence must match the authenticated subject and the current `snapshot_ref` / `compatibility_ref`

## Recommended Roles

- `system-maintainer`
- `vault-maintainer`
- `vault-user`

## Recommended First-Phase Behavior

- `vault-user`: `vault_list_paths`, `vault_read_markdown`, `vault_search_markdown`, `vault_check_artifacts`
- `vault-maintainer`: all vault-user tools plus `vault_scan_curation_gaps`
- `system-maintainer`: full governance path, including `L2` DBMS maintenance tools plus `vault_upsert_markdown` and `vault_append_markdown`, with approval on `L3-L4` plus execution-time proof through a matching approved proposal or context-bound explicit approval evidence

Write tools stay `L2` and are intended for system-maintainer or automation sessions in the first phase. They must stay vault-relative and are limited to `ProjectRaw/` plus approved governance report/log paths.

## DBMS Maintenance Boundary

- `governance_rebuild_dbms_index` and `governance_reconcile_dbms_state` operate on derived DBMS state only
- these tools must not be treated as registry truth writes
- Hermes or any other MCP-capable coordinator should invoke them through MCP instead of directly editing DBMS files
