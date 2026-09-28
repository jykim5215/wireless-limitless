"""Assemble the distributable package from the PyInstaller output.

1. release/WirelessLimitless-<ver>-win64/WirelessLimitless/  <- app + docs + installer
2. privacy scan (no user profile paths, no Bluetooth addresses, no logs/settings)
3. release/WirelessLimitless-<ver>-win64.zip (+ .sha256) and release/version.json

    python tools/package.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = "WirelessLimitless"
DOCS = ["HANDOFF.md", "README.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md", "version.json"]
PACKAGING = ["install.cmd", "install.ps1", "uninstall.cmd", "uninstall.ps1"]
TEXT_SUFFIXES = {".md", ".txt", ".json", ".html", ".js", ".css", ".ps1", ".cmd", ".toml", ".cfg"}
MAC_RE = re.compile(rb"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
FORBIDDEN_NAMES = {"settings.json", "app.log", ".env"}


def sensitive_needles() -> list[bytes]:
    needles: list[bytes] = []
    profile = os.environ.get("USERPROFILE")
    if profile:
        for variant in {profile, profile.replace("\\", "/"), profile.replace("\\", "\\\\")}:
            needles += [variant.encode("utf-8"), variant.encode("utf-16-le")]
    settings = Path(os.environ.get("APPDATA", "")) / APP / "settings.json"
    try:
        last = json.loads(settings.read_text(encoding="utf-8")).get("lastDevice") or {}
        if last.get("address"):
            addr = last["address"]
            needles += [addr.encode(), addr.lower().encode(), addr.encode("utf-16-le")]
    except (OSError, ValueError, AttributeError):
        pass
    return [n for n in needles if n]


def privacy_scan(folder: Path) -> list[str]:
    problems = []
    needles = sensitive_needles()
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(folder)
        if path.name.lower() in FORBIDDEN_NAMES or path.suffix.lower() == ".log":
            problems.append(f"{rel}: private file must not ship")
            continue
        data = path.read_bytes()
        for needle in needles:
            if needle in data:
                problems.append(f"{rel}: contains a local profile path or device address")
                break
        if path.suffix.lower() in TEXT_SUFFIXES and MAC_RE.search(data):
            problems.append(f"{rel}: contains a Bluetooth/MAC address")
    return problems


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"]
    built = ROOT / "build" / "dist" / APP
    if not (built / f"{APP}.exe").is_file():
        print("PyInstaller output missing; run tools/build.ps1", file=sys.stderr)
        return 1

    release = ROOT / "release"
    stage_root = release / f"{APP}-{version}-win64"
    pkg = stage_root / APP
    shutil.rmtree(stage_root, ignore_errors=True)
    shutil.copytree(built, pkg)
    for name in DOCS:
        shutil.copy2(ROOT / name, pkg / name)
    for name in PACKAGING:
        shutil.copy2(ROOT / "packaging" / name, pkg / name)
    shutil.copytree(ROOT / "licenses", pkg / "licenses")

    problems = privacy_scan(pkg)
    if problems:
        print("PRIVACY SCAN FAILED:", *problems, sep="\n  ", file=sys.stderr)
        return 2
    print("privacy scan: clean")

    archive = release / f"{APP}-{version}-win64.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(pkg.rglob("*")):
            if path.is_file():
                zf.write(path, Path(APP) / path.relative_to(pkg))
    digest = sha256(archive)
    (release / f"{archive.name}.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    shutil.copy2(ROOT / "version.json", release / "version.json")
    size_mb = archive.stat().st_size / (1 << 20)
    print(f"{archive.relative_to(ROOT)}  {size_mb:.1f} MB  sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
