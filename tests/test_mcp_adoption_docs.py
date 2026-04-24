from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class McpAdoptionDocsTests(unittest.TestCase):
    def test_client_config_doc_mentions_supported_clients_and_stdio(self) -> None:
        path = ROOT / "docs" / "mcp-client-configs.md"
        text = path.read_text(encoding="utf-8")

        self.assertIn("Codex", text)
        self.assertIn("Claude Desktop", text)
        self.assertIn("Cherry Studio", text)
        self.assertIn("stdio", text)
        self.assertIn("run_mcp_server.py", text)

    def test_server_first_doc_explains_when_to_use_mcp_vs_skills(self) -> None:
        path = ROOT / "docs" / "mcp-vs-skills-adoption.md"
        text = path.read_text(encoding="utf-8")

        self.assertIn("server-first", text)
        self.assertIn("优先连接 MCP server", text)
        self.assertIn("skills 是兼容接入层", text)
        self.assertIn("不支持 MCP", text)

    def test_adapters_and_skills_point_mcp_capable_agents_to_server_first(self) -> None:
        paths = [
            ROOT / "AGENTS.md",
            ROOT / "CLAUDE.md",
            ROOT / "GEMINI.md",
            ROOT / "templates" / "vault-root" / "AGENTS.md",
            ROOT / "templates" / "vault-root" / "CLAUDE.md",
            ROOT / "templates" / "vault-root" / "GEMINI.md",
            ROOT / "skills" / "vault-governance" / "SKILL.md",
            ROOT / "skills" / "vault-audit-repair" / "SKILL.md",
            ROOT / "skills" / "vault-canonical-promotion" / "SKILL.md",
        ]

        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertIn("MCP", text, str(path))
            self.assertIn("优先", text, str(path))


if __name__ == "__main__":
    unittest.main()
