from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

ALLOWED_READ_ROOTS = (
    Path("ProjectRaw"),
    Path("01-Workflow") / "Knowledge-Governance",
)
ALLOWED_WRITE_ROOTS = (
    Path("ProjectRaw"),
    Path("01-Workflow") / "Knowledge-Governance" / "DBMS" / "reports",
)
_MARKDOWN_HEADING_RE = re.compile(r"(?m)^(#{1,6})[ \t]+(.+?)\s*$")
_DATE_LINE_RE = re.compile(r"(?m)^\d{4}-\d{2}-\d{2}(?:\s*$|.*$)")
_DATE_STEM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _normalize_relative_path(path: str) -> Path:
    relative = Path(path)
    if relative.is_absolute():
        raise ValueError("path must be vault-relative")
    if ".." in relative.parts:
        raise ValueError("path must not contain parent traversal")
    return relative


def _resolve_within_vault(vault_root: Path, path: str) -> tuple[Path, Path]:
    relative = _normalize_relative_path(path)
    candidate = (vault_root / relative).resolve()
    try:
        candidate.relative_to(vault_root.resolve())
    except ValueError as exc:
        raise ValueError("path escapes the vault root") from exc
    return relative, candidate


def _resolved_relative_to_vault(vault_root: Path, resolved_path: Path) -> Path:
    try:
        return resolved_path.relative_to(vault_root.resolve())
    except ValueError as exc:
        raise ValueError("path escapes the vault root") from exc


def _relative_is_within_root(relative: Path, root: Path) -> bool:
    relative_parts = relative.parts
    root_parts = root.parts
    # Apply case-folding on filesystems that are case-insensitive by default:
    # Windows (NTFS) and macOS (APFS/HFS+). Linux (ext4, etc.) is case-sensitive,
    # so strict matching is correct there.
    if os.name == "nt" or sys.platform == "darwin":
        relative_parts = tuple(part.casefold() for part in relative_parts)
        root_parts = tuple(part.casefold() for part in root_parts)
    return relative_parts == root_parts or relative_parts[: len(root_parts)] == root_parts


def _require_positive_int(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


def _normalize_glob_pattern(pattern: str) -> str:
    normalized = _normalize_relative_path(pattern)
    return str(normalized).replace("\\", "/")


def _write_operation_log(
    vault_root: Path,
    *,
    actor: str,
    tool: str,
    operation: str,
    path: str,
    old_hash: str | None,
    new_hash: str,
) -> None:
    log_path = vault_root / "01-Workflow" / "Knowledge-Governance" / "DBMS" / "state" / "mcp-operation-log.jsonl"
    vault_resolved = vault_root.resolve()
    for candidate in (log_path, *log_path.parents):
        # Resolve the candidate for boundary comparison so that OS-level symlinks
        # (e.g. /var -> /private/var on macOS) don't prevent the loop from stopping
        # at the vault root.
        try:
            candidate_resolved = candidate.resolve()
        except OSError:
            # Fallback: use the unresolved candidate. On macOS this means the
            # boundary comparison (candidate_resolved == vault_resolved) will
            # fail for paths that go through /var -> /private/var — the loop
            # will over-iterate past the vault root and continue checking
            # parent dirs for user-created symlinks. This is a degraded but
            # safe path: the symlink check still rejects malicious redirects;
            # it just does slightly more work than necessary.
            candidate_resolved = candidate
        if candidate_resolved == vault_resolved.parent:
            break
        if candidate.exists() and candidate.is_symlink():
            raise ValueError("operation log path must not be a symlink")
        if candidate_resolved == vault_resolved:
            break
    resolved_log_path = log_path.resolve()
    try:
        resolved_log_path.relative_to(vault_resolved)
    except ValueError as exc:
        raise ValueError("operation log path escapes the vault root") from exc
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "tool": tool,
        "operation": operation,
        "path": path,
        "old_hash": old_hash,
        "new_hash": new_hash,
    }
    with resolved_log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _append_to_end(text: str, content: str) -> str:
    return text + content


def _append_to_heading(text: str, heading: str, content: str, *, create_if_missing: bool) -> tuple[str, bool]:
    normalized_heading = heading.strip()
    try:
        start, end, _ = _slice_markdown_heading_section_bounds(
            text,
            lambda match: match.group(0).strip() == normalized_heading,
        )
        return text[:end] + content + text[end:], False
    except ValueError:
        if not create_if_missing:
            raise ValueError(f"heading not found: {heading}")
        prefix = text
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n"
        return prefix + normalized_heading + "\n" + content, True


def _append_to_date_section(text: str, date: str, content: str, *, create_if_missing: bool) -> tuple[str, bool]:
    try:
        start, section = _extract_date_section_with_start(text, date)
        end = start + len(section)
        return text[:end] + content + text[end:], False
    except ValueError:
        if not create_if_missing:
            raise ValueError(f"date section not found: {date}")
        prefix = text
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n"
        return prefix + f"## {date}\n" + content, True


def _ensure_allowed_read_root(relative: Path) -> None:
    if any(_relative_is_within_root(relative, root) for root in ALLOWED_READ_ROOTS):
        return
    allowed_roots = ", ".join(str(root).replace("\\", "/") for root in ALLOWED_READ_ROOTS)
    raise ValueError(f"path must be inside an allowed read root: {allowed_roots}")


def _resolve_allowed_read_path(vault_root: Path, path: str) -> tuple[Path, Path]:
    relative, candidate = _resolve_within_vault(vault_root, path)
    _ensure_allowed_read_root(relative)
    _ensure_allowed_read_root(_resolved_relative_to_vault(vault_root, candidate))
    return relative, candidate


def _ensure_allowed_write_root(relative: Path) -> None:
    if any(_relative_is_within_root(relative, root) for root in ALLOWED_WRITE_ROOTS):
        return
    allowed_roots = ", ".join(str(root).replace("\\", "/") for root in ALLOWED_WRITE_ROOTS)
    raise ValueError(f"path must be inside an allowed write root: {allowed_roots}")


def _resolve_allowed_write_path(vault_root: Path, path: str) -> tuple[Path, Path]:
    relative, candidate = _resolve_within_vault(vault_root, path)
    if relative.suffix.lower() != ".md":
        raise ValueError("path must point to a Markdown file")
    _ensure_allowed_write_root(relative)
    try:
        _ensure_allowed_write_root(_resolved_relative_to_vault(vault_root, candidate))
    except ValueError:
        raise
    return relative, candidate


def _resolve_allowed_glob(vault_root: Path, pattern: str) -> list[Path]:
    relative = _normalize_relative_path(pattern)
    literal_parts: list[str] = []
    for part in relative.parts:
        if any(char in part for char in "*?["):
            break
        literal_parts.append(part)
    if not literal_parts:
        raise ValueError("glob must be rooted inside an allowed read root")
    _ensure_allowed_read_root(Path(*literal_parts))
    return list(vault_root.glob(str(relative).replace("\\", "/")))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slice_markdown_heading_section_bounds(text: str, predicate: Callable[[re.Match[str]], bool]) -> tuple[int, int, str]:
    matches = list(_MARKDOWN_HEADING_RE.finditer(text))
    for index, match in enumerate(matches):
        if not predicate(match):
            continue
        level = len(match.group(1))
        end = len(text)
        for next_match in matches[index + 1 :]:
            if len(next_match.group(1)) <= level:
                end = next_match.start()
                break
        return match.start(), end, text[match.start() : end]
    raise ValueError


def _slice_markdown_heading_section(text: str, predicate: Callable[[re.Match[str]], bool]) -> str:
    return _slice_markdown_heading_section_bounds(text, predicate)[2]


def _extract_heading_section(text: str, heading: str) -> str:
    try:
        return _slice_markdown_heading_section(
            text,
            lambda match: match.group(0).strip() == heading.strip(),
        )
    except ValueError as exc:
        raise ValueError(f"heading not found: {heading}") from exc


def _extract_date_section(text: str, date_filter: str) -> str:
    return _extract_date_section_with_start(text, date_filter)[1]


def _extract_date_section_with_start(text: str, date_filter: str) -> tuple[int, str]:
    return _extract_date_sections_with_starts(text, date_filter)[0]


def _extract_date_sections_with_starts(text: str, date_filter: str) -> list[tuple[int, str]]:
    normalized = date_filter.strip()
    sections: list[tuple[int, str]] = []
    heading_matches = list(_MARKDOWN_HEADING_RE.finditer(text))
    for index, match in enumerate(heading_matches):
        if not (
            match.group(2).strip() == normalized
            or match.group(2).strip().startswith(normalized)
            or match.group(0).strip() == normalized
            or match.group(0).strip().startswith(normalized)
        ):
            continue
        level = len(match.group(1))
        end = len(text)
        for next_match in heading_matches[index + 1 :]:
            if len(next_match.group(1)) <= level:
                end = next_match.start()
                break
        sections.append((match.start(), text[match.start() : end]))
    if sections:
        return sections
    try:
        raw_matches = list(re.finditer(rf"(?m)^{re.escape(normalized)}(?:\s*$|.*$)", text))
    except re.error:
        raw_matches = []
    for start_match in raw_matches:
        line_start = start_match.start()
        next_boundary = len(text)
        next_heading = _MARKDOWN_HEADING_RE.search(text, start_match.end())
        next_date = _DATE_LINE_RE.search(text, start_match.end())
        if next_heading is not None:
            next_boundary = min(next_boundary, next_heading.start())
        if next_date is not None:
            next_boundary = min(next_boundary, next_date.start())
        sections.append((line_start, text[line_start:next_boundary]))
    if not sections:
        raise ValueError(f"date section not found: {date_filter}")
    return sections


def list_paths(
    vault_root: Path,
    *,
    root: str,
    recursive: bool,
    glob: str = "*",
    include_dirs: bool = False,
    limit: int = 100,
) -> dict:
    _require_positive_int("limit", limit)
    relative_root, resolved_root = _resolve_allowed_read_path(vault_root, root)
    normalized_glob = _normalize_glob_pattern(glob)
    if not resolved_root.exists():
        raise ValueError(f"root does not exist: {root}")
    if resolved_root.is_file():
        raise ValueError(f"root must be a directory: {root}")

    iterator = resolved_root.rglob(normalized_glob) if recursive else resolved_root.glob(normalized_glob)
    items: list[str] = []
    for item in iterator:
        if item.is_symlink():
            continue
        if item.is_dir() and not include_dirs:
            continue
        resolved_item = item.resolve()
        try:
            relative_item = _resolved_relative_to_vault(vault_root, resolved_item)
            _ensure_allowed_read_root(relative_item)
        except ValueError:
            continue
        items.append(str(relative_item).replace("\\", "/"))

    items.sort()
    limited = items[:limit]
    return {
        "root": str(relative_root).replace("\\", "/"),
        "paths": limited,
        "count": len(limited),
        "truncated": len(items) > limit,
    }


def read_markdown(
    vault_root: Path,
    *,
    path: str,
    heading: str | None = None,
    date_filter: str | None = None,
    max_chars: int | None = None,
) -> dict:
    if max_chars is not None:
        _require_positive_int("max_chars", max_chars)
    relative_path, resolved_path = _resolve_allowed_read_path(vault_root, path)
    raw_path = vault_root / relative_path
    if raw_path.is_symlink() or raw_path.suffix.lower() != ".md":
        raise ValueError("path must point to a real Markdown file")
    if not resolved_path.is_file():
        raise ValueError("path must point to a real Markdown file")
    text = resolved_path.read_text(encoding="utf-8")
    section = text

    if heading:
        section = _extract_heading_section(section, heading)

    if date_filter:
        section = _extract_date_section(section, date_filter)

    truncated = False
    if max_chars is not None and len(section) > max_chars:
        section = section[:max_chars]
        truncated = True

    return {
        "path": str(relative_path).replace("\\", "/"),
        "hash": _sha256_text(text),
        "found": True,
        "content": section,
        "section": heading or date_filter,
        "truncated": truncated,
    }


def search_markdown(
    vault_root: Path,
    *,
    paths: list[str] | None = None,
    glob: str | None = None,
    query: str | None = None,
    regex: str | None = None,
    date_filter: str | None = None,
    max_results: int = 20,
    max_chars_per_hit: int = 160,
) -> dict:
    if not query and not regex:
        raise ValueError("query or regex is required")
    _require_positive_int("max_results", max_results)
    _require_positive_int("max_chars_per_hit", max_chars_per_hit)
    if regex:
        try:
            pattern = re.compile(regex)
        except re.error as exc:
            raise ValueError("invalid regex") from exc
    else:
        pattern = None
    if paths is not None:
        match_paths = paths
    elif glob is not None:
        match_paths = _resolve_allowed_glob(vault_root, glob)
    else:
        match_paths = []
        for allowed_root in ALLOWED_READ_ROOTS:
            match_paths.extend(_resolve_allowed_glob(vault_root, f"{allowed_root.as_posix()}/**/*.md"))
    matches: list[dict] = []

    for raw_path in match_paths:
        raw_candidate = Path(raw_path)
        try:
            if paths is not None:
                raw_candidate = vault_root / Path(raw_path)
                raw_is_symlink = raw_candidate.is_symlink()
                _, path = _resolve_allowed_read_path(vault_root, str(raw_path))
            else:
                raw_is_symlink = raw_candidate.is_symlink()
                path = raw_candidate.resolve()
                _ensure_allowed_read_root(_resolved_relative_to_vault(vault_root, path))
        except ValueError as exc:
            if paths is not None:
                raise
            continue
        if raw_is_symlink or not path.is_file() or path.suffix.lower() != ".md":
            continue
        original_text = path.read_text(encoding="utf-8")
        relative_path = str(_resolved_relative_to_vault(vault_root, path.resolve())).replace("\\", "/")
        sections = [(0, original_text)]
        if date_filter:
            try:
                sections = _extract_date_sections_with_starts(original_text, date_filter)
            except ValueError:
                continue
        for section_start, text in sections:
            line_offset = original_text[:section_start].count("\n")
            for idx, line in enumerate(text.splitlines(), 1):
                if query is not None and query not in line and not (pattern and pattern.search(line)):
                    continue
                if pattern is not None and not pattern.search(line) and not (query and query in line):
                    continue
                matches.append(
                    {
                        "path": relative_path,
                        "line": idx + line_offset,
                        "snippet": line[:max_chars_per_hit],
                    }
                )
                if len(matches) >= max_results:
                    return {"count": len(matches), "matches": matches}

    return {"count": len(matches), "matches": matches}


def upsert_markdown(
    vault_root: Path,
    *,
    path: str,
    content: str,
    mode: str,
    actor: str,
    expected_hash: str | None = None,
) -> dict:
    if mode not in {"create", "replace", "upsert"}:
        raise ValueError("mode must be one of: create, replace, upsert")

    relative_path, resolved_path = _resolve_allowed_write_path(vault_root, path)
    raw_path = vault_root / relative_path
    if raw_path.is_symlink():
        raise ValueError("path must not be a symlink")
    if resolved_path.exists() and not resolved_path.is_file():
        raise ValueError("path must point to a Markdown file")

    old_text = resolved_path.read_text(encoding="utf-8") if resolved_path.exists() else None
    old_hash = _sha256_text(old_text) if old_text is not None else None
    if expected_hash is not None and old_hash != expected_hash:
        raise ValueError("expected_hash does not match current content")
    if mode == "create" and resolved_path.exists():
        raise ValueError("target already exists")
    if mode == "replace" and not resolved_path.exists():
        raise ValueError("target does not exist")

    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(content, encoding="utf-8")
    relative_text_path = str(relative_path).replace("\\", "/")
    new_hash = _sha256_text(content)
    _write_operation_log(
        vault_root,
        actor=actor,
        tool="vault_upsert_markdown",
        operation=mode,
        path=relative_text_path,
        old_hash=old_hash,
        new_hash=new_hash,
    )
    return {
        "path": relative_text_path,
        "operation": mode,
        "old_hash": old_hash,
        "new_hash": new_hash,
        "actor": actor,
        "bytes_written": len(content.encode("utf-8")),
    }


def append_markdown(
    vault_root: Path,
    *,
    path: str,
    content: str,
    target: str,
    actor: str,
    heading: str | None = None,
    date: str | None = None,
    create_if_missing: bool = False,
    expected_hash: str | None = None,
) -> dict:
    if target not in {"eof", "heading", "date_section"}:
        raise ValueError("target must be one of: eof, heading, date_section")
    if target == "heading" and not heading:
        raise ValueError("heading is required when target=heading")
    if target == "date_section" and not date:
        raise ValueError("date is required when target=date_section")

    relative_path, resolved_path = _resolve_allowed_write_path(vault_root, path)
    raw_path = vault_root / relative_path
    if raw_path.is_symlink():
        raise ValueError("path must not be a symlink")
    if resolved_path.exists() and not resolved_path.is_file():
        raise ValueError("path must point to a Markdown file")

    created_file = not resolved_path.exists()
    if created_file and not create_if_missing:
        raise ValueError("target does not exist")

    old_text = resolved_path.read_text(encoding="utf-8") if resolved_path.exists() else ""
    old_hash = _sha256_text(old_text) if resolved_path.exists() else None
    if expected_hash is not None and old_hash != expected_hash:
        raise ValueError("expected_hash does not match current content")

    if target == "eof":
        new_text = _append_to_end(old_text, content)
        created_section = False
    elif target == "heading":
        new_text, created_section = _append_to_heading(old_text, heading or "", content, create_if_missing=create_if_missing)
    else:
        new_text, created_section = _append_to_date_section(old_text, date or "", content, create_if_missing=create_if_missing)

    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(new_text, encoding="utf-8")
    relative_text_path = str(relative_path).replace("\\", "/")
    new_hash = _sha256_text(new_text)
    _write_operation_log(
        vault_root,
        actor=actor,
        tool="vault_append_markdown",
        operation="append",
        path=relative_text_path,
        old_hash=old_hash,
        new_hash=new_hash,
    )
    return {
        "path": relative_text_path,
        "operation": "append",
        "old_hash": old_hash,
        "new_hash": new_hash,
        "actor": actor,
        "created_file": created_file,
        "created_section": created_section,
    }


def check_artifacts(vault_root: Path, *, artifacts: list[dict]) -> dict:
    results = []
    missing = 0
    content_failures = 0

    for spec in artifacts:
        if "path_glob" not in spec or not isinstance(spec["path_glob"], str) or not spec["path_glob"].strip():
            raise ValueError("artifact spec requires non-empty string field `path_glob`")
        matched = []
        found_any = False
        for path in _resolve_allowed_glob(vault_root, spec["path_glob"]):
            try:
                resolved_path = path.resolve()
            except (OSError, RuntimeError):
                continue
            try:
                relative_path = _resolved_relative_to_vault(vault_root, resolved_path)
                _ensure_allowed_read_root(relative_path)
            except ValueError:
                continue
            if path.is_symlink() or not resolved_path.is_file():
                continue
            text = resolved_path.read_text(encoding="utf-8")
            if spec.get("required_date") and spec["required_date"] not in text and spec["required_date"] not in path.name:
                continue
            found_any = True
            if spec.get("content_contains") and spec["content_contains"] not in text:
                content_failures += 1
                continue
            matched.append(str(relative_path).replace("\\", "/"))
        if spec.get("must_exist") and not found_any:
            missing += 1
        results.append({"spec": spec, "matched_paths": matched})

    return {"results": results, "missing": missing, "content_failures": content_failures}


def scan_curation_gaps(vault_root: Path, *, min_intake_files: int = 5) -> dict:
    _require_positive_int("min_intake_files", min_intake_files)
    _, project_raw = _resolve_allowed_read_path(vault_root, "ProjectRaw")
    if not project_raw.exists():
        return {"count": 0, "items": []}

    registry_topics: set[str] = set()
    registry_path = vault_root / ".knowledge-registry" / "vault-registry.json"
    if registry_path.exists() and registry_path.is_file() and not registry_path.is_symlink():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        for topic in registry.get("topics", []):
            for intake_path in topic.get("intake_paths", []):
                try:
                    intake_relative = _normalize_relative_path(intake_path)
                except ValueError:
                    continue
                if intake_relative.parts and intake_relative.parts[0] == "ProjectRaw" and len(intake_relative.parts) > 1:
                    registry_topics.add(intake_relative.parts[1])

    candidates = []
    for topic_dir in sorted(path for path in project_raw.iterdir() if path.is_dir()):
        try:
            resolved_topic_dir = topic_dir.resolve()
            topic_relative = _resolved_relative_to_vault(vault_root, resolved_topic_dir)
            _ensure_allowed_read_root(topic_relative)
        except (OSError, RuntimeError, ValueError):
            continue
        if registry_topics and topic_dir.name not in registry_topics:
            continue

        md_files = []
        for path in topic_dir.rglob("*.md"):
            try:
                resolved_path = path.resolve()
                relative_path = _resolved_relative_to_vault(vault_root, resolved_path)
                _ensure_allowed_read_root(relative_path)
            except (OSError, RuntimeError, ValueError):
                continue
            if path.is_symlink() or not resolved_path.is_file():
                continue
            if resolved_path.name == "00-专题索引.md":
                continue
            md_files.append(resolved_path)

        if not registry_topics and md_files and all(_DATE_STEM_RE.fullmatch(path.stem) for path in md_files):
            continue

        index_path = topic_dir / "00-专题索引.md"
        has_index = False
        try:
            index_resolved = index_path.resolve()
            index_relative = _resolved_relative_to_vault(vault_root, index_resolved)
            _ensure_allowed_read_root(index_relative)
            has_index = not index_path.is_symlink() and index_resolved.is_file()
        except (OSError, RuntimeError, ValueError):
            has_index = False
        if len(md_files) >= min_intake_files and not has_index:
            candidates.append(
                {
                    "topic_path": str(topic_relative).replace("\\", "/"),
                    "intake_count": len(md_files),
                    "has_index": has_index,
                }
            )
    return {"count": len(candidates), "items": candidates}
