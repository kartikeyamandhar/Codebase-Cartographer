"""
Phase 1 - Clone a GitHub repo to a local temp directory.
"""

import os
import tempfile
from pathlib import Path

import git


def clone_repo(github_url: str, target_dir: str = None) -> str:
    """
    Clone a GitHub repo. Returns the local path.
    If target_dir is None, clones into a temp directory.
    """
    if target_dir is None:
        target_dir = tempfile.mkdtemp(prefix="cartographer_")

    target = Path(target_dir)

    if target.exists() and any(target.iterdir()):
        print(f"[CLONE] Directory already exists and is non-empty: {target_dir}")
        print(f"[CLONE] Using existing directory — delete it to re-clone")
        return target_dir

    print(f"[CLONE] Cloning {github_url} → {target_dir}")
    git.Repo.clone_from(github_url, target_dir, depth=1)
    print(f"[CLONE] Done")
    return target_dir