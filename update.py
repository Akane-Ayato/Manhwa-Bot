"""Optional self-update: pull the latest code from UPSTREAM_REPO on every start.

Does nothing unless UPSTREAM_REPO is set.  WARNING: when it *is* set, local
files are replaced by the upstream branch (git reset --hard), so point it at
YOUR repository/fork - not at the original author's, or your own changes get
overwritten on every restart.
"""
import re
import subprocess
from os import environ, path as ospath
from shutil import rmtree

UPSTREAM_REPO = environ.get("UPSTREAM_REPO", "").strip()  # SSH/HTTPS URL (may embed a token)
UPSTREAM_BRANCH = environ.get("UPSTREAM_BRANCH", "master").strip() or "master"
GITHUB_EMAIL = environ.get("GITHUB_EMAIL", "random@gmail.com")
GITHUB_USERNAME = environ.get("GITHUB_USERNAME", "random")


def _mask(text: str) -> str:
    """Hide credentials embedded in a URL (https://user:token@host/...)."""
    text = text or ""
    if UPSTREAM_REPO:
        text = text.replace(UPSTREAM_REPO, "<UPSTREAM_REPO>")
    return re.sub(r"(https?://)[^/@\s]+@", r"\1***@", text)


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def main() -> int:
    if not UPSTREAM_REPO:
        print("UPSTREAM_REPO not set - skipping self-update.")
        return 0

    if ospath.exists(".git"):
        rmtree(".git", ignore_errors=True)

    steps = [
        ("init", "-q"),
        ("config", "--global", "user.email", GITHUB_EMAIL),
        ("config", "--global", "user.name", GITHUB_USERNAME),
        ("add", "."),
        ("commit", "-sm", "update", "-q"),
        ("remote", "add", "origin", UPSTREAM_REPO),
        ("fetch", "origin", "-q"),
        ("reset", "--hard", f"origin/{UPSTREAM_BRANCH}", "-q"),
    ]
    for step in steps:
        result = _git(*step)
        if result.returncode != 0:
            # "commit" fails harmlessly when there is nothing to commit
            if step[0] == "commit":
                continue
            print(f"Self-update failed at 'git {step[0]}': {_mask(result.stderr).strip()}")
            print("Check UPSTREAM_REPO / UPSTREAM_BRANCH.")
            return 1

    print("Successfully updated with latest commit from UPSTREAM_REPO")
    return 0


if __name__ == "__main__":
    # Never block the bot from starting just because the update failed.
    main()
