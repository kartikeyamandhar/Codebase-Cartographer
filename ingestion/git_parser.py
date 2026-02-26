"""
Phase 2 - Task 2.2
Git log parsing: Author, Commit nodes + MODIFIED_BY, AUTHORED_BY, OWNS edges.

Uses gitpython to walk commit history.
Caps at MAX_COMMITS (default 500) — configurable via env var.
Logs a warning if history is truncated.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import git


MAX_COMMITS = int(os.getenv("MAX_COMMITS", "500"))


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ParsedAuthor:
    email: str
    name: str
    workspace_id: str


@dataclass
class ParsedCommit:
    hash: str
    message: str
    timestamp: str          # ISO format string
    branch: str
    author_email: str
    workspace_id: str
    files_changed: list[dict] = field(default_factory=list)
    # each entry: {path, lines_added, lines_removed}


@dataclass
class GitGraph:
    authors: list[ParsedAuthor]
    commits: list[ParsedCommit]


# ── Git log parser ────────────────────────────────────────────────────────────

def parse_git_history(repo_path: str, workspace_id: str) -> GitGraph:
    """
    Parse git commit history for a repo.
    Returns authors and commits with file-level change info.
    """
    try:
        repo = git.Repo(repo_path)
    except git.InvalidGitRepositoryError:
        print(f"[GIT] No git repository found at {repo_path} — skipping git graph")
        return GitGraph(authors=[], commits=[])

    # Get active branch name safely
    try:
        branch_name = repo.active_branch.name
    except TypeError:
        branch_name = "detached"

    # Get commit list — cap at MAX_COMMITS
    all_commits = list(repo.iter_commits(max_count=MAX_COMMITS + 1))
    truncated = len(all_commits) > MAX_COMMITS

    if truncated:
        all_commits = all_commits[:MAX_COMMITS]
        print(f"[GIT] WARNING: History truncated at {MAX_COMMITS} commits. "
              f"Set MAX_COMMITS env var to increase. Full history not ingested.")
    else:
        print(f"[GIT] Found {len(all_commits)} commits")

    authors_map: dict[str, ParsedAuthor] = {}
    commits: list[ParsedCommit] = []

    for commit in all_commits:
        email = commit.author.email or "unknown@unknown"
        name = commit.author.name or "Unknown"

        # Register author
        if email not in authors_map:
            authors_map[email] = ParsedAuthor(
                email=email,
                name=name,
                workspace_id=workspace_id,
            )

        # Parse file-level changes
        files_changed = _parse_commit_files(commit, repo_path)

        ts = datetime.fromtimestamp(
            commit.committed_date, tz=timezone.utc
        ).isoformat()

        commits.append(ParsedCommit(
            hash=commit.hexsha,
            message=commit.message.strip()[:500],   # cap message length
            timestamp=ts,
            branch=branch_name,
            author_email=email,
            workspace_id=workspace_id,
            files_changed=files_changed,
        ))

    print(f"[GIT] Parsed {len(commits)} commits, {len(authors_map)} authors")
    return GitGraph(authors=list(authors_map.values()), commits=commits)


def _parse_commit_files(commit, repo_path: str) -> list[dict]:
    """
    Get file-level stats for a commit.
    Returns list of {path, lines_added, lines_removed}.
    Only includes .py, .ts, .js, .tsx, .jsx files.
    Uses commit.stats directly — works on full clones.
    """
    SUPPORTED_EXTENSIONS = {".py", ".ts", ".js", ".tsx", ".jsx"}
    files = []

    try:
        for path, stats in commit.stats.files.items():
            ext = Path(path).suffix
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            full_path = str(Path(repo_path) / path)

            files.append({
                "path": full_path,
                "relative_path": path,
                "lines_added": stats.get("insertions", 0),
                "lines_removed": stats.get("deletions", 0),
            })

    except Exception as e:
        # Don't crash on malformed commits
        pass

    return files


def build_ownership_map(git_graph: GitGraph) -> dict[str, dict]:
    """
    Derive file ownership from commit history.
    Returns: {file_path -> {author_email -> {commit_count, last_touch}}}
    """
    ownership: dict[str, dict] = {}

    for commit in git_graph.commits:
        for file_change in commit.files_changed:
            path = file_change["path"]
            email = commit.author_email
            ts = commit.timestamp

            if path not in ownership:
                ownership[path] = {}

            if email not in ownership[path]:
                ownership[path][email] = {
                    "commit_count": 0,
                    "last_touch": ts,
                }

            ownership[path][email]["commit_count"] += 1
            # Keep most recent timestamp
            if ts > ownership[path][email]["last_touch"]:
                ownership[path][email]["last_touch"] = ts

    return ownership