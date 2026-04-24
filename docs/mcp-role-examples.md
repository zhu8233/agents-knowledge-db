# MCP Role Examples

## Purpose

Show typical MCP usage patterns for the three governance role buckets:

- `vault-user`
- `vault-maintainer`
- `system-maintainer`

## Vault User

Typical sequence:

1. `tools/list`
2. `tools/call` -> `search_topics`
3. `tools/call` -> `get_topic_context`
4. `resources/read` -> `governance://rules/root`
5. `resources/read` -> `governance://dbms/index/findings`

Expected boundary:

- read-only toolset
- no registry apply
- no snapshot apply
- no promotion review/apply

## Vault Maintainer

Typical sequence:

1. `tools/list`
2. `tools/call` -> `propose_registry_update`
3. `tools/call` -> `create_promotion_proposal`
4. `tools/call` -> `list_promotion_queue`
5. `tools/call` -> `request_snapshot_review`

Expected boundary:

- can create proposals
- can inspect queue state
- cannot directly apply registry, snapshot, or promotion outcomes

## System Maintainer

Typical sequence:

1. `tools/call` -> `evaluate_access`
2. `tools/call` -> `apply_registry_update`
3. `tools/call` -> `review_snapshot_upgrade`
4. `tools/call` -> `apply_snapshot_upgrade`
5. `tools/call` -> `review_promotion_proposal`
6. `tools/call` -> `apply_promotion_proposal`

Expected boundary:

- full governance visibility
- high-risk actions still emit explicit review/apply metadata
- applied actions update queue/registry state and append ledger entries
