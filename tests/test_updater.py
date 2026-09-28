import zipfile

import pytest

from wireless_limitless import updater
from wireless_limitless.updater import UpdateError


@pytest.mark.parametrize(
    "remote,local,newer",
    [("1.0.1", "1.0.0", True), ("v1.1.0", "1.0.9", True), ("2.0.0", "1.9.9", True),
     ("1.0.0", "1.0.0", False), ("0.9.9", "1.0.0", False), ("garbage", "1.0.0", False),
     ("1.0.0-beta", "0.9.0", True)],
)
def test_is_newer(remote, local, newer):
    assert updater.is_newer(remote, local) is newer


def test_parse_version_rejects_partial():
    with pytest.raises(ValueError):
        updater.parse_version("1.0")


@pytest.mark.parametrize(
    "url",
    ["http://api.github.com/x", "https://evil.example.com/x", "https://github.com.evil.io/x", "file:///C:/x"],
)
def test_url_allowlist(url):
    with pytest.raises(UpdateError):
        updater._check_url(url)


def test_url_allowlist_accepts_github():
    updater._check_url("https://api.github.com/repos/o/r/releases/latest")
    updater._check_url("https://objects.githubusercontent.com/some/asset")


def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def test_safe_extract_ok(tmp_path):
    archive = tmp_path / "ok.zip"
    _zip(archive, {"WirelessLimitless/WirelessLimitless.exe": b"MZ", "WirelessLimitless/_internal/a.dll": b"x"})
    updater.safe_extract(archive, tmp_path / "out")
    root = updater._find_app_root(tmp_path / "out")
    assert root.name == "WirelessLimitless"


@pytest.mark.parametrize("bad", ["../evil.txt", "a/../../evil.txt", "/abs.txt", "C:/win.txt"])
def test_safe_extract_blocks_traversal(tmp_path, bad):
    archive = tmp_path / "bad.zip"
    _zip(archive, {bad: b"x"})
    with pytest.raises(UpdateError):
        updater.safe_extract(archive, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


def test_can_self_update_false_from_source():
    assert updater.can_self_update() is False
