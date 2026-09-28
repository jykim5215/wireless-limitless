"""Self-update from GitHub Releases (public REST API, no credentials).

Flow: latest release -> its `version.json` asset -> compare with the bundled
version -> (user approves) download the win64 zip + `.sha256` -> verify ->
extract into a staging folder (zip-slip safe) -> hand off to a small cmd
script that waits for this process to exit, mirrors the staged build over the
install folder (with a backup for rollback) and restarts the app.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import config, paths

log = logging.getLogger(__name__)

API_LATEST = f"https://api.github.com/repos/{config.GITHUB_OWNER}/{config.GITHUB_REPO}/releases/latest"
ALLOWED_HOSTS = frozenset({
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
})
TIMEOUT_S = 12
MAX_JSON_BYTES = 1 << 20
MAX_ZIP_BYTES = 400 << 20
MAX_UNPACKED_BYTES = 1 << 30
MAX_ZIP_ENTRIES = 20000


class UpdateError(Exception):
    """Carries a short Korean message that is safe to show in the UI."""


@dataclass
class UpdateInfo:
    version: str
    changelog: str
    zip_url: str | None
    zip_name: str | None
    sha_url: str | None


def current_version() -> str:
    try:
        return str(json.loads(paths.version_file().read_text(encoding="utf-8"))["version"])
    except (OSError, ValueError, KeyError):
        return "0.0.0"


def parse_version(text: str) -> tuple[int, int, int]:
    core = text.strip().lstrip("vV").split("-", 1)[0].split("+", 1)[0]
    parts = core.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"not a semantic version: {text!r}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def is_newer(remote: str, local: str) -> bool:
    try:
        return parse_version(remote) > parse_version(local)
    except ValueError:
        return False


# ----------------------------------------------------------------- network


def _check_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        raise UpdateError("허용되지 않은 업데이트 주소예요.")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirect())


def _open(url: str, accept: str):
    _check_url(url)
    request = urllib.request.Request(url, headers={
        "User-Agent": f"{config.APP_ID}-updater/{current_version()}",
        "Accept": accept,
    })
    try:
        return _opener.open(request, timeout=TIMEOUT_S)
    except UpdateError:
        raise
    except OSError as exc:  # URLError, HTTPError, timeouts, TLS errors
        log.info("update request failed: %s", exc)
        raise UpdateError("GitHub에 연결하지 못했어요.") from exc


def _get_json(url: str, accept: str = "application/vnd.github+json") -> dict:
    with _open(url, accept) as resp:
        body = resp.read(MAX_JSON_BYTES + 1)
    if len(body) > MAX_JSON_BYTES:
        raise UpdateError("업데이트 정보가 너무 커요.")
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise UpdateError("업데이트 정보를 읽지 못했어요.") from exc
    if not isinstance(data, dict):
        raise UpdateError("업데이트 정보를 읽지 못했어요.")
    return data


def _download(url: str, dest: Path, progress: Callable[[float], None] | None = None) -> None:
    with _open(url, "application/octet-stream") as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        if total > MAX_ZIP_BYTES:
            raise UpdateError("업데이트 파일이 너무 커요.")
        done = 0
        while chunk := resp.read(256 * 1024):
            done += len(chunk)
            if done > MAX_ZIP_BYTES:
                raise UpdateError("업데이트 파일이 너무 커요.")
            out.write(chunk)
            if progress and total:
                progress(done / total)


# ------------------------------------------------------------------- check


def check() -> tuple[UpdateInfo, bool]:
    """Returns (latest release info, is_newer_than_running_app)."""
    release = _get_json(API_LATEST)
    assets = {a.get("name"): a for a in release.get("assets", []) if isinstance(a, dict)}

    version = str(release.get("tag_name", "")).lstrip("vV")
    changelog = str(release.get("body") or "")
    manifest = assets.get("version.json")
    if manifest and manifest.get("browser_download_url"):
        data = _get_json(manifest["browser_download_url"], "application/octet-stream")
        version = str(data.get("version", version))
        changelog = str(data.get("changelog", changelog))
    try:
        parse_version(version)
    except ValueError as exc:
        raise UpdateError("릴리즈 버전 형식이 올바르지 않아요.") from exc

    zip_name = f"{config.APP_ID}-{version}-win64.zip"
    zip_asset, sha_asset = assets.get(zip_name), assets.get(zip_name + ".sha256")
    info = UpdateInfo(
        version=version,
        changelog=changelog.strip()[:4000],
        zip_url=zip_asset.get("browser_download_url") if zip_asset else None,
        zip_name=zip_name if zip_asset else None,
        sha_url=sha_asset.get("browser_download_url") if sha_asset else None,
    )
    return info, is_newer(version, current_version())


def can_self_update() -> bool:
    """Only replace files inside a folder that is unmistakably ours."""
    folder = paths.install_dir()
    if folder is None:
        return False
    if folder.name.lower() != config.APP_ID.lower():
        return False
    if not (folder / "_internal").is_dir() or not (folder / config.EXE_NAME).is_file():
        return False
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".wl-write-test-", delete=True):
            pass
    except OSError:
        return False
    return True


# ------------------------------------------------------------------- apply


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_extract(archive: Path, target: Path) -> None:
    target = target.resolve()
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        if len(members) > MAX_ZIP_ENTRIES:
            raise UpdateError("업데이트 파일 구성이 올바르지 않아요.")
        if sum(m.file_size for m in members) > MAX_UNPACKED_BYTES:
            raise UpdateError("업데이트 파일이 너무 커요.")
        for member in members:
            name = member.filename.replace("\\", "/")
            if name.startswith("/") or ":" in name or any(part == ".." for part in name.split("/")):
                raise UpdateError("업데이트 파일에 잘못된 경로가 있어요.")
            dest = (target / name).resolve()
            if dest != target and target not in dest.parents:
                raise UpdateError("업데이트 파일에 잘못된 경로가 있어요.")
        zf.extractall(target)


def _find_app_root(stage: Path) -> Path:
    for candidate in [stage, *[p for p in stage.iterdir() if p.is_dir()]]:
        if (candidate / config.EXE_NAME).is_file() and (candidate / "_internal").is_dir():
            return candidate
    raise UpdateError("업데이트 파일에 실행 파일이 없어요.")


_APPLY_SCRIPT = r"""@echo off
setlocal EnableExtensions
rem Wireless Limitless self-update helper. All paths come from WL_* variables.
set /a WAITED=0
:wait
tasklist /FI "PID eq %WL_PID%" /NH 2>nul | find "%WL_PID%" >nul
if not errorlevel 1 (
  if %WAITED% GEQ 90 goto done
  ping -n 2 127.0.0.1 >nul
  set /a WAITED+=1
  goto wait
)
robocopy "%WL_DST%" "%WL_BAK%" /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if %ERRORLEVEL% GEQ 8 goto relaunch
robocopy "%WL_SRC%" "%WL_DST%" /MIR /R:5 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if %ERRORLEVEL% GEQ 8 robocopy "%WL_BAK%" "%WL_DST%" /MIR /R:5 /W:1 /NFL /NDL /NJH /NJS /NP >nul
:relaunch
start "" "%WL_DST%\%WL_EXE%"
rmdir /s /q "%WL_WORK%" 2>nul
:done
(goto) 2>nul & del "%~f0"
"""


def apply(info: UpdateInfo, progress: Callable[[float], None] | None = None) -> None:
    """Download, verify and stage the release, then start the swap helper.

    The caller must exit the app right after this returns.
    """
    if not can_self_update():
        raise UpdateError("이 위치에서는 자동 업데이트를 할 수 없어요. 릴리즈에서 직접 내려받아 주세요.")
    if not (info.zip_url and info.sha_url and info.zip_name):
        raise UpdateError("릴리즈에 설치 파일이 없어요.")

    work = Path(tempfile.gettempdir()) / f"{config.APP_ID}-update"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    archive = work / info.zip_name
    _download(info.zip_url, archive, progress)

    sha_file = work / "sha256.txt"
    _download(info.sha_url, sha_file)
    expected = sha_file.read_text(encoding="ascii", errors="ignore").strip().split()
    if not expected or expected[0].lower() != _sha256(archive):
        raise UpdateError("내려받은 파일 검증에 실패했어요. (SHA-256 불일치)")

    stage = work / "stage"
    safe_extract(archive, stage)
    app_root = _find_app_root(stage)

    install = paths.install_dir()
    assert install is not None
    script = Path(tempfile.gettempdir()) / f"{config.APP_ID}-apply-update.cmd"
    script.write_text(_APPLY_SCRIPT, encoding="ascii")
    env = dict(os.environ)
    env.update({
        "WL_PID": str(os.getpid()),
        "WL_SRC": str(app_root),
        "WL_DST": str(install),
        "WL_BAK": str(work / "backup"),
        "WL_WORK": str(work),
        "WL_EXE": config.EXE_NAME,
    })
    # Hidden console (not DETACHED_PROCESS) so robocopy/tasklist don't pop up windows.
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    system_cmd = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
    subprocess.Popen([str(system_cmd), "/d", "/c", str(script)], env=env, creationflags=flags,
                     close_fds=True, cwd=str(work))
    log.info("update to %s staged; handing over to helper", info.version)
