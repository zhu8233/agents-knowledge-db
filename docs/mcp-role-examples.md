# MCP Role Examples

## Purpose

Show typical MCP usage patterns for the three governance role buckets:

- `vault-user`
- `vault-maintainer`
- `system-maintainer`

## Vault User

Typical sequence:

1. `tools/list`
2. `tools/call` -> `governance_search_topics`
3. `tools/call` -> `governance_get_topic_context`
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
2. `tools/call` -> `governance_propose_registry_update`
3. `tools/call` -> `governance_create_promotion_proposal`
4. `tools/call` -> `governance_list_promotion_queue`
5. `tools/call` -> `governance_request_snapshot_review`

Expected boundary:

- can create proposals
- can inspect queue state
- cannot directly apply registry, snapshot, or promotion outcomes

## System Maintainer

Typical sequence:

1. `tools/call` -> `governance_evaluate_access`
2. `tools/call` -> `governance_apply_registry_update`
3. `tools/call` -> `governance_review_snapshot_upgrade`
4. `tools/call` -> `governance_apply_snapshot_upgrade`
5. `tools/call` -> `governance_review_promotion_proposal`
6. `tools/call` -> `governance_apply_promotion_proposal`

Expected boundary:

- full governance visibility
- high-risk actions still require approved proposals or explicit approval evidence
- applied actions update queue/registry state and append ledger entries
