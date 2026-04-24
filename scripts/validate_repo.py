#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent


REQUIRED_FILES = [
    "README.md",
    "RULES.md",
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "schemas/vault-registry.schema.json",
    "schemas/agent-roster.schema.json",
    "schemas/promotion-queue.schema.json",
    "schemas/governance-proposals.schema.json",
    "schemas/change-ledger-entry.schema.json",
    "schemas/dbms-file-index-entry.schema.json",
    "schemas/dbms-topic-summary.schema.json",
    "schemas/dbms-findings.schema.json",
    "schemas/dbms-index-run-state.schema.json",
    "schemas/mcp-access-policy.schema.json",
    "docs/agent-indexing.md",
    "docs/mcp-access-model.md",
    "docs/mcp-role-examples.md",
    "docs/mcp-server.md",
    "docs/quickstart.md",
    "docs/github-publishing.md",
    "docs/agent-regression-scenarios.md",
    "docs/dual-repo-architecture.md",
    "docs/project-archiving.md",
    "docs/regression-plan.md",
    "core/RULES.md",
    "core/Interfaces/20-Task-Types.md",
    "core/Planning/20-Three-Planes.md",
    "core/DBMS/00-System-Data-Isolation.md",
    "core/DBMS/20-Materialized-Index-Layer.md",
    "templates/vault-root/RULES.md",
    "templates/vault-root/.dbms-system/README.md",
    "templates/vault-root/.dbms-system/version.json",
    "templates/vault-root/LocalOverrides/00-本地覆盖说明.md",
    "templates/vault-root/LocalOverrides/compatibility-status.json",
    "templates/vault-root/LocalOverrides/mcp-access-policy.json",
    "templates/vault-root/01-Workflow/Knowledge-Governance/00-Agent-Onboarding.md",
    "templates/vault-root/01-Workflow/Knowledge-Governance/DBMS/index/file-index.jsonl",
    "templates/vault-root/01-Workflow/Knowledge-Governance/DBMS/index/topic-summary.json",
    "templates/vault-root/01-Workflow/Knowledge-Governance/DBMS/index/findings.json",
    "templates/vault-root/01-Workflow/Knowledge-Governance/DBMS/state/last-index-run.json",
    "examples/portable-vault/RULES.md",
    "examples/portable-vault/01-Workflow/Knowledge-Governance/00-Agent-Onboarding.md",
    "examples/portable-vault/01-Workflow/Knowledge-Governance/DBMS/index/file-index.jsonl",
    "examples/portable-vault/01-Workflow/Knowledge-Governance/DBMS/index/topic-summary.json",
    "examples/portable-vault/01-Workflow/Knowledge-Governance/DBMS/index/findings.json",
    "examples/portable-vault/01-Workflow/Knowledge-Governance/DBMS/state/last-index-run.json",
    "tests/regression-prompts/01-first-entry.md",
    "tests/regression-prompts/02-raw-source-update.md",
    "tests/regression-prompts/03-canonical-temptation.md",
    "tests/regression-prompts/04-topic-collision.md",
    "tests/regression-prompts/05-project-archiving.md",
    "scripts/smoke_install.py",
    "scripts/install_to_vault.py",
    "scripts/sync_system_snapshot.py",
    "scripts/check_override_compat.py",
    "scripts/evaluate_mcp_access.py",
    "scripts/mcp_access.py",
    "scripts/mcp_governance_backend.py",
    "scripts/mcp_governance_server.py",
    "scripts/proposal_store.py",
    "scripts/promotion_queue.py",
    "scripts/registry_updates.py",
    "scripts/snapshot_upgrade.py",
    "scripts/rebuild_dbms_index.py",
    "scripts/validate_system_repo.py",
    "scripts/validate_data_repo.py",
]


SKILL_NAMES = [
    "vault-governance",
    "vault-intake-curation",
    "vault-project-archiving",
    "vault-canonical-promotion",
    "vault-audit-repair",
    "hermes-coordination",
]


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def require_files() -> None:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
    if missing:
        fail(f"missing required files: {missing}")


def parse_json(path: Path) -> None:
    with path.open("r", encoding="utf-8") as fh:
        json.load(fh)


def parse_jsonl(path: Path) -> None:
    with path.open("r", encoding="utf-8") as fh:
        for idx, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                fail(f"invalid JSONL at {path} line {idx}: {exc}")


def validate_skill(skill_name: str) -> None:
    skill_dir = ROOT / "skills" / skill_name
    skill_md = skill_dir / "SKILL.md"
    openai_yaml = skill_dir / "agents" / "openai.yaml"
    if not skill_md.exists():
        fail(f"missing SKILL.md for {skill_name}")
    if not openai_yaml.exists():
        fail(f"missing openai.yaml for {skill_name}")

    skill_text = skill_md.read_text(encoding="utf-8")
    if "TODO" in skill_text:
        fail(f"skill {skill_name} still contains TODO")
    if not skill_text.startswith("---\nname: "):
        fail(f"skill {skill_name} missing frontmatter header")
    if f"name: {skill_name}" not in skill_text:
        fail(f"skill {skill_name} frontmatter name mismatch")
    if "description: Use when" not in skill_text:
        fail(f"skill {skill_name} description should start with 'Use when'")

    yaml_text = openai_yaml.read_text(encoding="utf-8")
    if f"Use ${skill_name}" not in yaml_text:
        fail(f"skill {skill_name} default_prompt must mention ${skill_name}")


def validate_adapter_points_to_rules(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "RULES.md" not in text:
        fail(f"{path} does not point to RULES.md")


def main() -> None:
    require_files()

    for json_path in (ROOT / "schemas").glob("*.json"):
        parse_json(json_path)

    for registry in [
        ROOT / "templates" / "vault-root" / ".knowledge-registry" / "vault-registry.json",
        ROOT / "templates" / "vault-root" / ".knowledge-registry" / "agent-roster.json",
        ROOT / "templates" / "vault-root" / ".knowledge-registry" / "governance-proposals.json",
        ROOT / "templates" / "vault-root" / ".knowledge-registry" / "promotion-queue.json",
        ROOT / "templates" / "vault-root" / "LocalOverrides" / "mcp-access-policy.json",
        ROOT / "templates" / "vault-root" / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "topic-summary.json",
        ROOT / "templates" / "vault-root" / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "findings.json",
        ROOT / "templates" / "vault-root" / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-index-run.json",
        ROOT / "examples" / "portable-vault" / ".knowledge-registry" / "vault-registry.json",
        ROOT / "examples" / "portable-vault" / ".knowledge-registry" / "agent-roster.json",
        ROOT / "examples" / "portable-vault" / ".knowledge-registry" / "governance-proposals.json",
        ROOT / "examples" / "portable-vault" / ".knowledge-registry" / "promotion-queue.json",
        ROOT / "examples" / "portable-vault" / "LocalOverrides" / "mcp-access-policy.json",
        ROOT / "examples" / "portable-vault" / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "topic-summary.json",
        ROOT / "examples" / "portable-vault" / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "findings.json",
        ROOT / "examples" / "portable-vault" / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "last-index-run.json",
    ]:
        parse_json(registry)

    for ledger in [
        ROOT / "templates" / "vault-root" / ".knowledge-registry" / "change-ledger.jsonl",
        ROOT / "templates" / "vault-root" / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "file-index.jsonl",
        ROOT / "examples" / "portable-vault" / ".knowledge-registry" / "change-ledger.jsonl",
        ROOT / "examples" / "portable-vault" / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "index" / "file-index.jsonl",
    ]:
        parse_jsonl(ledger)

    for adapter in [
        ROOT / "CLAUDE.md",
        ROOT / "AGENTS.md",
        ROOT / "GEMINI.md",
        ROOT / "templates" / "vault-root" / "CLAUDE.md",
        ROOT / "templates" / "vault-root" / "AGENTS.md",
        ROOT / "templates" / "vault-root" / "GEMINI.md",
        ROOT / "examples" / "portable-vault" / "CLAUDE.md",
        ROOT / "examples" / "portable-vault" / "AGENTS.md",
        ROOT / "examples" / "portable-vault" / "GEMINI.md",
    ]:
        validate_adapter_points_to_rules(adapter)

    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    for marker in ["## Design", "## Quickstart", "## Agent Onboarding", "## Validation", "## Publishing"]:
        if marker not in readme_text:
            fail(f"README.md missing section: {marker}")

    for skill_name in SKILL_NAMES:
        validate_skill(skill_name)

    print("VALIDATION_OK")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover
        fail(str(exc))
