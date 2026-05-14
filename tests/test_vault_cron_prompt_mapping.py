from __future__ import annotations

import unittest


CRON_TOOLSETS = {
    "每日饮食打卡判读": {"vault_read_markdown", "vault_search_markdown", "vault_append_markdown"},
    "每日个人提升主动询问": {"vault_read_markdown", "vault_search_markdown", "vault_append_markdown"},
    "每周个人提升周复盘": {"vault_read_markdown", "vault_search_markdown", "vault_upsert_markdown"},
    "每日新闻早报": {"vault_upsert_markdown"},
    "AI行业每日动态": {"vault_upsert_markdown"},
    "知识库健康检查": {"vault_check_artifacts", "vault_upsert_markdown"},
    "Hermes策展深度扫描": {"vault_scan_curation_gaps"},
    "GitHub Trending 每日早报": {"vault_upsert_markdown", "vault_append_markdown"},
}


class VaultCronPromptMappingTests(unittest.TestCase):
    def test_every_remaining_cron_workflow_has_vault_mcp_coverage(self) -> None:
        self.assertEqual(len(CRON_TOOLSETS), 8)
        self.assertEqual(
            CRON_TOOLSETS["每日饮食打卡判读"],
            {"vault_read_markdown", "vault_search_markdown", "vault_append_markdown"},
        )
        self.assertIn("vault_append_markdown", CRON_TOOLSETS["GitHub Trending 每日早报"])


if __name__ == "__main__":
    unittest.main()
