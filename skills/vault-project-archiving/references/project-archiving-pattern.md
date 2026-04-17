# Project Archiving Pattern

## Intent

Bring an already-maintained engineering project into a governed vault without turning the vault into a code mirror.

## Recommended Outputs By Layer

### Intake

- `archive-manifest.md`
- `source-map.md`
- imported source metadata

### Curation

- `00-项目索引.md`
- `01-项目概览.md`
- `02-架构总览.md`
- `03-关键模块说明.md` when justified
- `04-决策记录.md` when available
- `05-当前状态与风险.md`
- `06-路线图与下一步.md`

### Canonical

Only after review:

- stable project index
- durable project summary

## Archive Depths

### Light

Use when you only need a searchable project entry point.

- project index
- overview
- source map

### Standard

Recommended default.

- project index
- overview
- architecture summary
- current state and risk
- source map

### Deep

Use for strategically important projects.

- all standard outputs
- key module summaries
- decision rollup
- workflow, deploy, and dependency notes when stable enough

## Minimal Metadata To Preserve

- repo name
- source path or URL
- default branch if known
- archive date
- key entry files
- known upstream systems

## Safety Rule

If the project is still actively changing, keep the working knowledge in `curation` unless a stable cross-project summary clearly deserves canonical placement.
