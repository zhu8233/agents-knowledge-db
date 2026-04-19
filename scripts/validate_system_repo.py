#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def main() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_repo.py")], check=True)

    required = [
        ROOT / "core" / "RULES.md",
        ROOT / "core" / "Interfaces" / "20-Task-Types.md",
        ROOT / "core" / "Planning" / "20-Three-Planes.md",
        ROOT / "core" / "DBMS" / "00-System-Data-Isolation.md",
        ROOT / "scripts" / "install_to_vault.py",
        ROOT / "scripts" / "sync_system_snapshot.py",
        ROOT / "scripts" / "check_override_compat.py",
        ROOT / "scripts" / "validate_data_repo.py",
    ]
    for path in required:
        if not path.exists():
            fail(f"missing required system repo artifact: {path}")

    disallowed_fragments = [
        r"native_AllNotes_Governed",
        r"F:\01-NativeLearnStore",
    ]
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if ".worktrees" in path.parts:
            continue
        if path.name == "validate_system_repo.py":
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".pyc"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for fragment in disallowed_fragments:
            if fragment in text:
                fail(f"system repo contains disallowed local reference '{fragment}' in {path}")

    print("VALIDATE_SYSTEM_REPO_OK")


if __name__ == "__main__":
    main()
