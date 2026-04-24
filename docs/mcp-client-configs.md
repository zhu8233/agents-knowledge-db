# MCP Client Configs

## Purpose

This project is **server-first** for MCP-capable agents.

- If the agent supports MCP, 优先连接 MCP server.
- If the agent does not support MCP, fall back to `RULES.md`, adapters, and skills.

The server transport is `stdio`.

## Shared Launch Command

Use the launcher to reduce setup friction:

```bash
python scripts/run_mcp_server.py /path/to/your-vault --subject-id owner@example.com --auth-mode oauth
```

## Codex

```json
{
  "mcpServers": {
    "agents-knowledge-db": {
      "command": "python",
      "args": [
        "F:/01-NativeLearnStore/obsidian_native/obsidian-vault-governance-kit/scripts/run_mcp_server.py",
        "D:/your-governed-vault",
        "--subject-id",
        "owner@example.com",
        "--auth-mode",
        "oauth"
      ]
    }
  }
}
```

## Claude Desktop

```json
{
  "mcpServers": {
    "agents-knowledge-db": {
      "command": "python",
      "args": [
        "F:/01-NativeLearnStore/obsidian_native/obsidian-vault-governance-kit/scripts/run_mcp_server.py",
        "D:/your-governed-vault",
        "--subject-id",
        "maintainer@example.com",
        "--auth-mode",
        "oauth"
      ]
    }
  }
}
```

## Cherry Studio

```json
{
  "name": "agents-knowledge-db",
  "type": "stdio",
  "command": "python",
  "args": [
    "F:/01-NativeLearnStore/obsidian_native/obsidian-vault-governance-kit/scripts/run_mcp_server.py",
    "D:/your-governed-vault",
    "--subject-id",
    "reader@example.com",
    "--auth-mode",
    "oauth"
  ]
}
```

## Role Examples

- `vault-user`
  - `--subject-id reader@example.com --auth-mode oauth`
- `vault-maintainer`
  - `--subject-id maintainer@example.com --auth-mode oauth`
- `system-maintainer`
  - `--subject-id owner@example.com --auth-mode oauth`
