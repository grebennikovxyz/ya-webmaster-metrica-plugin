"""Build one portable plugin from the versioned wheel and reviewed plugin components."""

import hashlib
import io
import json
import tarfile
import tomllib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/ya-webmaster"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"][
    "version"
]
DIST = ROOT / "dist"
WHEEL = f"grebennikov_ya_webmaster-{VERSION}-py3-none-any.whl"


def package():
    dist_wheel = DIST / WHEEL
    if not dist_wheel.is_file():
        raise SystemExit("Build the wheel first: uv build --wheel")
    manifests = [
        "plugin.json",
        ".codex-plugin/plugin.json",
        ".claude-plugin/plugin.json",
    ]
    for name in manifests:
        if json.loads((PLUGIN / name).read_text("utf-8"))["version"] != VERSION:
            raise ValueError(f"Version mismatch in {name}")
    config = json.loads((PLUGIN / "mcp.json").read_text("utf-8"))
    args = config["mcpServers"]["ya-webmaster"]["args"]
    if not args[3].endswith(f"/v{VERSION}/{WHEEL}"):
        raise ValueError("Marketplace wheel URL and version disagree")
    archive = DIST / f"ya-webmaster-{VERSION}.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as out:
        for name in [*manifests, "skills/ya-webmaster/SKILL.md", "assets/ya-webmaster.png"]:
            out.write(PLUGIN / name, name)
        args[3] = "./wheels/" + WHEEL
        args[0:0] = ["--directory", "${PLUGIN_ROOT}"]
        out.writestr("mcp.json", json.dumps(config, indent=2))
        out.write(dist_wheel, "wheels/" + WHEEL)
        out.write(ROOT / "LICENSE", "LICENSE")
    with ZipFile(archive) as check:
        assert check.testzip() is None and len(check.namelist()) == 8
    bundle = DIST / f"ya-webmaster-{VERSION}-clawhub.tgz"
    with tarfile.open(bundle, "w:gz", format=tarfile.USTAR_FORMAT) as tar:
        metadata = json.dumps(
            {
                "name": "@grebennikovxyz/ya-webmaster",
                "version": VERSION,
                "license": "Apache-2.0",
            }
        ).encode()
        entry = tarfile.TarInfo("package/package.json")
        entry.size = len(metadata)
        tar.addfile(entry, io.BytesIO(metadata))
        for name in [
            ".claude-plugin/plugin.json",
            "mcp.json",
            "skills/ya-webmaster/SKILL.md",
            "assets/ya-webmaster.png",
        ]:
            tar.add(PLUGIN / name, arcname="package/" + name, recursive=False)
        for name in ["LICENSE", "README.md"]:
            tar.add(ROOT / name, arcname="package/" + name, recursive=False)
    (DIST / "SHA256SUMS.txt").write_text(
        "".join(
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
            for p in [archive, dist_wheel, bundle]
        ),
        encoding="ascii",
    )
    return archive


if __name__ == "__main__":
    print(package())
