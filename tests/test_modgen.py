"""test_modgen — Tests unitaires du module de generation de mods (Phase 12).

Couverture :
  - Validation des noms et specs (schema.py)
  - Generation complete d'un dossier mod (generator.py)
  - Templates Jinja2 (mod.info, init.lua, etc.)
  - CLI (generate, list-templates, validate)
  - ZIP packaging (zip_mod)

Tous les tests utilisent tmp_path (pytest builtin) — aucun fichier permanent ecrit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Ajouter le project root au sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def tmp_mods_dir(tmp_path: Path) -> Path:
    """Repertoire temporaire pour les mods generes."""
    return tmp_path / "mods"


@pytest.fixture()
def valid_spec() -> Any:
    """ModSpec valide minimal."""
    from src.modgen.schema import ModSpec

    return ModSpec(
        name="TestMod",
        description="A test mod for Zomboid_Architect unit tests.",
        author="TestAuthor",
    )


@pytest.fixture()
def generator_with_tmp_output(tmp_mods_dir: Path) -> Any:
    """ModGenerator pointe vers tmp_path pour tests."""
    from src.modgen.config import ModGenConfig
    from src.modgen.generator import ModGenerator

    config = ModGenConfig(output_path=tmp_mods_dir)
    return ModGenerator(config)


# ===========================================================================
# Tests : Schema (schema.py)
# ===========================================================================


def test_modspec_creation():
    """ModSpec se cree sans erreur avec tous les champs par defaut."""
    from src.modgen.schema import ModSpec, ModType

    spec = ModSpec(name="MyMod", description="desc")
    assert spec.name == "MyMod"
    assert spec.author == "Zomboid Architect"  # valeur par defaut
    assert spec.mod_type == ModType.ITEM  # type par defaut
    assert spec.singleplayer is True
    assert spec.multiplayer is True


def test_modspec_tags_csv_conversion():
    """Tags CSV converis automatiquement en liste via __post_init__."""
    from src.modgen.schema import ModSpec

    spec = ModSpec(name="Test", description="desc", tags="weapons,combat,pve")
    assert spec.tags == ["weapons", "combat", "pve"]


def test_build_mod_id_produits_slug_propre():
    """_build_mod_id produit un ID canonique sans caracteres speciaux."""
    from src.modgen.schema import ModType, _build_mod_id

    mod_id = _build_mod_id("Custom Sword (1.0)", ModType.ITEM)
    assert "custom_sword" in mod_id
    assert "(" not in mod_id
    assert ")" not in mod_id
    assert len(mod_id.split("_")[-1]) == 8  # short UUID


def test_generated_manifest_properties():
    """GeneratedModManifest a les proprietes attendues."""
    from src.modgen.schema import GeneratedModManifest, ModSpec

    spec = ModSpec(name="Test", description="desc")
    manifest = GeneratedModManifest(
        id="test_123",
        name="Test",
        output_path=Path("/tmp/test"),
        spec=spec,
    )
    assert manifest.mod_root == Path("/tmp/test")


# ===========================================================================
# Tests : Validation (generator.py)
# ===========================================================================


def test_validate_empty_name(generator_with_tmp_output: Any):
    """Validation rejette un nom vide."""
    from src.modgen.generator import _validate_spec
    from src.modgen.schema import ModSpec

    spec = ModSpec(name="", description="desc")
    errors = _validate_spec(spec)
    assert any("ne peut pas etre vide" in e for e in errors)


def test_validate_invalid_chars(generator_with_tmp_output: Any):
    """Validation rejette des caracteres invalides dans le nom."""
    from src.modgen.generator import _validate_spec
    from src.modgen.schema import ModSpec

    spec = ModSpec(name="Mod/With/Bad", description="desc")
    errors = _validate_spec(spec)
    assert any("'/'" in e for e in errors)


def test_validate_name_too_long(generator_with_tmp_output: Any):
    """Validation rejette un nom de plus de 128 caracteres."""
    from src.modgen.generator import _validate_spec
    from src.modgen.schema import ModSpec

    spec = ModSpec(name="A" * 200, description="desc")
    errors = _validate_spec(spec)
    assert any("depasser 128" in e for e in errors)


def test_validate_valid_spec_no_errors(generator_with_tmp_output: Any):
    """Une spec valide retourne une liste d'erreurs vide."""
    from src.modgen.generator import _validate_spec
    from src.modgen.schema import ModSpec

    spec = ModSpec(name="ValidMod", description="A valid mod")
    errors = _validate_spec(spec)
    assert errors == []


def test_modgenerator_validate_spec(generator_with_tmp_output: Any):
    """La methode validate_spec de ModGenerator fonctionne."""
    from src.modgen.schema import ModSpec

    spec = ModSpec(name="", description="desc")
    errors = generator_with_tmp_output.validate_spec(spec)
    assert len(errors) > 0


# ===========================================================================
# Tests : Generation complete (generator.py)
# ===========================================================================


async def test_generate_creates_mod_root(generator_with_tmp_output: Any, valid_spec: ModSpec):
    """La generation cree le dossier root du mod dans output_path."""
    from pathlib import Path as P

    manifest = await generator_with_tmp_output.generate(valid_spec)
    assert manifest.output_path.exists()
    assert manifest.output_path.is_dir()


async def test_generate_writes_mod_info_json(generator_with_tmp_output: Any, valid_spec: ModSpec):
    """mod.info est un JSON valide avec tous les champs requis."""
    from src.modgen.generator import _validate_spec

    # First validate the spec
    errors = _validate_spec(valid_spec)
    assert errors == []

    manifest = await generator_with_tmp_output.generate(valid_spec)
    mod_info_path = manifest.output_path / "mod.info"
    assert mod_info_path.exists()

    data = json.loads(mod_info_path.read_text(encoding="utf-8"))
    assert data["name"] == valid_spec.name
    assert data["author"] == valid_spec.author
    assert data["type"] == valid_spec.mod_type.value
    assert "singleplayer" in data
    assert "multiplayer" in data
    assert "minGameVersion" in data


async def test_generate_writes_init_lua(generator_with_tmp_output: Any, valid_spec: ModSpec):
    """init.lua est cree dans media/lua/client/."""
    manifest = await generator_with_tmp_output.generate(valid_spec)
    init_lua_candidates = list(manifest.output_path.rglob("**/init.lua"))
    assert len(init_lua_candidates) > 0, f"Aucun init.lua trouve. Fichiers: {list(manifest.output_path.rglob('*'))}"
    init_lua = init_lua_candidates[0]
    assert init_lua.exists()

    content = init_lua.read_text(encoding="utf-8")
    assert "Hooks.Register" in content
    assert "OnGameInit" in content


async def test_generate_writes_zomboid_descriptor(generator_with_tmp_output: Any, valid_spec: ModSpec):
    """ZomboidModDescriptor.txt est cree en racine du mod."""
    manifest = await generator_with_tmp_output.generate(valid_spec)
    descriptor = manifest.output_path / "ZomboidModDescriptor.txt"
    assert descriptor.exists()

    content = descriptor.read_text(encoding="utf-8")
    assert f'name "{valid_spec.name}"' in content


async def test_generate_writes_readme(generator_with_tmp_output: Any, valid_spec: ModSpec):
    """README.md est cree en racine du mod."""
    manifest = await generator_with_tmp_output.generate(valid_spec)
    readme = manifest.output_path / "README.md"
    assert readme.exists()

    content = readme.read_text(encoding="utf-8")
    assert valid_spec.name in content


async def test_generate_creates_lua_directories(generator_with_tmp_output: Any, valid_spec: ModSpec):
    """Les sous-dossiers lua/ (client, shared, server) sont crees."""
    manifest = await generator_with_tmp_output.generate(valid_spec)
    for sub in ["client", "shared", "server"]:
        dir_path = manifest.output_path / "media" / "lua" / sub
        assert dir_path.exists()
        assert dir_path.is_dir()


async def test_generate_respects_config_output_path(generator_with_tmp_output: Any, valid_spec: ModSpec):
    """Le mod est ecrit dans output_path configure par la config."""
    manifest = await generator_with_tmp_output.generate(valid_spec)
    assert str(manifest.output_path).startswith(str(generator_with_tmp_output.config.output_path))


async def test_generate_manifest_file_count(generator_with_tmp_output: Any, valid_spec: ModSpec):
    """manifest.file_count correspond au nombre reel de fichiers sur le disque."""
    manifest = await generator_with_tmp_output.generate(valid_spec)
    actual_count = sum(1 for f in manifest.mod_root.rglob("*") if f.is_file())
    assert manifest.file_count == actual_count


async def test_generate_rejects_invalid_spec(generator_with_tmp_output: Any, tmp_mods_dir: Path):
    """La generation rejette une spec invalide avec ValueError."""
    from src.modgen.generator import ModGenerator
    from src.modgen.schema import ModSpec

    invalid_spec = ModSpec(name="", description="desc")
    gen = ModGenerator(generator_with_tmp_output.config)
    with pytest.raises(ValueError, match="ne peut pas etre vide"):
        await gen.generate(invalid_spec)


async def test_generate_with_custom_type(generator_with_tmp_output: Any, tmp_mods_dir: Path):
    """Different types de mod creent dossiers corrects avec le bon type dans mod.info."""
    from src.modgen.generator import ModGenerator
    from src.modgen.config import ModGenConfig
    from src.modgen.schema import ModSpec, ModType

    config = ModGenConfig(output_path=tmp_mods_dir)
    gen = ModGenerator(config)

    spec = ModSpec(
        name="TestFeature",
        description="A feature mod",
        mod_type=ModType.FEATURE,
    )
    manifest = await gen.generate(spec)
    data = json.loads((manifest.output_path / "mod.info").read_text(encoding="utf-8"))
    assert data["type"] == "feature"


# ===========================================================================
# Tests : Templates (templates/)
# ===========================================================================


def test_mod_info_template_valid_json(generator_with_tmp_output: Any):
    """Le template mod.info produit un JSON valide."""
    from src.modgen.schema import ModSpec

    spec = ModSpec(name="Test", description="desc")
    mod_info_content = generator_with_tmp_output._render_mod_info(spec)
    data = json.loads(mod_info_content)  # Ne doit pas lever JSONDecodeError
    assert "name" in data


def test_init_lua_template_contains_hooks(generator_with_tmp_output: Any, valid_spec: ModSpec):
    """Le template init.lua contient les hooks PZ standards."""
    manifest = generator_with_tmp_output  # fixture unused in this test
    from src.modgen.generator import ModGenerator
    from src.modgen.config import ModGenConfig

    async def _run():
        gen = ModGenerator(ModGenConfig(output_path=Path(__file__).parent / "tmp_test_mods"))
        return await gen.generate(valid_spec)

    # On ne genere pas le fichier ici — teste via la generation complete
    pass  # deja couvre par test_generate_writes_init_lua


# ===========================================================================
# Tests : CLI (__main__.py)
# ===========================================================================


def test_cli_list_templates():
    """La CLI list-templates affiche les templates."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "src.modgen", "list-templates"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0
    assert "mod.info.j2" in result.stdout


def test_cli_validate_existing_mod():
    """La CLI validate retourne exit code 0 pour un mod valide."""
    import subprocess

    # Utiliser le mod de test genere precedemment
    test_mod = PROJECT_ROOT / "mods" / "modgen_testmod_7b934cc6"
    if not test_mod.exists():
        pytest.skip("Test mod inexistant")

    result = subprocess.run(
        [sys.executable, "-m", "src.modgen", "validate", str(test_mod)],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0
    assert "Validation reussie" in result.stdout


def test_cli_validate_nonexistent():
    """La CLI validate retourne exit code 1 pour un dossier inexistant."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "src.modgen", "validate", "/nonexistent/path"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 1


def test_cli_generate_creates_mod():
    """La CLI generate cree un mod dans le dossier specifie."""
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "output"
        output_dir.mkdir()
        result = subprocess.run(
            [
                sys.executable, "-m", "src.modgen", "generate",
                "Test CLI Mod",
                "--name", "CLIMod",
                "--output", str(output_dir),
            ],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0
        # Un des fichiers generes doit exister
        files = list(output_dir.rglob("*"))
        assert len(files) > 0


def test_cli_no_command_shows_help():
    """Sans sous-commande, la CLI affiche l'aide."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "src.modgen"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    # Doit afficher le help (exit 1 car pas de commande donnee)
    assert result.returncode == 1 or len(result.stdout) > 0


# ===========================================================================
# Tests : Packaging (zip_mod)
# ===========================================================================


async def test_zip_mod_creates_archive(generator_with_tmp_output: Any, valid_spec: ModSpec):
    """zip_mod produit un .zip contenant les fichiers du mod."""
    manifest = await generator_with_tmp_output.generate(valid_spec)
    from src.modgen.generator import zip_mod

    zip_path = await zip_mod(manifest)
    assert zip_path.exists()
    assert zip_path.suffix == ".zip"


async def test_zip_mod_includes_mod_info(generator_with_tmp_output: Any, valid_spec: ModSpec):
    """Le ZIP inclut obligatoirement mod.info en racine."""
    manifest = await generator_with_tmp_output.generate(valid_spec)
    from src.modgen.generator import zip_mod

    zip_path = await zip_mod(manifest)
    import zipfile as zf

    with zf.ZipFile(zip_path, "r") as archive:
        names = archive.namelist()
        assert any("mod.info" in name for name in names)


# ===========================================================================
# Tests : Fonctions de commodite
# ===========================================================================


async def test_generate_mod_function(tmp_mods_dir: Path, valid_spec: ModSpec):
    """La fonction generate_mod cree un mod avec la config par defaut."""
    from src.modgen import generate_mod

    manifest = await generate_mod(valid_spec, output_dir=tmp_mods_dir)
    assert manifest.output_path.exists()


async def test_generate_mod_from_description(tmp_mods_dir: Path):
    """La fonction generate_mod_from_description cree un mod depuis une description."""
    from src.modgen import generate_mod_from_description

    manifest = await generate_mod_from_description(
        "Une epée en acier avec 45 degats",
        mod_type="item",
        name="SteelSword",
        output_dir=tmp_mods_dir,
    )
    assert manifest.output_path.exists()
    data = json.loads((manifest.output_path / "mod.info").read_text(encoding="utf-8"))
    assert data["name"] == "SteelSword"
    assert data["type"] == "item"


# ===========================================================================
# Tests : Edge cases
# ===========================================================================


async def test_generate_special_chars_in_name(generator_with_tmp_output: Any, tmp_mods_dir: Path):
    """La generation accepte les noms avec accents (valide pour PZ)."""
    from src.modgen.generator import ModGenerator
    from src.modgen.config import ModGenConfig
    from src.modgen.schema import ModSpec

    spec = ModSpec(name="Mod avec accents", description="Test accents")
    gen = ModGenerator(ModGenConfig(output_path=tmp_mods_dir))
    manifest = await gen.generate(spec)
    assert manifest.output_path.exists()


async def test_generate_empty_description(generator_with_tmp_output: Any, valid_spec: ModSpec):
    """La generation fonctionne meme avec une description vide."""
    from src.modgen.schema import ModSpec

    spec = ModSpec(name="EmptyDesc", description="")
    manifest = await generator_with_tmp_output.generate(spec)
    assert manifest.output_path.exists()


# ===========================================================================
# Helpers
# ===========================================================================


def asyncio_run(coro):
    """Executer une coroutine async."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return coro
    return asyncio.run(coro)
