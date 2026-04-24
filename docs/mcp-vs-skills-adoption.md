# MCP Vs Skills Adoption

## Position

This project is **server-first**.

- 对支持 MCP 的 agent：`优先连接 MCP server`
- 对不支持 MCP 的 agent：回退到 `RULES.md`、adapters 和 skills

`skills 是兼容接入层`，不是第二套治理引擎。

## When To Use MCP

Use MCP when the agent:

- supports stdio MCP
- needs structured tools, resources, and prompts
- needs role-aware capability filtering
- should participate in proposal/review/apply governance workflows

## When To Use Skills

Use skills when the agent:

- 不支持 MCP
- only supports prompts, adapters, or local skill packs
- still needs guided governance behavior inside the vault

## Operational Difference

### MCP Server

- one shared protocol surface
- one permission model
- one proposal/review/apply state machine
- best for multi-agent consistency

### Skills

- behavior guidance only
- compatible fallback for non-MCP agents
- should point MCP-capable agents back to the server
- should not reimplement high-risk governance mutations
