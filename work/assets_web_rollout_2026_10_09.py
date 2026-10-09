"""Publish only the verified Assets web bundle, preserving public SEO pages."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("phase", choices=["prepare", "promote", "verify"])
args = parser.parse_args()
commit = "e05f9605eeaac6553968101cd8985e5291cc1c29"
package = Path("/opt/svaultai/assets-web-e05f9605eeaa.tar")
expected_sha = "1f5c739fc334d38344fa2ea4423e7e203e0c7cb9348bcee3983ff2264aecdcc1"
root = Path("/opt/svaultai/frontend")
current = root / "current"
old = root / "store-only-d2a9199-20261008"
release = root / "assets-e05f9605eeaa-20261009"
temporary_link = root / "assets-switch-e05f9605eeaa"

def marker(path):
    value = json.loads((path / "release.json").read_text())
    assert value["commit"] == commit
    return value

def retained():
    # Keep these existing public pages exactly; no unrelated marketing/legal
    # edits or deleted indexable pages are part of this feature release.
    for name in ("features", "privacy", "guides"):
        for before in (old / name).rglob("*"):
            if before.is_file():
                after = release / before.relative_to(old)
                assert before.read_bytes() == after.read_bytes()
    for name in ("robots.txt", "sitemap.xml", "404.html"):
        assert (old / name).read_bytes() == (release / name).read_bytes()

if args.phase == "prepare":
    assert current.is_symlink() and current.resolve() == old.resolve()
    assert package.is_file() and hashlib.sha256(package.read_bytes()).hexdigest() == expected_sha
    assert not release.exists() and not temporary_link.exists()
    with tarfile.open(package) as archive:
        for member in archive.getmembers():
            name = PurePosixPath(member.name)
            assert not name.is_absolute() and ".." not in name.parts
            assert member.isfile() or member.isdir()
        release.mkdir(mode=0o755)
        archive.extractall(release, filter="data")
    marker(release)
    assert (release / "main.dart.js").stat().st_size > 1_000_000
    assert (release / "flutter_bootstrap.js").is_file()
    for name in ("features", "privacy", "guides"):
        shutil.copytree(old / name, release / name, dirs_exist_ok=True)
    for name in ("robots.txt", "sitemap.xml", "404.html"):
        shutil.copy2(old / name, release / name)
    retained()
    print("Verified scoped website package staged; existing public pages retained")
elif args.phase == "promote":
    assert current.is_symlink() and current.resolve() == old.resolve()
    marker(release)
    retained()
    assert not temporary_link.exists()
    temporary_link.symlink_to(release)
    os.replace(temporary_link, current)
    try:
        with urllib.request.urlopen("https://app.svaultai.com/release.json", timeout=15) as response:
            assert json.load(response)["commit"] == commit
        with urllib.request.urlopen("https://app.svaultai.com/main.dart.js", timeout=15) as response:
            assert response.status == 200 and len(response.read()) > 1_000_000
    except Exception:
        temporary_link.symlink_to(old)
        os.replace(temporary_link, current)
        raise RuntimeError("Public web gate failed; original website restored") from None
    print("Assets web release live; previous release retained for rollback")
else:
    assert current.resolve() == release.resolve()
    marker(release)
    retained()
    print("Web release and retained public pages verified")
