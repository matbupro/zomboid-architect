"""__main__ — CLI entry point pour src.modgen.

Commandes :
    python -m src.modgen generate "description" --name NomMod [--type item]
    python -m src.modgen list-templates
    python -m src.modgen validate /chemin/vers/mod/

Exemples :
    # Generer un mod a partir d'une description
    python -m src.modgen generate "Une epée en acier avec 45 degats" \\
        --name "CustomSword" --type item --output ../mods/

    # Generer avec des features detaillees (JSON)
    python -m src.modgen generate "Arme furtive silencieuse" \\
        --name "SilentBow" --type item \\
        --features '[{"name": "silent_shot", "type": "add_feature"}]'

    # Lister les templates disponibles
    python -m src.modgen list-templates

    # Valider un mod existeant
    python -m src.modgen validate /chemin/vers/MyMod/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ajouter le project root au sys.path pour les imports relatifs
_PROJECT_ROOT = Path(__file__).parent.parent  # f:/.../Zomboid_Architect
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _cmd_generate(args: argparse.Namespace) -> None:
    """Handler de la sous-commande generate."""
    from src.modgen import ModGenerator, ModGenConfig, ModSpec, ModType

    # Resolution du type
    try:
        mod_type = ModType(args.type)
    except ValueError:
        available = [t.value for t in ModType]
        print(f"Erreur: Type '{args.type}' invalide. Types accepts : {available}", file=sys.stderr)
        sys.exit(1)

    # Parsing des features (JSON string → list)
    features = []
    if args.features:
        try:
            features = json.loads(args.features)
        except json.JSONDecodeError as exc:
            print(f"Erreur: features JSON invalide : {exc}", file=sys.stderr)
            sys.exit(1)

    # Tags (CSV → list)
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []

    # Configuration
    output_dir = Path(args.output).resolve() if args.output else None
    config = ModGenConfig(output_path=output_dir or Path("mods"))

    spec = ModSpec(
        name=args.name,
        description=args.description,
        author=args.author,
        mod_type=mod_type,
        tags=tags,
        features=features if features or args.no_llm_fill else None,
        client_scripts=["init.lua"] if not args.no_llm_fill else [],
    )

    # Generation
    generator = ModGenerator(config)
    manifest = asyncio.run(generator.generate(spec))

    print(f"Mod genere avec succes !")
    print(f"  ID   : {manifest.id}")
    print(f"  Nom  : {manifest.name}")
    print(f"  Path : {manifest.output_path}")
    print(f"  Fichiers ecrits : {manifest.file_count}")
    print()
    print("Dossier cree :")
    for root, dirs, files in sorted(manifest.mod_root.walk(top_down=True)):
        level = root.relative_to(manifest.mod_root).parts.__len__()
        indent = "  " * level
        spacer = indent + ("  " if level > 0 else "")
        print(f"{indent}{manifest.mod_root.name}/")
        for f in sorted(files):
            print(f"{spacer}[+] {f}")  # ASCII-safe tree display (Windows CP1252 compatible)


def _cmd_list_templates(_args: argparse.Namespace) -> None:
    """Handler de la sous-commande list-templates."""
    from src.modgen import ModGenConfig, ModGenerator

    config = ModGenConfig()
    generator = ModGenerator(config)
    templates = generator.list_templates()

    print("Templates disponibles :")
    for t in sorted(templates):
        path = config.templates_path / t
        size = path.stat().st_size if path.exists() else 0
        print(f"  {t:<45} ({size:>6} bytes)")


def _cmd_validate(args: argparse.Namespace) -> None:
    """Handler de la sous-commande validate."""
    mod_path = Path(args.path)
    errors = []

    if not mod_path.exists():
        print(f"Erreur : le dossier '{mod_path}' n'existe pas.", file=sys.stderr)
        sys.exit(1)

    # Verifier mod.info
    mod_info_path = mod_path / "mod.info"
    if not mod_info_path.exists():
        errors.append("mod.info manquant — fichier manifest requis")
    else:
        try:
            import json
            data = json.loads(mod_info_path.read_text(encoding="utf-8"))
            required_fields = {"name", "author"}
            for field_name in required_fields:
                if field_name not in data:
                    errors.append(f"mod.info manque le champ '{field_name}'")

            print(f"mod.info : OK — nom='{data.get('name', '?')}', auteur='{data.get('author', '?')}'")
        except json.JSONDecodeError as exc:
            errors.append(f"mod.info JSON invalide : {exc}")

    # Verifier scripts lua
    lua_path = mod_path / "media" / "lua"
    if not lua_path.exists():
        errors.append("media/lua/ manquant — dossier de scripts requis")

    # Verifier init.lua
    init_lua_candidates = list(lua_path.rglob("init.lua")) if lua_path.exists() else []
    if not init_lua_candidates:
        errors.append("init.lua manquant dans media/lua/ — point d'entree requis")
    else:
        print(f"init.lua trouve : {init_lua_candidates[0].relative_to(mod_path)}")

    # Resultat global
    if errors:
        print("\nErreurs de validation :")
        for e in errors:
            print(f"  [FAIL] {e}")
        sys.exit(1)
    else:
        print("\nValidation reussie ! Le mod est structurellement valide.")


def build_parser() -> argparse.ArgumentParser:
    """Construit et retourne le parser CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m src.modgen",
        description="Generator de mods Project Zomboid — Zomboid_Architect",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0-alpha")

    subparsers = parser.add_subparsers(dest="command", help="Commande a executer")

    # --- generate ---
    gen_parser = subparsers.add_parser("generate", help="Generer un mod a partir d'une description")
    gen_parser.add_argument("description", help="Description haute-niveau du mod")
    gen_parser.add_argument("--name", required=True, help="Nom du mod (obligatoire)")
    gen_parser.add_argument(
        "--type", default="item",
        choices=["item", "feature", "ui", "script", "zombie", "vehicle"],
        help="Type de mod (defaut: item)",
    )
    gen_parser.add_argument("--author", default="Zomboid Architect", help="Auteur du mod")
    gen_parser.add_argument("--description-desc", dest="description_long", default="", help="Description detaillee (optionnel, defaut=argument positionnel)")
    gen_parser.add_argument("--output", "-o", help="Repertoire de sortie (defaut: mods/)")
    gen_parser.add_argument("--tags", default="", help="Tags Steam Workshop separes par virgule")
    gen_parser.add_argument(
        "--features", default=None,
        help='Features detaillees en JSON (ex: \'[{"name":"silent_shot","type":"add_feature"}]\')',
    )
    gen_parser.add_argument("--no-llm-fill", action="store_true", help="Ne pas utiliser LLM pour remplir les features")

    # --- list-templates ---
    subparsers.add_parser("list-templates", help="Lister les templates disponibles")

    # --- validate ---
    val_parser = subparsers.add_parser("validate", help="Valider la structure d'un mod existant")
    val_parser.add_argument("path", help="Chemin vers le dossier du mod a valider")

    return parser


def main() -> None:
    """Point d'entrée principal de la CLI."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Mapper les sous-commandes aux handlers
    handlers = {
        "generate": _cmd_generate,
        "list-templates": _cmd_list_templates,
        "validate": _cmd_validate,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
