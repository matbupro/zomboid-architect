"""ingestor/tag_release.py — Creer un tag Git annote + backup + patch notes.

Responsabilites :
  1. Lire le fichier VERSION et incrémenter (semver)
  2. Ecrire le nouveau numéro de version
  3. Créer un commit "release: vX.Y.Z" avec les fichiers modifies
  4. Creer un tag git annote (-a -m ...)
  5. Sauvegarder la base ChromaDB production dans backups/chromadb/
  6. Generer le changelog de la release a partir des commits depuis le dernier tag

Usage :
  python -m ingestor.tag_release                          # bump patch (0.3.0 → 0.3.1)
  python -m ingestor.tag_release --minor                  # bump minor (0.3.0 → 0.4.0)
  python -m ingestor.tag_release --major                  # bump major (0.3.0 → 1.0.0)
  python -m ingestor.tag_release --version 1.0.0-beta     # version explicite
  python -m ingestor.tag_release --no-push                # ne pas push (commit + tag local seulement)
  python -m ingestor.tag_release --changelog-only         # generer patch notes sans tag
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).parent.parent
VERSION_FILE = ROOT / "VERSION"
CHANGELOG_FILE = ROOT / "CHANGELOG.md"
BACKUP_DIR = ROOT / "backups" / "chromadb"
PROD_DIR = ROOT / "data" / "production"
STAGING_DIR = ROOT / "data" / "staging"


# ── Version helpers ──────────────────────────────────────────────────────────


@dataclass
class SemVer:
    major: int
    minor: int
    patch: int
    pre: Optional[str] = None  # ex: "alpha", "beta", "rc.1"

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.pre:
            base += f"-{self.pre}"
        return base

    def bump(self, part: str = "patch") -> SemVer:
        """Retourne une nouvelle version avec le segment incrémente."""
        if part == "major":
            return SemVer(self.major + 1, 0, 0, None)  # major reset pre-release
        elif part == "minor":
            return SemVer(self.major, self.minor + 1, 0, None)
        elif part == "patch":
            return SemVer(self.major, self.minor, self.patch + 1)
        else:
            raise ValueError(f"Unknown version part: {part!r}")

    @classmethod
    def from_string(cls, s: str) -> SemVer:
        m = re.match(r"(\d+)\.(\d+)\.(\d+)(?:-(.+))?", s.strip())
        if not m:
            raise ValueError(f"Invalid version string: {s!r}")
        return cls(
            int(m.group(1)),
            int(m.group(2)),
            int(m.group(3)),
            m.group(4),
        )


def read_version() -> SemVer:
    # Lire avec UTF-8-SIG pour ignorer automatiquement le BOM
    content = VERSION_FILE.read_text(encoding="utf-8-sig").strip()
    return SemVer.from_string(content)


def write_version(ver: SemVer) -> None:
    # UTF-8 sans BOM (UTF-8-SIG ajoute un BOM, on l'évite ici)
    VERSION_FILE.write_text(str(ver) + "\n", encoding="utf-8")


# ── Git helpers ──────────────────────────────────────────────────────────────


def _git(args: list[str], cwd: Path = ROOT) -> str:
    """Executer une commande git et retourner stdout."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def get_last_tag() -> Optional[str]:
    """Retourne le nom du dernier tag annoté ou None."""
    try:
        tag = _git(["describe", "--tags", "--abbrev=0"], cwd=ROOT)
        return tag if tag else None
    except RuntimeError:
        return None


def get_commits_since_tag(tag: Optional[str]) -> list[dict]:
    """Retourne les commits depuis un tag (ou le debut du repo).

    Chaque commit est {hash, message, author, date}.
    """
    range_spec = f"{tag}..HEAD" if tag else "HEAD"
    fmt = "%H%n%s%n%an%n%ai%n---COMMIT_SEP---"
    output = _git(["log", "--format=" + fmt, range_spec], cwd=ROOT)

    commits = []
    for block in output.split("---COMMIT_SEP---\n"):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        if len(lines) >= 4:
            commits.append({
                "hash": lines[0][:8],
                "message": lines[1],
                "author": lines[2],
                "date": lines[3],
            })
    return commits


def _is_release_commit(msg: str) -> bool:
    """Filtre les commits de release (tag, bump) du changelog."""
    patterns = [
        r"^release:", r"^version bump", r"^tag:", r"^bump version",
        r"feat: incremental ingestion", r"feat: mod scan",
    ]
    return any(re.search(p, msg, re.IGNORECASE) for p in patterns)


# ── Backup ───────────────────────────────────────────────────────────────────


def create_backup() -> Optional[Path]:
    """Backup production ChromaDB + raw data → backups/chromadb/YYYY-MM_vX.Y.Z.tar.gz."""
    RAW_DIR = ROOT / "data" / "raw"

    if not PROD_DIR.exists():
        print("[tag_release] Production dir does not exist — skipping backup")
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ver = str(read_version())
    stamp = datetime.now(timezone.utc).strftime("%Y-%m")
    snapshot_name = f"{stamp}_production_{ver}.tar.gz"
    snapshot_path = BACKUP_DIR / snapshot_name

    with tarfile.open(snapshot_path, "w:gz") as tar:
        tar.add(PROD_DIR, arcname=PROD_DIR.name)
        # Inclure les données brutes (source de vérité pour reconstruction)
        if RAW_DIR.exists():
            tar.add(RAW_DIR, arcname=RAW_DIR.name)

    print(f"[tag_release] Production backup -> {snapshot_path}")
    return snapshot_path


# ── Changelog generation ─────────────────────────────────────────────────────


def generate_changelog(commits: list[dict]) -> str:
    """Genere le corps du changelog a partir des commits."""
    # Group par type de commit (conventional commits)
    groups: dict[str, list[dict]] = {}
    for c in commits:
        if _is_release_commit(c["message"]):
            continue
        msg_lower = c["message"].lower()
        if msg_lower.startswith(("feat", "fix", "chore", "docs", "refactor")):
            prefix = re.match(r"(\w+)", c["message"]).group(1)
        else:
            prefix = "misc"
        groups.setdefault(prefix, []).append(c)

    icons = {
        "feat": "✨",
        "fix": "🐛",
        "docs": "📝",
        "chore": "🔧",
        "refactor": "♻️",
        "misc": "📌",
    }

    lines = []
    for prefix in ["feat", "fix", "docs", "chore", "refactor", "misc"]:
        items = groups.get(prefix, [])
        if not items:
            continue
        icon = icons.get(prefix, "📌")
        title_map = {
            "feat": "Nouvelles fonctionnalités",
            "fix": "Corrections de bugs",
            "docs": "Documentation",
            "chore": "Tâches internes",
            "refactor": "Refactoring",
            "misc": "Autres",
        }
        lines.append(f"\n### {icon} {title_map[prefix]}")
        for c in items:
            # Format: - feat(module): message court (par <auteur>)
            detail = c["message"]
            author = c["author"]
            lines.append(f"  - `{detail}` ({author})")

    return "\n".join(lines)


# ── Main release flow ───────────────────────────────────────────────────────


def do_release(
    version_part: str = "patch",
    explicit_version: Optional[str] = None,
    no_push: bool = False,
    changelog_only: bool = False,
) -> dict:
    """Execute le flux complet de release.

    Args:
        version_part: 'major' | 'minor' | 'patch'.
        explicit_version: Version explicite (ignore bump).
        no_push: Ne pas push origin.
        changelog_only: Ne rien modifier, juste generer les patch notes.

    Returns un dict avec les details de la release (pour logging).
    """
    old_ver = read_version()

    # Mode 'changelog only' — aucun git ni ecriture
    if changelog_only:
        last_tag = get_last_tag()
        commits = get_commits_since_tag(last_tag) if last_tag else []
        changelog_body = generate_changelog(commits)
        release_info = {
            "old_version": str(old_ver),
            "new_version": None,
            "last_tag": last_tag,
            "commit_count": len(commits),
            "changelog_preview": changelog_body[:200],
        }
        if changelog_body:
            print("\nChangelog:")
            print(changelog_body)
        return release_info

    new_ver = SemVer.from_string(explicit_version) if explicit_version else old_ver.bump(version_part)

    last_tag = get_last_tag()
    commits = get_commits_since_tag(last_tag) if last_tag else []

    changelog_body = generate_changelog(commits)

    # Output info
    release_info = {
        "old_version": str(old_ver),
        "new_version": str(new_ver),
        "last_tag": last_tag,
        "commit_count": len(commits),
        "changelog_preview": changelog_body[:200] if changelog_body else "",
    }

    print(f"[tag_release] {old_ver} -> {new_ver}")

    # Ecrire nouvelle version
    write_version(new_ver)
    print(f"[tag_release] VERSION mise a jour -> {new_ver}")

    # Backup production
    backup_path = create_backup()

    # Commit de release
    release_msg = f"release: v{new_ver}"
    _git(["add", str(VERSION_FILE), "CHANGELOG.md"])
    _git(["commit", "-m", release_msg])
    print(f"[tag_release] Commit — {release_msg}")

    # Tag annote
    tag_name = f"v{new_ver}"
    _git(["tag", "-a", tag_name, "-m", f"Release {tag_name}\n\n{changelog_body[:500]}"])
    print(f"[tag_release] Tag crée — {tag_name}")

    if not no_push:
        _git(["push"])
        _git(["push", "--tags"])
        print("[tag_release] Push vers origin")

    return release_info


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Creer un tag Git annote + backup ChromaDB + patch notes.",
        prog="python -m ingestor.tag_release",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--major", action="store_true", help="Bump major (X.0.0)")
    group.add_argument("--minor", action="store_true", help="Bump minor (0.X.0)")
    group.add_argument("--patch", action="store_true", help="Bump patch (0.0.X) — default")
    parser.add_argument(
        "--version",
        type=str,
        default=None,
        help="Version explicite (ex: 1.0.0-beta)",
    )
    parser.add_argument("--no-push", action="store_true", help="Ne pas push (commit + tag local seulement)")
    parser.add_argument(
        "--changelog-only",
        action="store_true",
        help="Generer patch notes sans creer de release",
    )
    args = parser.parse_args(argv)

    if args.version:
        version_part = "patch"  # ignore major/minor when explicit
    elif args.major:
        version_part = "major"
    elif args.minor:
        version_part = "minor"
    else:
        version_part = "patch"

    try:
        info = do_release(
            version_part=version_part,
            explicit_version=args.version,
            no_push=args.no_push,
            changelog_only=args.changelog_only,
        )
        return 0
    except RuntimeError as exc:
        print(f"[tag_release] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
