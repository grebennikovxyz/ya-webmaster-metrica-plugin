"""Publish or verify one immutable GitHub release artifact on ClawHub."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from package import PLUGIN, ROOT, VERSION

OWNER = "grebennikovxyz"
REPO = f"{OWNER}/ya-webmaster-metrica-plugin"
PACKAGE = f"@{OWNER}/ya-webmaster"
SKILL = PLUGIN / "skills/ya-webmaster"
REGISTRY = "https://clawhub.ai"


def read_json(url):
    request = Request(
        url,
        headers={
            "User-Agent": f"Ya-Webmaster/{VERSION} (+https://github.com/{REPO})",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=25) as reply:
        return json.load(reply)


def published(channel, archive):
    if channel == "skill":
        path = f"/skills/ya-webmaster/versions/{VERSION}?ownerHandle={OWNER}"
    else:
        path = f"/packages/{quote(PACKAGE, safe='')}/versions/{VERSION}/artifact"
    try:
        data = read_json(f"{REGISTRY}/api/v1{path}")
    except HTTPError as error:
        if error.code == 404:
            return False
        raise
    if channel == "skill":
        expected = {
            item.relative_to(SKILL).as_posix(): hashlib.sha256(
                item.read_bytes()
            ).hexdigest()
            for item in SKILL.rglob("*")
            if item.is_file()
        }
        files = data["version"]["files"]
        match = data["version"]["version"] == VERSION and expected == {
            f["path"]: f["sha256"] for f in files
        }
    else:
        with archive.open("rb") as file:
            digest = hashlib.file_digest(file, "sha256").hexdigest()
        match = (
            data["package"]["name"] == PACKAGE
            and data["version"] == VERSION
            and data["artifact"]["sha256"] == digest
        )
    if not match:
        raise SystemExit(f"ClawHub {channel} {VERSION} exists with different content.")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", choices=("skill", "package"))
    parser.add_argument(
        "--archive", type=Path, default=ROOT / "dist" / f"ya-webmaster-{VERSION}-clawhub.tgz"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    tag = f"v{VERSION}"
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if not args.dry_run:
        if os.environ.get("GITHUB_REF") != f"refs/tags/{tag}":
            raise SystemExit("Publish from the matching release tag.")
        if (
            read_json(f"https://api.github.com/repos/{REPO}/releases/latest")[
                "tag_name"
            ]
            != tag
        ):
            raise SystemExit(
                "Only the latest stable GitHub release can update the latest registry tag."
            )
        if published(args.channel, args.archive):
            print(f"Verified public {args.channel} {VERSION}")
            return

    if args.channel == "skill":
        cmd = [
            "skill",
            "publish",
            str(SKILL),
            "--slug",
            "ya-webmaster",
            "--name",
            "Ya-Webmaster",
            "--categories",
            "productivity",
            "--topics",
            "yandex,webmaster,metrica,maps",
            "--source-path",
            SKILL.relative_to(ROOT).as_posix(),
        ]
    else:
        cmd = [
            "package",
            "publish",
            str(args.archive),
            "--family",
            "bundle-plugin",
            "--name",
            PACKAGE,
            "--display-name",
            "Ya-Webmaster",
            "--source-path",
            PLUGIN.relative_to(ROOT).as_posix(),
        ]
        if not args.dry_run:
            cmd.extend(["--wait", "--wait-timeout", "600"])
    cmd.extend(
        [
            "--version",
            VERSION,
            "--owner",
            OWNER,
            "--changelog",
            f"https://github.com/{REPO}/releases/tag/{tag}",
            "--source-repo",
            REPO,
            "--source-commit",
            commit,
            "--source-ref",
            f"refs/tags/{tag}",
        ]
    )
    if args.dry_run:
        cmd.append("--dry-run")
    executable = shutil.which("clawhub")
    if not executable:
        raise SystemExit("Install clawhub@0.27.0 to run the publisher.")
    subprocess.run([executable, *cmd], check=True, cwd=ROOT)
    if not args.dry_run:
        for attempt in range(21):
            if published(args.channel, args.archive):
                print(f"Verified public {args.channel} {VERSION}")
                return
            if attempt < 20:
                time.sleep(15)
        raise SystemExit(
            "Registry has not made this version public. Check moderation, then rerun the job."
        )


if __name__ == "__main__":
    main()
