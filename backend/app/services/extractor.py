"""
Extractor service module.

Parses Git history using high-performance bulk log streaming (`git log --numstat -M`).
Handles commit metadata, per-file diff stats, and file renames.
"""

from datetime import datetime, timezone
import logging
import re
import subprocess
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("gitcompass.extractor")

RENAME_PATTERN_BRACES = re.compile(r"^(.*?)\{(.*?) => (.*?)\}(.*)$")
RENAME_PATTERN_SIMPLE = re.compile(r"^(.*?) => (.*)$")


def parse_git_path(path_str: str) -> Tuple[str, Optional[str], bool]:
    """Parses Git numstat file path into (current_path, old_path, is_rename).

    Examples:
        "src/app.py" -> ("src/app.py", None, False)
        "old.py => new.py" -> ("new.py", "old.py", True)
        "src/{old => new}/utils.py" -> ("src/new/utils.py", "src/old/utils.py", True)
    """
    path_str = path_str.strip()

    # Case 1: Braced rename `prefix/{old => new}/suffix`
    m_brace = RENAME_PATTERN_BRACES.match(path_str)
    if m_brace:
        prefix, old_mid, new_mid, suffix = m_brace.groups()
        old_path = (prefix + old_mid + suffix).replace("//", "/")
        new_path = (prefix + new_mid + suffix).replace("//", "/")
        return new_path, old_path, True

    # Case 2: Simple rename `old => new`
    m_simple = RENAME_PATTERN_SIMPLE.match(path_str)
    if m_simple:
        old_path = m_simple.group(1).strip()
        new_path = m_simple.group(2).strip()
        return new_path, old_path, True

    # Case 3: Regular file path
    return path_str, None, False


def extract_git_history(
    repo_dir: str, repo_id: str, user_id: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int, int]:
    """Bulk parses Git history for a repository.

    Returns:
        (commits_list, file_diffs_list, total_commits, total_files)
    """
    logger.info("Extracting Git history for repo %s from %s", repo_id, repo_dir)

    # Bulk git log command with --numstat and rename detection (-M)
    cmd = [
        "git",
        "log",
        "--numstat",
        "--format=COMMIT:%H|%an|%ae|%at|%s",
        "-M",
    ]

    res = subprocess.run(
        cmd,
        cwd=repo_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=300,
    )

    if res.returncode != 0:
        raise RuntimeError(f"Git log failed: {res.stderr.strip()}")

    lines = res.stdout.splitlines()

    commits: List[Dict[str, Any]] = []
    file_diffs: List[Dict[str, Any]] = []
    unique_files: set[str] = set()

    current_commit: Optional[Dict[str, Any]] = None
    commit_insertions = 0
    commit_deletions = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("COMMIT:"):
            # Finalize previous commit stats before starting new one
            if current_commit:
                current_commit["insertions"] = commit_insertions
                current_commit["deletions"] = commit_deletions
                commits.append(current_commit)

            # Reset per-commit trackers
            commit_insertions = 0
            commit_deletions = 0

            # Parse line format: COMMIT:sha|author_name|author_email|timestamp|message
            raw_data = line[7:]
            parts = raw_data.split("|", 4)

            sha = parts[0] if len(parts) > 0 else ""
            author_name = parts[1] if len(parts) > 1 else ""
            author_email = parts[2] if len(parts) > 2 else ""
            raw_ts = parts[3] if len(parts) > 3 else "0"
            message = parts[4] if len(parts) > 4 else ""

            try:
                ts_int = int(raw_ts)
                committed_at = datetime.fromtimestamp(ts_int, tz=timezone.utc).isoformat()
            except ValueError:
                committed_at = datetime.now(timezone.utc).isoformat()

            commit_id = str(uuid.uuid4())
            current_commit = {
                "id": commit_id,
                "repo_id": repo_id,
                "user_id": user_id,
                "sha": sha,
                "author_name": author_name,
                "author_email": author_email,
                "committed_at": committed_at,
                "message": message,
                "insertions": 0,
                "deletions": 0,
            }
        elif current_commit:
            # Numstat line: <insertions>\t<deletions>\t<path>
            parts = line.split("\t", 2)
            if len(parts) == 3:
                raw_ins, raw_del, raw_path = parts[0], parts[1], parts[2]

                # Handle binary files ("-  -   file.png")
                ins = int(raw_ins) if raw_ins.isdigit() else 0
                dels = int(raw_del) if raw_del.isdigit() else 0

                current_path, old_path, is_rename = parse_git_path(raw_path)
                unique_files.add(current_path)

                commit_insertions += ins
                commit_deletions += dels

                file_diffs.append(
                    {
                        "id": str(uuid.uuid4()),
                        "commit_id": current_commit["id"],
                        "repo_id": repo_id,
                        "user_id": user_id,
                        "file_path": current_path,
                        "old_path": old_path,
                        "is_rename": is_rename,
                        "insertions": ins,
                        "deletions": dels,
                    }
                )

    # Don't forget the last commit
    if current_commit:
        current_commit["insertions"] = commit_insertions
        current_commit["deletions"] = commit_deletions
        commits.append(current_commit)

    logger.info(
        "Extracted %d commits and %d file diffs across %d unique files for repo %s",
        len(commits),
        len(file_diffs),
        len(unique_files),
        repo_id,
    )

    return commits, file_diffs, len(commits), len(unique_files)
