#!/usr/bin/env python3
"""
Generate version.json with git hash and timestamp.

This file is used by the frontend to detect when a new version is deployed.
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def get_git_hash() -> str:
    """Get the current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


def get_git_branch() -> str:
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


def generate_version_file() -> None:
    """Generate static/version.json with current git info."""
    version_data = {
        "hash": get_git_hash(),
        "branch": get_git_branch(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Write to static directory
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)

    version_file = static_dir / "version.json"
    with open(version_file, "w") as f:
        json.dump(version_data, f, indent=2)

    print(f"✅ Generated {version_file}")
    print(f"   Hash: {version_data['hash'][:8]}")
    print(f"   Branch: {version_data['branch']}")
    print(f"   Timestamp: {version_data['timestamp']}")


if __name__ == "__main__":
    generate_version_file()
