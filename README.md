# Agents Knowledge DB

An agent-driven personal knowledge database system with a productized governance kernel and a snapshot-consuming data repository model.

This project is for people who want a personal or team knowledge database that can be operated by:

- humans
- ingestion workflows
- specialist agents
- coordinator agents
- multiple model ecosystems

without losing topic identity, source lineage, canonical stability, system integrity, or long-term maintainability.

## Why This Exists

Most vaults break under multi-agent maintenance for the same reasons:

- every agent reads different entry files
- raw intake and durable knowledge get mixed together
- topic identity is implicit in folder names instead of explicit in registry state
- updates happen without a shared change log
- "final" notes are overwritten by working notes

This kit solves that by combining:

1. one human rule source: `RULES.md`
2. compatibility entry files: `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`
3. one machine fact layer: `.knowledge-registry/`
4. a portable skill pack for agent behavior
5. promotion and audit workflows to control drift
6. a project-archiving workflow for bringing maintained engineering work into the vault
7. a dual-repo model where the governance system can be released independently from the data vault

## Design

### Core model

The governance model has five layers:

| Layer | Purpose | Typical examples |
|------|---------|------------------|
| `system` | rules, schemas, registries, workflow docs | `RULES.md`, `.knowledge-registry/` |
| `intake` | raw or machine-landed material | imports, source dumps, NotebookLM outputs |
| `curation` | reorganized working knowledge | topic indexes, draft syntheses, cleaned notes |
| `canonical` | durable, high-findability knowledge | stable summaries, durable topic indexes |
| `archive` | frozen or retired material | superseded canonical notes, retired topics |

### Rule source strategy

`RULES.md` is the single rule source.

`CLAUDE.md`, `AGENTS.md`, and `GEMINI.md` are thin adapters that point back to `RULES.md`.

That lets the same vault work across multiple agent ecosystems without making the governance model vendor-specific.

### Dual-repo strategy

This project is the **system repository**.

A governed knowledge database acts as the **data repository**.

The intended relationship is:

- the system repo publishes reusable governance releases
- the data repo consumes a read-only snapshot in `.dbms-system/`
- local differences live in `LocalOverrides/`
- database-admin tooling manages snapshot upgrade proposals instead of auto-overwrite

### Registry strategy

`.knowledge-registry/` stores machine-readable facts:

- `vault-registry.json`
- `agent-roster.json`
- `promotion-queue.json`
- `change-ledger.jsonl`

The registry is the source of truth for:

- topic IDs
- object identity
- layer placement
- agent roles
- promotion state
- change history

### Agent behavior strategy

The skill pack teaches agents how to:

- enter a governed vault
- identify layer and topic
- decide if they can write
- route work into intake, curation, project archiving, promotion, audit, or Hermes coordination

## Repository Layout

```text
.
├── README.md
├── RULES.md
├── core/
├── CLAUDE.md
├── AGENTS.md
├── GEMINI.md
├── docs/
├── schemas/
├── scripts/
├── skills/
├── templates/vault-root/
└── examples/portable-vault/
```

See also:

- `docs/dual-repo-architecture.md`

## Included Components

### Skill pack

- `vault-governance`
- `vault-intake-curation`
- `vault-project-archiving`
- `vault-canonical-promotion`
- `vault-audit-repair`
- `hermes-coordination`

### Schema pack

- `schemas/vault-registry.schema.json`
- `schemas/agent-roster.schema.json`
- `schemas/promotion-queue.schema.json`
- `schemas/change-ledger-entry.schema.json`

### Vault bootstrap templates

- `templates/vault-root/RULES.md`
- `templates/vault-root/CLAUDE.md`
- `templates/vault-root/AGENTS.md`
- `templates/vault-root/GEMINI.md`
- `templates/vault-root/.knowledge-registry/*`
- `templates/vault-root/.dbms-system/*`
- `templates/vault-root/LocalOverrides/*`

### Core system snapshot source

- `core/RULES.md`
- `core/Interfaces/`
- `core/Planning/`
- `core/DBMS/`
- `core/skills-manifest.md`

### Example governed data repository

- `examples/portable-vault/`

## Quickstart

### 1. Copy templates into your vault root

Copy everything under `templates/vault-root/` into the root of the target vault.

At minimum you want:

- `RULES.md`
- one or more adapter files
- `.knowledge-registry/`

### 2. Adjust the templates

Edit:

- `RULES.md`
- `.knowledge-registry/agent-roster.json`
- `.knowledge-registry/vault-registry.json`

Customize:

- agent IDs
- local topic naming rules
- local folder conventions
- any platform-specific adapter wording
- local override files

### 3. Register your first topics

Add 3-5 real topics to `vault-registry.json`.

Do not try to register the entire vault at once.

### 4. Install the skill pack

Copy the folders under `skills/` into your agent skill directory, or vendor them into your own agent setup.

### 4.5 Sync the system snapshot

Use the provided script to copy the core system into the target data vault:

```bash
python scripts/sync_system_snapshot.py /path/to/your-vault
```

### 5. Start with intake and curation only

Do not enable canonical promotion on day one.

First verify that:

- agents reliably read `RULES.md`
- topic IDs stay consistent
- change ledger entries are created

### 6. Enable canonical promotion

Once the team is comfortable:

- turn on the promotion queue workflow
- give Hermes or a human the coordinator role

## Agent Onboarding

The intended onboarding path for any agent is:

1. read `RULES.md`
2. read the nearest adapter file if present
3. read `.knowledge-registry/vault-registry.json`
4. determine target `topic_id`
5. determine target layer
6. check write authority in `agent-roster.json`
7. route to the appropriate skill

If you want "any agent can enter and align quickly", this onboarding path is the minimum contract.

## Project Archiving

This repository includes a dedicated scenario for archiving an already-maintained engineering project into the vault.

Use `$vault-project-archiving` when you need to:

- preserve project knowledge from an existing repo
- create project overview and architecture notes
- map source lineage without dumping raw code into the vault
- keep active project material in curation until a stable summary deserves promotion

## Validation

This repository includes a self-contained validator:

```bash
python scripts/validate_repo.py
```

It checks:

- required repo files exist
- skill metadata is present
- no `TODO` placeholders remain in `SKILL.md`
- `openai.yaml` prompts mention the correct `$skill-name`
- JSON and JSONL files parse
- template and example vault registry files parse
- dual-repo support files exist
- core system snapshot source exists

You can also run:

```bash
python scripts/validate_system_repo.py
python scripts/validate_data_repo.py /path/to/your-vault
```

GitHub Actions also runs this validation on push and pull request.

## Publishing

This repository is designed to be published on GitHub as the open-source system repository for Agents Knowledge DB.

Recommended release steps:

1. run `python scripts/validate_repo.py`
2. review `README.md`
3. review `templates/vault-root/`
4. review `examples/portable-vault/`
5. commit and push

## Limitations

This kit improves convergence, but does not create absolute enforcement by itself.

Skills guide behavior.
Registries carry facts.
Audit catches drift.

If an agent refuses to read the rules, no documentation package can fully save it. This is why the model uses both adapter files and registry-backed audits.

## Current Status

This is a publishable v1 system repository:

- architecture defined
- templates included
- example vault included
- skill pack included
- validation script included
- GitHub workflow included

This repository is also the foundation of the Agents Knowledge DB dual-repo model:

- productized system repo
- data repo snapshot consumption
- local override layer
- database-admin upgrade flow

The main recommended next step after publishing is real multi-agent regression testing against live vault tasks.
