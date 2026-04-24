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
- tool visibility and write posture

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

## Recommended Roles

- `system-maintainer`
- `vault-maintainer`
- `vault-user`

## Recommended First-Phase Behavior

- `vault-user`: read-only
- `vault-maintainer`: read + proposal path
- `system-maintainer`: full governance path with approval on `L3-L4`
