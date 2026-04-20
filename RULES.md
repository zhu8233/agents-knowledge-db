# RULES.md

This repository publishes the system kernel for Agents Knowledge DB: an agent-driven personal knowledge database system.

## Project Rule Source

The canonical design of the governance model lives in:

- `docs/architecture.md`
- `docs/portable-adoption.md`
- `templates/vault-root/RULES.md`

## Editing Rules

- Keep the governance model platform-neutral by default
- Put platform-specific entry behavior in adapter files, not in the core rules
- Treat schemas as machine contracts
- Treat skills as behavior contracts
- Treat templates as adoption assets

## Release Rule

If a change updates the governance model, check whether all three also need updates:

- `schemas/`
- `skills/`
- `templates/vault-root/`
