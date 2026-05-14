# MCP Client Configs

## Purpose

This project is **server-first** for MCP-capable agents.

- If the agent supports MCP, 优先连接 MCP server.
- If the agent does not support MCP, fall back to `RULES.md`, adapters, and skills.

The server transport is `stdio`.

## Vault Content Tooling

Current MCP clients will see role-filtered `vault_*` tools for governed Markdown workflows:

- `vault_list_paths`
- `vault_read_markdown`
- `vault_search_markdown`
- `vault_upsert_markdown`
- `vault_append_markdown`
- `vault_check_artifacts`
- `vault_scan_curation_gaps`

Write tools are only exposed to `system-maintainer` sessions in the first phase.

## Shared Launch Command

Use the launcher to reduce setup friction:

```bash
python scripts/run_mcp_server.py /path/to/your-vault --subject-id owner@example.com --auth-mode oauth
```

## Codex

Add this to `C:\Users\<you>\.codex\config.toml`:

```toml
[mcp_servers.agents-knowledge-db]
type = "stdio"
command = "python"
args = [
  "F:/01-NativeLearnStore/obsidian_native/obsidian-vault-governance-kit/scripts/run_mcp_server.py",
  "D:/your-governed-vault",
  "--subject-id",
  "owner@example.com",
  "--auth-mode",
  "oauth",
]
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

## Hermes (WSL2)

Add a dedicated stdio MCP entry in `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  agents-knowledge-db:
    type: stdio
    command: python3
    args:
      - /mnt/f/01-NativeLearnStore/obsidian_native/obsidian-vault-governance-kit/scripts/run_mcp_server.py
      - /mnt/f/01-NativeLearnStore/obsidian_native/native_AllNotes_Governed
      - --subject-id
      - owner@example.com
      - --auth-mode
      - token
    tools:
      include:
        - governance_whoami
        - governance_validate_data_repo
        - governance_rebuild_dbms_index
        - governance_reconcile_dbms_state
        - governance_list_topic_findings
```

Recommended Hermes constraints:

- keep the gateway `PATH` limited to native WSL binaries so cron does not pick Windows-side Unix tools by mistake
- store only the routing rule in Hermes memory: access to the governed data repo must go through `agents-knowledge-db`
- do not persist registry or findings snapshots in Hermes memory; read live state through MCP resources and tools

Recommended DBMS maintenance cron flow:

1. `governance_whoami`
2. `governance_validate_data_repo`
3. `governance_rebuild_dbms_index` or `governance_reconcile_dbms_state` when validation or state drift requires it
4. `governance_list_topic_findings`
