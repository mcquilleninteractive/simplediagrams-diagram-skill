"""Checks that what this public repository would publish holds nothing private or stray.

It looks at every entry Git tracks and every untracked file Git does not ignore, which is
what a commit could pick up. It fails on text that is not UTF-8 or holds a character no
one can see, local paths, email addresses, credentials, personal names, the names of
private repositories, internal records or working arrangements, kinds of file that never
belong here, and any entry that is not a plain file, such as a symbolic link, whose
target is checked too. The forbidden words are assembled from parts so that this file
does not match them itself, and the checker is shown to catch one probe of each kind in
a temporary folder, never in the repository. Outside a Git checkout, such as an installed
copy of the skill, there is nothing to check.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import struct
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
IGNORE_CASE = re.IGNORECASE
# Characters no one sees in an editor or a review: control characters other than tab and
# line breaks, the no-break space, the soft hyphen, zero-width and direction marks, and
# the byte-order mark. Given by number so that this file holds none of them itself.
INVISIBLE = [
    *range(0x09), 0x0B, 0x0C, *range(0x0E, 0x20), 0x7F, 0xA0, 0xAD,
    *range(0x200B, 0x2010), *range(0x202A, 0x202F), *range(0x2060, 0x2065), *range(0x2066, 0x206A), 0xFEFF,
]  # fmt: skip

# Text that would place a file on someone's machine, give away a secret, name a person or
# what is not published, or hide from a reader. The company's name, and its GitHub
# organisation, may appear; the family name on its own may not.
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
    "a personal name": re.compile(
        r"\b" + "Dan" + "iel" + r"\b|" + "dan" + "ielmcq|" + "mc" + "quillen" + r"(?!\s*interactive)", IGNORE_CASE
    ),
    "a working arrangement": re.compile("scratch" + "pad|claude-" + r"\d{3}|mana" + r"ger\s+session|sub" + "agent", IGNORE_CASE),
    "an invisible character": re.compile("[" + "".join(re.escape(chr(code)) for code in INVISIBLE) + "]"),
}
# Generic text a file may hold although it matches a pattern above, by file.
ALLOWED_TEXT: dict[str, tuple[str, ...]] = {"README.md": ("~" + "/.claude/skills/",)}
# Only the reviewed plugin-listing logo may be binary.
ALLOWED_NON_TEXT: frozenset[str] = frozenset({".claude-plugin/icon.png"})
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


def forbidden(text: str) -> list[str]:
    """What each line of `text` gives away, as `line: what` entries. Lines are split at line
    feeds only, so no other control character can pass as a line break unseen."""
    return [
        f"{number}: {what}"
        for number, line in enumerate(text.split("\n"), start=1)
        for what, pattern in FORBIDDEN_TEXT.items()
        if pattern.search(line)
    ]


def problems(root: Path, names: list[str]) -> list[str]:
    """Everything wrong with the entries `names`, relative to `root`, as publishable files."""
    found = []
    for name in names:
        path = root / name
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            found.append(f"{name}: listed by Git but missing; restore it, or remove it with git rm")
            continue
        if stat.S_ISLNK(mode):
            found.append(f"{name}: a symbolic link, which is never published")
            found += [f"{name}: its target, line {entry}" for entry in forbidden(os.readlink(path))]
            continue
        if not stat.S_ISREG(mode):
            found.append(f"{name}: not a plain file")
            continue
        if name in ALLOWED_NON_TEXT:
            if path.stat().st_size >= 2_000_000:
                found.append(f"{name}: icon must be under 2 MB")
                continue
            data = path.read_bytes()
            if len(data) < 33 or data[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
                found.append(f"{name}: icon must be a PNG with an IHDR header")
                continue
            width, height = struct.unpack(">II", data[16:24])
            if width != height or not 512 <= width <= 2048:
                found.append(f"{name}: icon must be square and 512 to 2048 pixels")
            continue
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
        found += [f"{name}:{entry}" for entry in forbidden(text)]
    return found


def _published_names() -> list[str]:
    """Every entry a commit could pick up: tracked, or untracked and not ignored."""
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("not a Git checkout, so there is no published set of files to check")
    listing = subprocess.run(
        [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode("utf-8")
    return [name for name in sorted(set(listing.split("\0"))) if name]


def test_nothing_published_is_private_secret_or_stray() -> None:
    """The repository is public: a local path, an address, a credential, a name, a private
    repository's name or an internal record in any file would leak with it, and a log,
    cache, picture, key, link or built document has no place in it."""
    assert problems(ROOT, _published_names()) == []


def test_only_the_listing_icon_is_allowed_as_a_binary_image(tmp_path: Path) -> None:
    """The product icon exception must not admit user images or malformed icons."""
    name = ".claude-plugin/icon.png"
    icon = tmp_path / name
    icon.parent.mkdir()
    icon.write_bytes((ROOT / name).read_bytes())
    assert problems(tmp_path, [name]) == []
    (tmp_path / "photo.png").write_bytes(icon.read_bytes())
    assert problems(tmp_path, ["photo.png"])
    icon.write_bytes(b"not a PNG")
    assert any("IHDR" in problem for problem in problems(tmp_path, [name]))
    data = bytearray((ROOT / name).read_bytes())
    data[16:24] = struct.pack(">II", 1024, 512)
    icon.write_bytes(data)
    assert any("square" in problem for problem in problems(tmp_path, [name]))
    icon.write_bytes(b"x" * 2_000_000)
    assert any("under 2 MB" in problem for problem in problems(tmp_path, [name]))


# One probe of each kind the checker must catch, written only to a temporary folder.
PROBES: dict[str, str | bytes] = {
    "binary.txt": b"\xff\xfe\x00not text",
    "invisible.md": "a" + chr(0x200B) + "b",
    "bidi.md": "a" + chr(0x202E) + "b",
    "form-feed.md": "a" + chr(0x0C) + "b",
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
    "person.md": "ask " + "Dan" + "iel",
    "family.md": "as Mr " + "Mc" + "Quillen said",
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
# Generic text that must pass: the copy-to path the README names, the company and its
# GitHub organisation.
ALLOWED_PROBE = (
    "Copy it into `" + "~" + "/.claude/skills/`. Made by " + "Mc" + "Quillen Interactive Pty. Ltd., "
    "github.com/" + "mc" + "quilleninteractive.\n"
)


def test_the_checker_catches_one_probe_of_each_kind(tmp_path: Path) -> None:
    """A checker that was clean only by luck proves nothing: each kind of leak and each
    kind of stray entry must be caught, a link's target checked as well, and the allowed
    generic text must not be caught."""
    for name, content in PROBES.items():
        (tmp_path / name).write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    for name in PROBE_NAMES:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(ALLOWED_PROBE, encoding="utf-8")
    (tmp_path / "link.md").symlink_to("/" + "Users/someone/notes.md")
    (tmp_path / "folder").mkdir()
    os.mkfifo(tmp_path / "pipe")
    entries = ["link.md", "folder", "pipe", "gone.md"]
    found = problems(tmp_path, [*PROBES, *PROBE_NAMES, "README.md", *entries])
    for name in [*PROBES, *PROBE_NAMES, *entries]:
        assert any(line.startswith(f"{name}:") for line in found), name
    assert "link.md: its target, line 1: a home folder path" in found
    assert not any(line.startswith("README.md") for line in found), found
