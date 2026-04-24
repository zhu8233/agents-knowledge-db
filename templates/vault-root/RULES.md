# RULES.md

This is the single rule source for the governed vault.

## First Read Rule

Before changing any file in this vault:

1. Read `RULES.md`
2. Read `01-Workflow/Knowledge-Governance/00-Agent-Onboarding.md`
3. Read the nearest local adapter file if one exists
4. Read `.knowledge-registry/vault-registry.json`
5. Check whether your role can write to the target layer
6. Record important changes in `.knowledge-registry/change-ledger.jsonl`

For audit or scan tasks, also read:

7. `01-Workflow/Knowledge-Governance/DBMS/state/last-index-run.json`
8. `01-Workflow/Knowledge-Governance/DBMS/index/findings.json`

## Layer Model

- `system`
- `intake`
- `curation`
- `canonical`
- `archive`

## Write Rules

- Only Hermes and humans may directly update canonical knowledge
- Other agents must submit proposals for canonical changes
- Intake and curation may be edited by specialized agents if they update registry state as required
- Archive is append-oriented and should not be silently deleted

## Registry Files

- `.knowledge-registry/vault-registry.json`
- `.knowledge-registry/change-ledger.jsonl`
- `.knowledge-registry/agent-roster.json`
- `.knowledge-registry/promotion-queue.json`
- `.knowledge-registry/governance-proposals.json` (governance proposals, pending and reviewed; apply only through approved workflows)

## Onboarding File

Use `01-Workflow/Knowledge-Governance/00-Agent-Onboarding.md` as the procedural checklist for agents entering the vault.

## Compatibility Adapters

This vault may include:

- `CLAUDE.md`
- `AGENTS.md`
- `GEMINI.md`

These adapters should point back to `RULES.md`, not redefine it.
