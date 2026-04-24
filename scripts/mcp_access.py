from __future__ import annotations

import json
from pathlib import Path


RISK_ORDER = {
    "L0": 0,
    "L1": 1,
    "L2": 2,
    "L3": 3,
    "L4": 4,
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def select_identity_mapping(policy: dict, subject_id: str, auth_mode: str) -> dict | None:
    for item in policy.get("identity_mappings", []):
        if item.get("subject_id") == subject_id and item.get("auth_mode") == auth_mode:
            return item
    return None


def select_role_policy(policy: dict, mcp_role: str) -> dict | None:
    for item in policy.get("role_policies", []):
        if item.get("mcp_role") == mcp_role:
            return item
    return None


def select_agent(roster: dict, agent_id: str) -> dict | None:
    for item in roster.get("agents", []):
        if item.get("agent_id") == agent_id:
            return item
    return None


def risk_allows(requested: str, maximum: str) -> bool:
    return RISK_ORDER[requested] <= RISK_ORDER[maximum]


def risk_requires_approval(requested: str, threshold: str) -> bool:
    return RISK_ORDER[requested] >= RISK_ORDER[threshold]


def tool_allowed(role_policy: dict, tool: str) -> bool:
    allowed_tools = role_policy.get("allowed_tools", [])
    return "*" in allowed_tools or tool in allowed_tools


def layer_allowed(agent: dict, target_layer: str) -> bool:
    return target_layer in agent.get("allowed_layers", []) and target_layer not in agent.get("forbidden_layers", [])


def evaluate_access(vault_root: Path, subject_id: str, auth_mode: str, tool: str, risk_level: str, target_layer: str) -> dict:
    root = Path(vault_root).resolve()
    roster = load_json(root / ".knowledge-registry" / "agent-roster.json")
    policy = load_json(root / "LocalOverrides" / "mcp-access-policy.json")

    mapping = select_identity_mapping(policy, subject_id, auth_mode)
    if mapping is None:
        return {
            "subject_id": subject_id,
            "auth_mode": auth_mode,
            "decision": policy.get("default_decision", "deny"),
            "reason": "identity-unmapped",
            "source_of_truth": [
                ".knowledge-registry/agent-roster.json",
                "LocalOverrides/mcp-access-policy.json",
            ],
        }

    agent = select_agent(roster, mapping["agent_id"])
    role_policy = select_role_policy(policy, mapping["mcp_role"])
    if agent is None or role_policy is None:
        return {
            "subject_id": subject_id,
            "auth_mode": auth_mode,
            "mapped_agent_id": mapping.get("agent_id"),
            "effective_role": mapping.get("mcp_role"),
            "decision": "deny",
            "reason": "missing-agent-or-role-policy",
            "source_of_truth": [
                ".knowledge-registry/agent-roster.json",
                "LocalOverrides/mcp-access-policy.json",
            ],
        }

    if not layer_allowed(agent, target_layer):
        return {
            "subject_id": subject_id,
            "auth_mode": auth_mode,
            "mapped_agent_id": mapping["agent_id"],
            "effective_role": mapping["mcp_role"],
            "agent_role": agent.get("role"),
            "decision": "deny",
            "reason": "layer-not-allowed",
            "risk_level": risk_level,
            "target_layer": target_layer,
            "source_of_truth": [
                ".knowledge-registry/agent-roster.json",
                "LocalOverrides/mcp-access-policy.json",
            ],
        }

    if tool in role_policy.get("proposal_only_tools", []):
        return {
            "subject_id": subject_id,
            "auth_mode": auth_mode,
            "mapped_agent_id": mapping["agent_id"],
            "effective_role": mapping["mcp_role"],
            "agent_role": agent.get("role"),
            "decision": "proposal-only",
            "risk_level": risk_level,
            "target_layer": target_layer,
            "requested_tool": tool,
            "suggested_tool": role_policy.get("suggested_proposal_tool"),
            "requires_approval": False,
            "approval_reason": None,
            "requires_registry_write": agent.get("requires_registry_write"),
            "default_operations": agent.get("default_operations", []),
            "source_of_truth": [
                ".knowledge-registry/agent-roster.json",
                "LocalOverrides/mcp-access-policy.json",
            ],
        }

    if not risk_allows(risk_level, role_policy["max_risk_level"]):
        return {
            "subject_id": subject_id,
            "auth_mode": auth_mode,
            "mapped_agent_id": mapping["agent_id"],
            "effective_role": mapping["mcp_role"],
            "agent_role": agent.get("role"),
            "decision": "deny",
            "reason": "risk-exceeds-policy",
            "risk_level": risk_level,
            "target_layer": target_layer,
            "source_of_truth": [
                ".knowledge-registry/agent-roster.json",
                "LocalOverrides/mcp-access-policy.json",
            ],
        }

    requires_approval = risk_requires_approval(risk_level, role_policy["require_approval_at_or_above"])
    approval_reason = "risk-threshold" if requires_approval else None

    if not tool_allowed(role_policy, tool):
        return {
            "subject_id": subject_id,
            "auth_mode": auth_mode,
            "mapped_agent_id": mapping["agent_id"],
            "effective_role": mapping["mcp_role"],
            "agent_role": agent.get("role"),
            "decision": "deny",
            "reason": "tool-not-allowed",
            "risk_level": risk_level,
            "target_layer": target_layer,
            "requested_tool": tool,
            "source_of_truth": [
                ".knowledge-registry/agent-roster.json",
                "LocalOverrides/mcp-access-policy.json",
            ],
        }

    return {
        "subject_id": subject_id,
        "auth_mode": auth_mode,
        "mapped_agent_id": mapping["agent_id"],
        "effective_role": mapping["mcp_role"],
        "agent_role": agent.get("role"),
        "decision": "allow",
        "risk_level": risk_level,
        "target_layer": target_layer,
        "requested_tool": tool,
        "requires_approval": requires_approval,
        "approval_reason": approval_reason,
        "requires_registry_write": agent.get("requires_registry_write"),
        "default_operations": agent.get("default_operations", []),
        "source_of_truth": [
            ".knowledge-registry/agent-roster.json",
            "LocalOverrides/mcp-access-policy.json",
        ],
    }
