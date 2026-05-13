#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import hashlib
from pathlib import Path
import subprocess
import argparse
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "core"


def repo_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except Exception:
        return None


def latest_tag() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(ROOT), "describe", "--tags", "--abbrev=0"],
            text=True,
        ).strip()
    except Exception:
        return None


def repo_dirty(pathspec: str | None = None) -> bool:
    try:
        command = ["git", "-C", str(ROOT), "status", "--porcelain"]
        if pathspec is not None:
            command.extend(["--", pathspec])
        output = subprocess.check_output(command, text=True)
        return bool(output.strip())
    except Exception:
        return False


def tree_digest(root: Path, *, exclude: set[str] | None = None) -> str:
    hasher = hashlib.sha256()
    excluded = exclude or set()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in excluded:
            continue
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def snapshot_content_digest() -> str:
    return tree_digest(CORE)


def current_snapshot_version() -> dict:
    release_tag = latest_tag()
    source_commit = repo_head()
    source_dirty = repo_dirty("core")
    content_digest = snapshot_content_digest()
    base_ref = release_tag or source_commit or "unversioned"
    snapshot_ref = f"{base_ref}:{content_digest[:12]}"
    return {
        "system_repo": "obsidian-vault-governance-kit",
        "release_tag": release_tag,
        "source_commit": source_commit,
        "source_dirty": source_dirty,
        "content_digest": content_digest,
        "snapshot_ref": snapshot_ref,
    }


def sync_snapshot(target_vault: Path, *, expected_version: dict | None = None) -> Path:
    snapshot = target_vault / ".dbms-system"
    staging = target_vault / ".dbms-system.__staging__"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    source_version = dict(expected_version or current_snapshot_version())
    version = {**source_version, "synced_at": datetime.now(timezone.utc).isoformat()}

    try:
        shutil.copy2(CORE / "RULES.md", staging / "RULES.md")
        shutil.copy2(CORE / "00-Agent-Onboarding.md", staging / "00-Agent-Onboarding.md")
        shutil.copy2(CORE / "skills-manifest.md", staging / "skills-manifest.md")
        shutil.copytree(CORE / "Interfaces", staging / "Interfaces", dirs_exist_ok=True)
        shutil.copytree(CORE / "Planning", staging / "Planning", dirs_exist_ok=True)
        shutil.copytree(CORE / "DBMS", staging / "DBMS", dirs_exist_ok=True)

        staged_digest = tree_digest(staging)
        if staged_digest != version["content_digest"]:
            raise RuntimeError("snapshot source changed during sync")

        (staging / "version.json").write_text(json.dumps(version, ensure_ascii=False, indent=2), encoding="utf-8")
        if snapshot.exists():
            shutil.rmtree(snapshot)
        staging.replace(snapshot)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise

    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync the system snapshot into a target data vault.")
    parser.add_argument("target_vault", help="Path to the governed data vault")
    args = parser.parse_args()
    snapshot = sync_snapshot(Path(args.target_vault).resolve())
    print(f"SNAPSHOT_SYNCED\t{snapshot}")


if __name__ == "__main__":
    main()
