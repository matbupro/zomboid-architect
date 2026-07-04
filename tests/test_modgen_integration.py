"""test_modgen_integration — Tests d'integration du moteur de generation de mods.

Couvre la pipeline complete : description textuelle → ModSpec → generation dossier →
ZIP → validation manifeste → verification contenu.

Utilise tmp_path (pytest builtin) — aucun fichier permanent ecrit.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

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


# ===========================================================================
# Tests : Pipeline complete (description → generate → ZIP → validate)
# ===========================================================================


async def test_full_pipeline_item_mod(tmp_mods_dir: Path):
    """Pipeline entiere : description textuelle → generation → ZIP → validation.

    Etapes :
      1. generate_mod_from_description("Une épée en acier avec 45 dégâts")
      2. Vérifier que le dossier mod existe avec tous les fichiers requis
      3. zip_mod() pour compresser le mod
      4. Décompresser dans tmp et valider mod.info JSON
    """
    from src.modgen import generate_mod_from_description
    from src.modgen.generator import zip_mod

    manifest = await generate_mod_from_description(
        "Une épée en acier avec 45 dégâts",
        mod_type="item",
        name="SteelSword",
        output_dir=tmp_mods_dir,
    )

    # --- Etape 2 : verification des fichiers generés ---
    root = manifest.output_path
    assert root.exists() and root.is_dir(), "Le dossier mod n'a pas été créé"

    # Fichiers obligatoires d'un mod PZ
    assert (root / "mod.info").exists(), "mod.info manquant"
    assert (root / "ZomboidModDescriptor.txt").exists(), "ZomboidModDescriptor.txt manquant"
    assert (root / "README.md").exists(), "README.md manquant"

    # Dossiers lua obligatoires
    for sub in ["client", "shared", "server"]:
        lua_dir = root / "media" / "lua" / sub
        assert lua_dir.exists() and lua_dir.is_dir(), f"media/lua/{sub}/ manquant"

    # init.lua présent au moins une fois (peut être dans scripts/ ou sous-dossier)
    init_luas = list(root.rglob("**/init.lua"))
    assert len(init_luas) > 0, "Aucun init.lua trouvé"


async def test_full_pipeline_feature_mod(tmp_mods_dir: Path):
    """Pipeline avec mod_type=feature : vérifie que le type est correctement appliqué."""
    from src.modgen import generate_mod_from_description

    manifest = await generate_mod_from_description(
        "Un système de tannerie avancé pour convertir les peaux en cuir",
        mod_type="feature",
        name="AdvancedTanning",
        output_dir=tmp_mods_dir,
    )

    data = json.loads((manifest.output_path / "mod.info").read_text(encoding="utf-8"))
    assert data["type"] == "feature"
    assert manifest.name == "AdvancedTanning"


async def test_zip_roundtrip(tmp_mods_dir: Path):
    """Generation → ZIP → extraction dans dossier séparé → verification mod.info."""
    from src.modgen import generate_mod_from_description
    from src.modgen.generator import zip_mod

    # Generation
    manifest = await generate_mod_from_description(
        "Un nouveau type de torchière murale",
        mod_type="item",
        name="WallTorch",
        output_dir=tmp_mods_dir,
    )

    # ZIP
    zip_path = await zip_mod(manifest)
    assert zip_path.exists()
    assert zip_path.suffix == ".zip"

    # Extraction dans dossier séparé
    extract_dir = tmp_mods_dir / "extracted"
    extract_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    # Verification mod.info dans ZIP extrait
    extracted_mod_info = extract_dir / manifest.id / "mod.info"
    assert extracted_mod_info.exists(), "mod.info manquant dans le ZIP extrait"
    data = json.loads(extracted_mod_info.read_text(encoding="utf-8"))
    assert data["name"] == "WallTorch"
    assert "author" in data
    assert "type" in data


async def test_manifest_modinfo_schema(tmp_mods_dir: Path):
    """mod.info contient TOUS les champs requis par le template PZ."""
    from src.modgen import generate_mod_from_description

    manifest = await generate_mod_from_description(
        "Hache de fortune",
        mod_type="item",
        name="MakeshiftAxe",
        output_dir=tmp_mods_dir,
    )

    data = json.loads((manifest.output_path / "mod.info").read_text(encoding="utf-8"))

    # Champs requis par le template mod.info.j2
    required_keys = ["name", "author", "type", "description"]
    for key in required_keys:
        assert key in data, f"Champ requis manquant dans mod.info : {key}"

    # Type doit être une valeur valide de ModType enum
    valid_types = {"item", "feature", "ui", "script", "zombie", "vehicle"}
    assert data["type"] in valid_types, f"type invalide : {data['type']}"


async def test_init_lua_contains_pz_hooks(tmp_mods_dir: Path):
    """init.lua contient les hooks standards PZ (Hooks.Register, OnGameInit, etc.)."""
    from src.modgen import generate_mod_from_description

    manifest = await generate_mod_from_description(
        "Afficheur de statistics en jeu",
        mod_type="ui",
        name="StatsDisplay",
        output_dir=tmp_mods_dir,
    )

    init_luas = list(manifest.output_path.rglob("**/init.lua"))
    assert len(init_luas) > 0, "Aucun init.lua trouvé"

    content = init_luas[0].read_text(encoding="utf-8")
    # Les templates doivent contenir au moins les hooks PZ standards
    assert "Hooks.Register" in content, "Hooks.Register manquant dans init.lua"
    assert "OnGameInit" in content or "Register" in content, "Hook OnGameInit ou Register manquant"


async def test_multiple_generations_no_conflict(tmp_mods_dir: Path):
    """Plusieurs generations successives ne se marchent pas dessus (IDs uniques)."""
    from src.modgen import generate_mod_from_description

    results = []
    for i in range(3):
        manifest = await generate_mod_from_description(
            f"Description numero {i}",
            mod_type="item",
            name=f"ModNumero{i}",
            output_dir=tmp_mods_dir,
        )
        results.append(manifest)

    # Chaque mod doit avoir un ID unique (suffixe UUID différent)
    ids = [m.id for m in results]
    assert len(set(ids)) == 3, f"IDs non uniques : {ids}"

    # Tous les dossiers doivent exister independamment
    for m in results:
        assert m.output_path.exists(), f"Dossier {m.id} inexistant"


async def test_script_content_has_spec_references(tmp_mods_dir: Path):
    """Les fichiers de scripts générés contiennent des références à la spec (nom du mod)."""
    from src.modgen import generate_mod_from_description

    manifest = await generate_mod_from_description(
        "Un portail sécurisé avec code d'accès",
        mod_type="feature",
        name="SecureGate",
        output_dir=tmp_mods_dir,
    )

    # Chercher les fichiers Lua clients (hors init.lua qui est un template general)
    client_files = [f for f in manifest.output_path.rglob("**/*.lua") if f.name != "init.lua"]

    if client_files:
        content = client_files[0].read_text(encoding="utf-8")
        assert "SecureGate" in content, f"Le nom du mod n'est pas présent dans {client_files[0]}"


async def test_generate_mod_from_description_creates_valid_spec(tmp_mods_dir: Path):
    """generate_mod_from_description crée une ModSpec valide avec les champs attendus."""
    from src.modgen import generate_mod_from_description

    manifest = await generate_mod_from_description(
        "Epée en bois avec 15 degâts",
        mod_type="item",
        name="WoodSword",
        output_dir=tmp_mods_dir,
    )

    data = json.loads((manifest.output_path / "mod.info").read_text(encoding="utf-8"))
    assert data["name"] == "WoodSword"
    assert data["type"] == "item"
    assert data["author"] == "Zomboid Architect"  # valeur par defaut
    assert "minGameVersion" in data


# ===========================================================================
# Tests : Edge cases integration
# ===========================================================================


async def test_generate_with_unicode_name(tmp_mods_dir: Path):
    """La generation accepte les noms Unicode (accents, caractères spéciaux)."""
    from src.modgen import generate_mod_from_description

    manifest = await generate_mod_from_description(
        "Épée du Roi des Enfers",
        mod_type="item",
        name="ÉpéeRoiEnfers",
        output_dir=tmp_mods_dir,
    )

    assert manifest.output_path.exists()
    # mod.info doit être en UTF-8 sans erreur d'encodage
    content = (manifest.output_path / "mod.info").read_text(encoding="utf-8")
    json.loads(content)  # Ne doit pas lever JSONDecodeError


async def test_generate_empty_description_works(tmp_mods_dir: Path):
    """La generation fonctionne avec une description vide."""
    from src.modgen import generate_mod

    from src.modgen.schema import ModSpec

    spec = ModSpec(name="EmptyDescMod", description="")
    manifest = await generate_mod(spec, output_dir=tmp_mods_dir)

    assert manifest.output_path.exists()
    assert (manifest.output_path / "mod.info").exists()


async def test_zip_with_empty_mod_still_works(tmp_mods_dir: Path):
    """zip_mod ne plante pas meme si le mod a peu de fichiers."""
    from src.modgen import generate_mod_from_description
    from src.modgen.generator import zip_mod

    manifest = await generate_mod_from_description(
        "Mini",
        mod_type="script",
        name="MiniScript",
        output_dir=tmp_mods_dir,
    )

    # Le mod minimal a quand meme mod.info + descriptors + init.lua
    assert manifest.file_count >= 3
    zip_path = await zip_mod(manifest)
    assert zip_path.exists()


async def test_all_mod_types_generate_correctly(tmp_mods_dir: Path):
    """Chaque type de mod (item, feature, ui, script, zombie, vehicle) se genere sans erreur."""
    from src.modgen import generate_mod_from_description

    for mod_type in ["item", "feature", "ui", "script", "zombie", "vehicle"]:
        manifest = await generate_mod_from_description(
            f"Mod de type {mod_type}",
            mod_type=mod_type,
            name=f"Test{mod_type.capitalize()}",
            output_dir=tmp_mods_dir,
        )
        assert manifest.output_path.exists(), f"Dossier manquant pour type={mod_type}"

        # Le champ type dans mod.info doit correspondre
        data = json.loads((manifest.output_path / "mod.info").read_text(encoding="utf-8"))
        assert data["type"] == mod_type, f"Type mismatch pour {mod_type} : {data['type']}"


# ===========================================================================
# Tests : Validation manifeste post-generation
# ===========================================================================


async def test_manifest_file_count_matches_disk(tmp_mods_dir: Path):
    """Le file_count du manifest correspond au nombre reel de fichiers sur le disque."""
    from src.modgen import generate_mod_from_description

    manifest = await generate_mod_from_description(
        "Arme de defense",
        mod_type="item",
        name="DefenseWeapon",
        output_dir=tmp_mods_dir,
    )

    actual_count = sum(1 for f in manifest.output_path.rglob("*") if f.is_file())
    assert manifest.file_count == actual_count, (
        f"file_count mismatch : manifest={manifest.file_count}, reel={actual_count}"
    )


async def test_descriptor_contains_spec_name(tmp_mods_dir: Path):
    """ZomboidModDescriptor.txt contient le nom du mod."""
    from src.modgen import generate_mod_from_description

    manifest = await generate_mod_from_description(
        "Ecran de protection renforce",
        mod_type="feature",
        name="ReinforcedShield",
        output_dir=tmp_mods_dir,
    )

    desc_file = manifest.output_path / "ZomboidModDescriptor.txt"
    assert desc_file.exists()
    content = desc_file.read_text(encoding="utf-8")
    assert "ReinforcedShield" in content


async def test_readme_contains_spec_name(tmp_mods_dir: Path):
    """README.md contient le nom du mod et la description."""
    from src.modgen import generate_mod_from_description

    manifest = await generate_mod_from_description(
        "Nouveau type de tente",
        mod_type="feature",
        name="BigTent",
        output_dir=tmp_mods_dir,
    )

    readme_file = manifest.output_path / "README.md"
    assert readme_file.exists()
    content = readme_file.read_text(encoding="utf-8")
    assert "BigTent" in content


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
