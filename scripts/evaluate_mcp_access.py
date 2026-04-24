#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from mcp_access import evaluate_access


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate MCP access against local overrides and the agent roster.")
    parser.add_argument("target_vault", help="Path to the governed data vault")
    parser.add_argument("--subject-id", required=True, help="Authenticated subject identifier")
    parser.add_argument("--auth-mode", required=True, choices=["oauth", "token"], help="Authentication mode")
    parser.add_argument("--tool", required=True, help="Requested MCP tool name")
    parser.add_argument("--risk-level", required=True, choices=["L0", "L1", "L2", "L3", "L4"], help="Requested risk level")
    parser.add_argument("--target-layer", required=True, help="Requested target layer")
    args = parser.parse_args()

    root = Path(args.target_vault).resolve()
    decision = evaluate_access(root, args.subject_id, args.auth_mode, args.tool, args.risk_level, args.target_layer)
    print(json.dumps(decision, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
