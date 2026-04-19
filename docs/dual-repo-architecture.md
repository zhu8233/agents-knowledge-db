# Dual Repo Architecture

## Purpose

Separate the governance system from the governed data vault.

## Repositories

### System repository

`obsidian-vault-governance-kit`

Owns:

- governance kernel
- interfaces
- planning
- DBMS rules
- schemas
- skills
- templates
- tooling

### Data repository

Any governed vault, for example:

- `your-governed-vault`

Owns:

- real data
- local registry
- local reports
- local state
- local overrides
- read-only snapshot of the system release

## Data Repo Read Order

1. local `RULES.md`
2. `.dbms-system/`
3. `LocalOverrides/`
4. `.knowledge-registry/`

## Why snapshots instead of direct repo reads

- better portability
- stable versioning
- no cross-repo path dependency
- easier upgrade review
