"""Checks that what this public repository would publish holds nothing private or stray.

It looks at every file Git tracks and every untracked file Git does not ignore, which is
what a commit could pick up. It fails on text that is not UTF-8, local paths, email
addresses, credentials, the names of private repositories, internal records or working
arrangements, and kinds of file that never belong here. The forbidden words are assembled
from parts so that this file does not match them itself, and the checker is shown to
catch one probe of each kind in a temporary folder, never in the repository. Outside a Git
checkout, such as an installed copy of the skill, there is nothing to check.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
IGNORE_CASE = re.IGNORECASE

# Text that would place a file on someone's machine, give away a secret, or name what is
# not published.
FORBIDDEN_TEXT: dict[str, re.Pattern[str]] = {
    "a home folder path": re.compile("/" + "Users" + "/|/" + "home" + "/[a-z]|" + "~" + "/", IGNORE_CASE),
    "a temporary folder path": re.compile(
        "/" + "private" + "/|/" + "var" + "/folders|/" + "tmp" + "/|" + "[a-z]:" + r"\\" + "users", IGNORE_CASE
    ),
    "an email address": re.compile(r"[A-Za-z0-9._%+-]+" + "@" + r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
    "a private key": re.compile("-----" + "BEGIN" + r"[A-Z ]*" + "PRIVATE " + "KEY" + "-----"),
    "an access token": re.compile(
        r"\b" + "gh" + r"p_[A-Za-z0-9]{8,}|\b" + "github" + r"_pat_[A-Za-z0-9_]{8,}|\b" + "sk" + r"_(live|test)_[A-Za-z0-9]{8,}"
        + r"|\b" + "AK" + r"IA[0-9A-Z]{16}\b|\b" + "xo" + r"x[bp]-[A-Za-z0-9-]+"
    ),
    "a credential file's key": re.compile('"' + "private" + '_key"'),
    "a private repository's name": re.compile(
        "simplediagrams" + "-(project|desktop|app|legacy)|simplediagrams" + "_site|skill-" + "maintenance|work-" + "register",
        IGNORE_CASE,
    ),
    "an internal decision record": re.compile(r"\b" + "AD" + r"R[ -]?\d+", IGNORE_CASE),
    "a personal name": re.compile(r"\b" + "Dan" + "iel" + r"\b|" + "dan" + "ielmcq", IGNORE_CASE),
    "a working arrangement": re.compile("scratch" + "pad|claude-" + r"\d{3}|mana" + r"ger\s+session|sub" + "agent", IGNORE_CASE),
}
# Generic text a file may hold although it matches a pattern above, by file.
ALLOWED_TEXT: dict[str, tuple[str, ...]] = {"README.md": ("~" + "/.claude/skills/",)}
# Published files that may be other than UTF-8 text. There are none.
ALLOWED_NON_TEXT: frozenset[str] = frozenset()
# Files that never ship: logs, merge leftovers, archives, caches, Finder files, pictures
# and documents people supply, keys and credentials, databases, and built documents,
# which are made from a spec rather than kept.
FORBIDDEN_NAMES = re.compile(
    r"(^|/)(\.DS_Store|\._[^/]*|" + "Auth" + r"Key_[^/]*)$|(^|/)(__pycache__|\.env[^/]*)(/|$)"
    r"|\.(log|orig|rej|zip|tar|gz|tgz|7z|pyc|png|jpe?g|heic|gif|pdf|pem|key|p8|p12|mobileprovision|jks|keystore"
    r"|sqlite3?|db)$|\.simplediagram(/|$)",
    IGNORE_CASE,
)
LARGEST_FILE = 1_000_000


def problems(root: Path, names: list[str]) -> list[str]:
    """Everything wrong with the files `names`, relative to `root`, as publishable files."""
    found = []
    for name in names:
        path = root / name
        if FORBIDDEN_NAMES.search(name):
            found.append(f"{name}: a kind of file that is never published")
        if path.stat().st_size > LARGEST_FILE:
            found.append(f"{name}: larger than {LARGEST_FILE} bytes")
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            if name not in ALLOWED_NON_TEXT:
                found.append(f"{name}: not UTF-8 text")
            continue
        for allowed in ALLOWED_TEXT.get(name, ()):
            text = text.replace(allowed, "")
        for number, line in enumerate(text.splitlines(), start=1):
            found += [f"{name}:{number}: {what}" for what, pattern in FORBIDDEN_TEXT.items() if pattern.search(line)]
    return found


def _published_names() -> list[str]:
    """Every file a commit could pick up: tracked, or untracked and not ignored."""
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("not a Git checkout, so there is no published set of files to check")
    listing = subprocess.run(
        [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode("utf-8")
    return [name for name in sorted(set(listing.split("\0"))) if name and (ROOT / name).is_file()]


def test_nothing_published_is_private_secret_or_stray() -> None:
    """The repository is public: a local path, an address, a credential, a private
    repository's name or an internal record in any file would leak with it, and a log,
    cache, picture, key or built document has no place in it."""
    assert problems(ROOT, _published_names()) == []


# One probe of each kind the checker must catch, written only to a temporary folder.
PROBES: dict[str, str | bytes] = {
    "binary.txt": b"\xff\xfe\x00not text",
    "home.md": "see /" + "Users/someone/notes",
    "tilde.md": "copy it to " + "~" + "/somewhere",
    "tmp.md": "written to /" + "tmp/out",
    "windows.md": "C:" + "\\" + "USERS\\someone",
    "mail.md": "write to someone" + "@" + "example.org",
    "pem.md": "-----" + "BEGIN RSA " + "PRIVATE KEY" + "-----",
    "github.md": "token " + "gh" + "p_" + "A1b2C3d4E5f6G7h8",
    "github-pat.md": "github" + "_pat_" + "11ABCDEFG0123456789",
    "stripe.md": "sk" + "_live_" + "abcdefgh12345678",
    "aws.md": "AK" + "IA" + "ABCDEFGHIJKLMNOP",
    "slack.md": "xo" + "xb-" + "1234-abcd",
    "service.json": '{"' + "private" + '_key": "x"}',
    "repo.md": "see SimpleDiagrams" + "-Project for that",
    "site.md": "the old simplediagrams" + "_site behaviour",
    "record.md": "as " + "ad" + "r 7 decided",
    "scratch.md": "kept in the Scratch" + "Pad",
    "manager.md": "ask the Mana" + "ger Session",
    "helper.md": "a Sub" + "agent did it",
}
PROBE_NAMES = [
    "photo.PNG", "scan.jpeg", "shot.heic", "anim.gif", "spec.pdf", "cert.pem", "signing.key",
    "AuthKey_" + "ABC123.p8", "bundle.p12", "app.mobileprovision", "release.jks", "debug.keystore",
    "cache.sqlite", "store.db", ".env.local", ".envs/production", "out.simplediagram/document.json",
    "notes.orig", "scripts/__pycache__/sd_spec.pyc",
]


def test_the_checker_catches_one_probe_of_each_kind(tmp_path: Path) -> None:
    """A checker that was clean only by luck proves nothing: each kind of leak and each
    kind of stray file must be caught, and the one allowed generic path must not be."""
    for name, content in PROBES.items():
        (tmp_path / name).write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    for name in PROBE_NAMES:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Copy it into `" + "~" + "/.claude/skills/`.\n", encoding="utf-8")
    found = problems(tmp_path, [*PROBES, *PROBE_NAMES, "README.md"])
    for name in [*PROBES, *PROBE_NAMES]:
        assert any(line.startswith(f"{name}:") for line in found), name
    assert not any(line.startswith("README.md") for line in found)
