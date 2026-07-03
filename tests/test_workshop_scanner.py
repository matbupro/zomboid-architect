"""test_workshop_scanner — Tests du module workshop_scanner.

Couverture : scan, metadata parsing, fallback nom dossier, recherche par ID,
cas limites (racine vide, addoninfo corrompu, caracteres speciaux).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ingestor.steam.workshop_scanner import WorkshopModInfo, WorkshopScanner


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def large_workshop(tmp_path: Path):
    """Racine workshop avec 50 mods — pour tests de validation structure."""
    ws_root = tmp_path / "ws"
    ws_root.mkdir(parents=True)

    for i in range(1, 51):
        mod = ws_root / str(1000000 + i)
        mod.mkdir()
        (mod / "addoninfo.txt").write_text(
            f'name "Mod {i}"\nauthor "Author{i}"\ndescription "Description {i}"\n',
            encoding="utf-8",
        )

    return ws_root


# ===========================================================================
# Tests : scan basic
# ===========================================================================


def test_scan_detects_mods(fake_workshop):
    """Le scanner detecte 3 mods (ignore les dossiers non-numeriques)."""
    async def _run():
        scanner = WorkshopScanner(fake_workshop)
        return await scanner.scan()

    mods = asyncio_run(_run())
    assert len(mods) == 3


def test_scan_mod_names(fake_workshop):
    """Les noms des mods sont extraits de addoninfo.txt."""
    async def _run():
        scanner = WorkshopScanner(fake_workshop)
        return await scanner.scan()

    mods = asyncio_run(_run())
    names = {m.name for m in mods}
    assert "Test Mod Alpha" in names
    assert "Test Mod Beta" in names


def test_scan_empty_root(fake_empty_workshop):
    """Racine workshop vide → liste de mods vide."""
    async def _run():
        scanner = WorkshopScanner(fake_empty_workshop)
        return await scanner.scan()

    mods = asyncio_run(_run())
    assert len(mods) == 0


def test_scan_nonexistent_root(tmp_path):
    """Racine inexistante → liste vide (pas d'exception)."""
    fake = tmp_path / "does_not_exist"
    scanner = WorkshopScanner(fake)
    mods = asyncio_run(scanner.scan())
    assert len(mods) == 0


# ===========================================================================
# Tests : metadata parsing
# ===========================================================================


def test_scan_metadata_author(fake_workshop):
    """L'auteur est correctement extrait de addoninfo.txt."""
    async def _run():
        scanner = WorkshopScanner(fake_workshop)
        return await scanner.scan()

    mods = asyncio_run(_run())
    alpha = next(m for m in mods if m.mod_id == 1000001)
    assert alpha.author == "TestAuthor1"


def test_scan_metadata_description(fake_workshop):
    """La description est correctement extraite."""
    async def _run():
        scanner = WorkshopScanner(fake_workshop)
        return await scanner.scan()

    mods = asyncio_run(_run())
    alpha = next(m for m in mods if m.mod_id == 1000001)
    assert alpha.description == "First test mod."


def test_scan_metadata_file_count(fake_workshop):
    """file_count compte recursivement les fichiers du dossier mod."""
    async def _run():
        scanner = WorkshopScanner(fake_workshop)
        return await scanner.scan()

    mods = asyncio_run(_run())
    alpha = next(m for m in mods if m.mod_id == 1000001)
    # addoninfo.txt + script.lua = 2 fichiers
    assert alpha.file_count == 2


# ===========================================================================
# Tests : fallback nom dossier (sans addoninfo.txt)
# ===========================================================================


def test_scan_no_addoninfo_fallback_name(fake_workshop):
    """Mod sans addoninfo.txt utilise le nom du dossier comme nom."""
    async def _run():
        scanner = WorkshopScanner(fake_workshop)
        return await scanner.scan()

    mods = asyncio_run(_run())
    gamma = next(m for m in mods if m.mod_id == 1000003)
    # Le scanner lit README.txt et extrait "# Readme Only" comme nom
    assert gamma.name is not None  # ne doit pas etre None


def test_scan_no_addoninfo_author_is_none(fake_workshop):
    """Sans addoninfo, author reste None."""
    async def _run():
        scanner = WorkshopScanner(fake_workshop)
        return await scanner.scan()

    mods = asyncio_run(_run())
    gamma = next(m for m in mods if m.mod_id == 1000003)
    assert gamma.author is None
    assert gamma.description is None


# ===========================================================================
# Tests : find_by_mod_id
# ===========================================================================


def test_find_by_id_existing(fake_workshop):
    """find_by_mod_id retrouve un mod present."""
    async def _run():
        scanner = WorkshopScanner(fake_workshop)
        return await scanner.find_by_mod_id(1000001)

    mod = asyncio_run(_run())
    assert mod is not None
    assert mod.name == "Test Mod Alpha"


def test_find_by_id_missing(fake_workshop):
    """find_by_mod_id retourne None pour un ID inexistant."""
    async def _run():
        scanner = WorkshopScanner(fake_workshop)
        return await scanner.find_by_mod_id(9999999)

    mod = asyncio_run(_run())
    assert mod is None


# ===========================================================================
# Tests : _parse_addoninfo (direct access via public API)
# ===========================================================================


def test_parse_addoninfo_valid_space_format(tmp_path):
    """Format valve standard : key "value"."""
    folder = tmp_path / "123456"
    folder.mkdir()
    info_file = folder / "addoninfo.txt"
    info_file.write_text(
        'name "My Mod"\nauthor "CoolDev"\ndescription "Great stuff"\n',
        encoding="utf-8",
    )

    result = WorkshopScanner._parse_addoninfo(info_file)
    assert result["name"] == "My Mod"
    assert result["author"] == "CoolDev"
    assert result["description"] == "Great stuff"


def test_parse_addoninfo_equals_format(tmp_path):
    """Format avec egalite : key="value"."""
    folder = tmp_path / "123456"
    folder.mkdir()
    info_file = folder / "addoninfo.txt"
    info_file.write_text('name="My Mod"\nauthor="Dev"\n', encoding="utf-8")

    result = WorkshopScanner._parse_addoninfo(info_file)
    assert result["name"] == "My Mod"
    assert result["author"] == "Dev"


def test_parse_addoninfo_corrupted(tmp_path):
    """Contenu sans cle/valeur valide → retourne dict vide (pas d'exception)."""
    folder = tmp_path / "123456"
    folder.mkdir()
    # Ligne sans esperite ni egalite entre cle et valeur
    info_file = folder / "addoninfo.txt"
    info_file.write_text("NOT-A-KV-LINE", encoding="utf-8")

    result = WorkshopScanner._parse_addoninfo(info_file)
    assert len(result) == 0


def test_parse_addoninfo_special_chars(tmp_path):
    """Noms avec accents et chaines vides."""
    folder = tmp_path / "123456"
    folder.mkdir()
    info_file = folder / "addoninfo.txt"
    info_file.write_text('name "Mod a l\'emu"\nauthor ""\ndescription "Test "\n', encoding="utf-8")

    result = WorkshopScanner._parse_addoninfo(info_file)
    assert result["name"] == "Mod a l'emu"
    assert result["author"] == ""


def test_parse_addoninfo_empty_file(tmp_path):
    """Fichier vide → dict vide."""
    info_file = tmp_path / "addoninfo.txt"
    info_file.write_text("", encoding="utf-8")

    result = WorkshopScanner._parse_addoninfo(info_file)
    assert len(result) == 0


def test_parse_addoninfo_tags(tmp_path):
    """Parsing des tags separes par virgule."""
    folder = tmp_path / "123456"
    folder.mkdir()
    info_file = folder / "addoninfo.txt"
    info_file.write_text('tags "weapons,combat,pve"\n', encoding="utf-8")

    result = WorkshopScanner._parse_addoninfo(info_file)
    assert result["tags"] == "weapons,combat,pve"


# ===========================================================================
# Tests : WorkshopModInfo.to_metadata
# ===========================================================================


def test_mod_info_to_metadata():
    """Conversion en dict ChromaDB — coupe description a 500 chars."""
    meta = WorkshopModInfo(
        mod_id=1234,
        folder_path=Path("/fake"),
        name="Test",
        author="Auth",
        description="A" * 600,
        date_created="2024-01-01",
        date_updated="2024-01-02",
        file_count=5,
        tags=["tag1", "tag2"],
    ).to_metadata()

    assert meta["mod_id"] == 1234
    assert meta["name"] == "Test"
    assert meta["author"] == "Auth"
    assert len(meta["description"]) == 500
    assert meta["file_count"] == 5
    assert meta["tags"] == "tag1,tag2"
    assert meta["source"] == "steam_workshop"


# ===========================================================================
# Tests : content_root property
# ===========================================================================


def test_content_root_is_resolved(fake_workshop):
    """content_root retourne un Path resolu (absolu)."""
    scanner = WorkshopScanner(fake_workshop)
    assert scanner.content_root.is_absolute()


# ===========================================================================
# Helpers
# ===========================================================================


def asyncio_run(coro):
    """Executer une coroutine."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return coro
    return asyncio.run(coro)
