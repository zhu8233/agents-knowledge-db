# Project Archiving

## Purpose

This scenario is for projects that already live in source control and already have working engineering structure.

The vault should capture:

- what the project is
- how it is organized
- what decisions matter
- what the current state is
- what risks and next steps exist

The vault should not become a code mirror.

## Recommended Layer Placement

### Intake

Use intake for:

- source maps
- archive manifests
- imported docs
- repo metadata snapshots

### Curation

Use curation for:

- project index
- overview
- architecture summary
- key module notes
- risk summary
- roadmap notes

### Canonical

Use canonical only for:

- durable project entry points
- stable cross-project summaries

## Default Archive Set

For most projects, create:

- `archive-manifest.md`
- `source-map.md`
- `00-项目索引.md`
- `01-项目概览.md`
- `02-架构总览.md`
- `05-当前状态与风险.md`

## Promotion Rule

If the project is still in active development, default to `curation`. Promote only the stable summary layer.
