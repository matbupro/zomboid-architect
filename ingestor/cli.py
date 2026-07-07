"""
cli â€” Interface CLI de l'ingestion multi-format Zomboid Knowledge Engine.

Commandes principales :
    --search "query"           Recherche web via DuckDuckGo + crawl des rÃ©sultats
    --url <url>                Crawl une seule URL (tout le contenu d'une page)
    --crawl <seed_url>         Crawl BFS (follow liens internes, depth=5 par dÃ©faut)
    --file <path>              Ingestion d'un fichier unique (auto-dÃ©tection du format)
    --dir <path>               Ingestion de tout un dossier
    --list-collections         Liste les collections storage disponibles
    --search-all <query>       Recherche sur TOUTES les collections storage

Commandes Steam & Mods :
    --steam-scan               Scanner Steam + decouvrir PZ install
    --steamcmd-download-game   Telecharger PZ via steamcmd (anonymous)
    --steamcmd-install-mod ID  Installer un mod workshop via steamcmd
    --workshop-scan            Scanner les mods installes dans le Steam Workshop
    --mod-ingest <dir>         Ingerer tous les mods d’un repertoire → storage vectoriel

Exemples :
    # Web search + crawl
    python -m ingestor.cli --search "Project Zomboid wiki guide"

    # Crawl d'un site complet (depth limitÃ©)
    python -m ingestor.cli --crawl "https://pzmods.net"

    # Ingestion PDF / .pbo
    python -m ingestor.cli --file "C:/docs/manual_pz.pdf"
    python -m ingestor.cli --file "C:/Mods/my_mod.pbo"

    # Steam & Workshop
    python -m ingestor.cli --steam-scan
    python -m ingestor.cli --workshop-scan
    python -m ingestor.cli --mod-ingest "C:/Steam/steamapps/workshop/content/1042170"

    # Recherche dans la base de connaissances
    python -m ingestor.cli --search-all "comment fabriquer un feu de camp"

    # VÃ©rifier les collections disponibles
    python -m ingestor.cli --list-collections
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import logging
import sys
import time

import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")
if hasattr(_sys.stderr, "reconfigure"):
    _sys.stderr.reconfigure(encoding="utf-8")

from src.governance.logger import get_logger

logger = get_logger("ingestor.cli")


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ingestor",
        description="Zomboid Knowledge Engine â€” Multi-Modal Ingestor v0.2.0-alpha",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Exemples :
  %(prog)s --search "Project Zomboid modding guide"
  %(prog)s --crawl "https://pzwiki.net"
  %(prog)s --file "C:/docs/pz_manual.pdf"
  %(prog)s --dir "C:/my_docs/"
  %(prog)s --list-collections
  %(prog)s --search-all "comment survivre en B42"
  %(prog)s --report        Rapport qualite (recall, collections, quarantine)
""",
    )

    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--search", type=str, help="Recherche web + crawl (DDG en priorite, Brave fallback)")
    group.add_argument("--url", type=str, help="Ingestion d'une seule URL")
    group.add_argument("--crawl", type=str, help="Crawl BFS d'un site depuis une seed URL")
    group.add_argument("--file", type=str, help="Ingestion d'un fichier unique (auto-dÃ©tection)")
    group.add_argument("--dir", type=str, help="Ingestion d'un dossier complet")
    group.add_argument("--list-collections", action="store_true", help="Liste les collections storage disponibles")
    group.add_argument("--search-all", type=str, help="Recherche sur TOUTES les collections storage")
    group.add_argument("--report", action="store_true", help="Rapport de qualite (recall golden set, collections, quarantaine)")

    # Options globales

    # Options globales
    parser.add_argument("--max-depth", type=int, default=5, help="Profondeur max de crawl (defaut: 5)")
    parser.add_argument("--max-pages", type=int, default=20, help="Pages max par search/args (defaut: 20)")
    parser.add_argument("--engine", choices=["auto", "ddg", "brave"], default="auto", help="Moteur de recherche : auto = DDG â†’ Brave fallback")
    parser.add_argument("--verbose", "-v", action="store_true", help="Mode verbeux")
    parser.add_argument("--collection", type=str, help="Collection storage cible (ex: pz_guides)")

    # Steam & Mod commands (groupse a part)
    steam_group = parser.add_mutually_exclusive_group()
    steam_group.add_argument("--steam-scan", action="store_true", help="Scanner Steam pour Project Zomboid (registry + bibliotheques)")
    steam_group.add_argument("--steamcmd-download-game", type=str, metavar="DIR", help="Telecharger PZ via steamcmd")
    steam_group.add_argument("--steamcmd-install-mod", type=int, metavar="MOD_ID", help="Installer un mod workshop via steamcmd")
    steam_group.add_argument("--workshop-scan", action="store_true", help="Scanner les mods installÃ©s dans le Steam Workshop")
    steam_group.add_argument("--mod-ingest", type=str, metavar="DIR", help="Ingerer tous les mods d'un repertoire (ex: workshop/content/1042170)")

    return parser


# ---------------------------------------------------------------------------
# Handlers des commandes
# ---------------------------------------------------------------------------

async def handle_search(args: argparse.Namespace) -> None:
    """Commande : --search <query> + fallback Brave."""
    import os as _os

    from .engine import IngestionEngine
    from .config import load_config
    from .search.duckduckgo import search as _ddg_search
    from .search.brave import search as _brave_search, check_brave_installed as _check_brave

    config = load_config()
    engine_obj = IngestionEngine(config)

    logger.info("Recherche web : '%s' (engine=%s)", args.search, args.engine)

    # Resolution clef Brave depuis env si pas explicitement passe
    brave_key = _os.getenv("BRAVE_API_KEY")

    results: list | None = None
    source = ""

    # 1. Forced Brave ou DDG impossible â†’ directement Brave
    if args.engine == "brave":
        logger.info("Brave Search force (engine=%s)", args.engine)
        results = await _try_brave(_brave_search, args.search, min(args.max_pages, 10), brave_key)
        source = "brave" if results else None

    # 2. DDG en priorite (auto ou ddg force)
    if not results and args.engine != "brave":
        logger.info("Essai DuckDuckGo pour '%s'...", args.search)
        try:
            from .search.duckduckgo import search_and_crawl

            raw_results = await _ddg_search(args.search, max_results=min(args.max_pages, 10))
            if raw_results:
                results = await search_and_crawl(
                    args.search,
                    max_results=min(args.max_pages, 10),
                    crawler=None,
                )
                source = "ddg"
            else:
                logger.info("DDG â†’ 0 resultats, tentative Brave fallback")
        except Exception as exc:
            logger.warning("DDG echoue (%s), tentative Brave fallback", exc)

    # 3. Fallback Brave si DDG vide/echec + Brave key dispo
    if not results and brave_key and _check_brave(brave_key):
        logger.info("Brave Search fallback pour '%s'...", args.search)
        results = await _try_brave(_brave_search, args.search, min(args.max_pages, 10), brave_key)
        source = "brave"

    if not results:
        logger.warning("Aucun rÃ©sultat trouvÃ© pour '%s'", args.search)
        return

    logger.info("Source : %s â€” %d pages extraites", source, len(results))

    for i, r in enumerate(results, 1):
        title = (r.title or "Sans titre")[:60]
        url = (r.url or "")[:80]
        body_len = len(r.body) if r.body else 0
        print(f"\n{'='*70}")
        print(f"#{i} {title}")
        print(f"   URL : {url}")
        print(f"   Source : {source}")
        print(f"   Contenu : {body_len} chars, ~{body_len // 5} mots")
        print(f"   Description : {r.description[:200]}")

        # Afficher un extrait du contenu
        if r.body:
            preview = r.body[:600].replace("\n", " ").strip()
            if len(r.body) > 600:
                preview += "..."
            print(f"\n   Extrait :\n   {preview}")

    # Stocker dans le storage vectoriel (auto-accept si stdin pipÃ© / non-terminal, sinon demande confirmation)
    _auto_accept = not sys.stdin.isatty()  # piped/CI â†’ auto yes
    if _auto_accept:
        store = "y"
    else:
        try:
            store = input("\nIngrÃ©rer ces rÃ©sultats dans le storage vectoriel ? [y/N] ").strip().lower()
        except EOFError:
            store = "y"  # pipe fermÃ© â†’ auto yes
    if store == "y":
        print(f"\nIngestion de {len(results)} pages dans le storage vectoriel...")
        from .processors.base import Chunk as BaseChunk
        from .storage.storage_writer import write_chunks_to_storage

        all_chunks = []
        for i, r in enumerate(results):
            if r.body:
                all_chunks.append(BaseChunk(text=r.body, index=i, start_offset=0))  # chunk_index=i, start_offset obligatoire
        success = await write_chunks_to_storage(
            chunks=all_chunks,
            source=args.search,
            content_type="web_search",
            collection="pz_web_pages",
            metadata={"search_query": args.search, "search_engine": source},
        )
        print(f"Storage   : {'OK' if success else 'Ã‰CHEC'}")
    else:
        logger.info("Stockage ignore par l'utilisateur.")


async def _try_brave(brave_fn, query: str, max_results: int, api_key: str | None) -> list | None:
    """Essayer Brave Search. Retourne liste ou None."""
    try:
        res = await brave_fn(query, max_results=min(max_results, 50), api_key=api_key)
        return res if res else None
    except Exception as exc:
        logger.warning("Brave Search Ã©chouÃ© : %s", exc)
        return None


async def handle_url(args: argparse.Namespace) -> None:
    """Commande : --url <url>"""
    from .engine import IngestionEngine
    from .config import load_config
    from .storage.storage_writer import write_chunks_to_storage

    config = load_config()
    engine = IngestionEngine(config)

    logger.info("Ingestion URL : %s", args.url)
    result = await engine.ingest(args.url, collection="pz_web_pages")

    print(f"\n{'='*70}")
    print(f"URL : {args.url}")
    print(f"Chunks : {len(result.chunks)}")
    print(f"Mots : {result.word_count}")
    print(f"Type : {result.content_type or '(inconnu)'}")
    print(f"Hash : {result.file_hash[:16]}...")

    if result.chunks:
        print(f"\nPremier chunk :\n{result.chunks[0].text[:500].replace(chr(10), ' ')}")

    # Store
    store = input("\nStocker dans le storage vectoriel ? [y/N] ").strip().lower()
    if store == "y":
        success = await write_chunks_to_storage(
            chunks=result.chunks,
            source=args.url,
            content_type="web",
            collection="pz_web_pages",
        )
        print(f"Storage   : {'OK' if success else 'Ã‰CHEC'}")


async def handle_crawl(args: argparse.Namespace) -> None:
    """Commande : --crawl <seed_url>"""
    from .processors.web import WebCrawler, CrawlStats

    logger.info("Crawl BFS : %s (depth=%d, max_pages=%d)", args.crawl, args.max_depth, args.max_pages)

    crawler = WebCrawler()
    pages, stats = await crawler.crawl(
        args.crawl,
        max_depth=args.max_depth,
        max_pages=args.max_pages,
    )

    print(f"\n{'='*70}")
    print(f"Crawl BFS : {args.crawl}")
    print(f"  Pages visitÃ©es : {stats.pages_visited}")
    print(f"  Pages Ã©chouÃ©es : {stats.pages_failed}")
    print(f"  Liens trouvÃ©s : {stats.links_found}")
    print(f"  Liens suivis   : {stats.links_followed}")
    print(f"  BloquÃ©s robots : {stats.links_robots_blocked}")
    print(f"  Temps total     : {stats.download_time_s:.1f}s")

    for i, page in enumerate(pages[:3], 1):
        title = (page.get("title", "Sans titre") or "")[:60]
        content = page.get("content", "")
        print(f"\nPage #{i} (depth={page.get('depth', '?')}): {title}")
        if content:
            preview = content[:400].replace("\n", " ").strip()
            if len(content) > 400:
                preview += "..."
            print(f"  {preview}")

    if len(pages) > 3:
        print(f"\n... et {len(pages) - 3} autres pages.")


async def handle_file(args: argparse.Namespace) -> None:
    """Commande : --file <path>"""
    from pathlib import Path
    from .engine import IngestionEngine, detect_type
    from .config import load_config
    from .storage.storage_writer import write_chunks_to_storage

    file_path = Path(args.file)
    if not file_path.exists():
        logger.error("Fichier non trouvÃ© : %s", args.file)
        return

    content_type, processor_key = detect_type(file_path)
    logger.info("Ingestion fichier : %s (type=%s, processeur=%s)", file_path.name, content_type, processor_key)

    config = load_config()
    engine = IngestionEngine(config)
    result = await engine.ingest(str(file_path))

    print(f"\n{'='*70}")
    print(f"Fichier : {file_path.name}")
    print(f"  Taille : {(file_path.stat().st_size / 1024):.1f} Ko")
    print(f"  Type   : {content_type}")
    print(f"  Processeur : {processor_key}")
    print(f"  Chunks : {len(result.chunks)}")
    print(f"  Mots   : {result.word_count}")
    print(f"  Hash   : {result.file_hash[:16]}...")

    if result.chunks:
        preview = result.chunks[0].text[:400].replace("\n", " ")
        print(f"\n  Extrait :\n    {preview}")

    # Store
    collection = args.collection or result.collection or "pz_pdfs"
    try:
        _auto_file = not sys.stdin.isatty()
        if _auto_file:
            store = "y"
        else:
            store = input(f"\nStocker dans le storage vectoriel ('{collection}') ? [y/N] ").strip().lower()
    except EOFError:
        store = "y"
    if store == "y":
        success = await write_chunks_to_storage(
            chunks=result.chunks,
            source=str(file_path),
            content_type=content_type,
            collection=collection,
            metadata={"original_file": str(file_path)},
        )
        print(f"Storage   : {'OK' if success else 'Ã‰CHEC'}")


async def handle_dir(args: argparse.Namespace) -> None:
    """Commande : --dir <path>"""
    from pathlib import Path
    from .engine import IngestionEngine
    from .config import load_config

    dir_path = Path(args.dir) if isinstance(args.dir, str) else args.dir
    if not dir_path.is_dir():
        logger.error("Dossier non trouvÃ© : %s", dir_path)
        return

    logger.info("Ingestion dossier : %s", dir_path)
    config = load_config()
    engine = IngestionEngine(config)

    results = await engine.ingest_directory(str(dir_path))

    # Stats globales
    total_files = len(results)
    total_chunks = sum(len(r.chunks) for r in results)
    total_words = sum(r.word_count for r in results)
    failed = 0  # comptÃ©s dans quarantine_manager.py
    print(f"\n{'='*70}")
    print(f"Dossier : {dir_path}")
    print(f"  Fichiers traitÃ©s : {total_files}")
    print(f"  Total chunks     : {total_chunks}")
    print(f"  Total mots       : {total_words}")

    # Stocker dans le storage vectoriel (optionnel) â€” auto-accept si stdin non-TTY
    _auto_dir = not sys.stdin.isatty()
    if _auto_dir:
        store = 'y'
    else:
        try:
            store = input('\nStocker tous les fichiers dans le storage vectoriel ? [y/N] ').strip().lower()
        except EOFError:
            store = "y"
    if store == "y":
        from .storage.storage_writer import write_chunks_to_storage
        for result in results:
            await write_chunks_to_storage(
                chunks=result.chunks,
                source=result.source,
                content_type=result.content_type or "(auto)",
                collection=args.collection or result.collection or "pz_pdfs",
                metadata={"directory": str(dir_path)},
            )
        print("Storage : stockage terminÃ©.")


async def handle_list_collections(args: argparse.Namespace) -> None:
    """Commande : --list-collections"""
    from .storage.storage_writer import StorageWriter
    writer = StorageWriter()
    collections = await writer.list_collections()

    print(f"\n{'='*70}")
    print("Collections Storage disponibles :")
    for col in sorted(collections):
        # Essayer de compter les documents dans la collection
        try:
            count = await writer.count_collection(col)
            marker = "  â˜… nouveau" if col.startswith("pz_") and col not in [
                "pz_items", "pz_recipes", "pz_mechanics", "pz_lua_api", "pz_java_api"
            ] else ""
            print(f"  â€¢ {col} ({count} documents){marker}")
        except Exception:
            print(f"  â€¢ {col} (non accessible)")


async def handle_search_all(args: argparse.Namespace) -> None:
    """Commande : --search-all <query>"""
    from .storage.storage_writer import StorageWriter

    query = args.search_all
    logger.info("Recherche cross-collection : '%s'", query)

    writer = StorageWriter()
    results = await writer.cross_collection_search(query, n_results=10)

    if not results:
        logger.warning("Aucun rÃ©sultat trouvÃ© pour '%s'", query)
        return

    print(f"\n{'='*70}")
    print(f"Recherche cross-collection : '{query}'")
    print(f"{len(results)} rÃ©sultats trouvÃ©s\n")

    for i, r in enumerate(results, 1):
        col = getattr(r, "collection", "unknown")
        rid = getattr(r, "id", "?")
        dist = getattr(r, "distance", None)
        prose = getattr(r, "prose", "")[:200]

        dist_str = f"{dist:.3f}" if isinstance(dist, (int, float)) else str(dist or "?")
        print(f"{i}. [{col}] {rid} (dist={dist_str})")
        if prose:
            print(f"   {prose}")
        print()


# ---------------------------------------------------------------------------
# Golden report handler (sync, no async needed)
# ---------------------------------------------------------------------------

def handle_report() -> None:
    """Commande : --report â€” genere le rapport qualite."""
    from .generate_report import main as gen_report_main

    gen_report_main(output_json=True, output_md=True)


# ---------------------------------------------------------------------------
# Steam & Mod handlers
# ---------------------------------------------------------------------------

async def handle_steam_scan(args: argparse.Namespace) -> None:
    """Commande : --steam-scan"""
    from .steam.path_discovery import discover_game_path, get_steamcmd_path

    logger.info("Scan Steam...")
    game_paths = discover_game_path()

    print(f"\n{'='*70}")
    print("=== Scan Steam ===")
    print(f"  Repertoire Steam     : {game_paths.steam_install or 'Non trouve'}")
    print(f"  Bibliotheques        : {len(game_paths.library_paths) if game_paths.library_paths else 0}")
    for idx, lp in enumerate(game_paths.library_paths or [], 1):
        status = "OK" if lp.exists() else "MISSING"
        print(f"    [{idx}] {lp} ({status})")
    print(f"  Project Zomboid      : {game_paths.game_path or 'Non trouve'}")
    print(f"  Workshop content     : {game_paths.workshop_content_root or 'Non trouve'}")
    print(f"  Decouverte valide    : {'OUI' if game_paths.discovered else 'NON'}")

    # steamcmd detection
    sc_cmd = get_steamcmd_path(game_paths.steam_install)
    print(f"\n=== SteamCMD ===")
    print(f"  Executable           : {sc_cmd or 'Non trouve'}")


async def handle_steamcmd_download(args: argparse.Namespace) -> None:
    """Commande : --steamcmd-download-game DIR"""
    from .steam.steamcmd_client import SteamCMDClient
    from .steam.path_discovery import find_steam_install_path

    logger.info("Telechargement PZ via steamcmd...")
    client = SteamCMDClient()

    if client.steamcmd_exe is None:
        logger.error("steamcmd.exe non trouve. Installer steamcmd standalone.")
        return

    target_dir = Path(args.steamcmd_download_game) if args.steamcmd_download_game else find_steam_install_path() / "steamapps" / "common"
    result = await client.download_game(target_dir, validate=True)

    print(f"\n{'='*70}")
    print("=== SteamCMD Download ===")
    print(f"  Succes               : {result.success}")
    print(f"  Code sortie          : {result.exit_code}")
    print(f"  Output (dernieres lignes):")
    for line in result.lines[-10:]:
        print(f"    {line}")


async def handle_steamcmd_install_mod(args: argparse.Namespace) -> None:
    """Commande : --steamcmd-install-mod MOD_ID"""
    from .steam.steamcmd_client import SteamCMDClient

    logger.info("Installation mod workshop #%d via steamcmd...", args.steamcmd_install_mod)
    client = SteamCMDClient()

    if client.steamcmd_exe is None:
        logger.error("steamcmd.exe non trouve.")
        return

    result = await client.install_workshop_item(args.steamcmd_install_mod)

    print(f"\n{'='*70}")
    print(f"=== Installation Mod #{args.steamcmd_install_mod} ===")
    print(f"  Succes               : {result.success}")
    print(f"  Code sortie          : {result.exit_code}")
    for line in result.lines[-10:]:
        print(f"    {line}")


async def handle_workshop_scan(args: argparse.Namespace) -> None:
    """Commande : --workshop-scan"""
    from pathlib import Path

    from .steam.path_discovery import discover_game_path
    from .steam.workshop_scanner import WorkshopScanner

    game_paths = discover_game_path()

    # Try to find workshop content root
    content_root = None
    if game_paths.workshop_content_root:
        content_root = game_paths.workshop_content_root
    else:
        # Manual path or current directory
        content_root = Path("steamapps/workshop/content/1042170")
        if not content_root.exists():
            logger.error("Root Workshop non trouve. Utiliser le chemin exact:")
            print(f"\n  Utilisation : python -m ingestor.cli --workshop-scan --file \"C:/Steam/steamapps/workshop/content/1042170\"")
            return

    scanner = WorkshopScanner(content_root)
    mods = await scanner.scan()

    print(f"\n{'='*70}")
    print(f"=== Mods Workshop ({len(mods)} decouverts) ===")
    for mod in mods[:50]:  # max 50 pour l'affichage
        author_str = f" par {mod.author}" if mod.author else ""
        desc_preview = (mod.description[:80] + "...") if mod.description else "Aucune description"
        print(f"  #{mod.mod_id:<10} {mod.name or 'Sans titre':<40}{author_str}")
        print(f"         {desc_preview} ({mod.file_count} fichiers)")

    if len(mods) > 50:
        print(f"\n... et {len(mods) - 50} autres mods (affichages limites a 50).")


async def handle_mod_ingest(args: argparse.Namespace) -> None:
    """Commande : --mod-ingest DIR"""
    from pathlib import Path
    from .steam.mod_ingester import ingest_mods_from_directory
    from .config import load_config

    mod_dir = Path(args.mod_ingest)
    if not mod_dir.is_dir():
        logger.error("Repertoire de mods inexistant: %s", mod_dir)
        return

    logger.info("Ingestion des mods depuis : %s", mod_dir)
    config = load_config()
    results = await ingest_mods_from_directory(mod_dir, config=config)

    print(f"\n{'='*70}")
    print(f"=== Ingestion Mods ({len(results)} mods traites) ===")
    total_chunks = 0
    successes = 0
    for r in results:
        status = f"{r.chunks_written} chunks" if r.success else f"ERREUR: {r.errors}"
        print(f"  Mod #{r.mod_id}: {status}")
        total_chunks += r.chunks_written
        if r.success:
            successes += 1

    print(f"\n  Total : {successes}/{len(results)} succes, {total_chunks} chunks ecrits")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def main(args: argparse.Namespace) -> None:
    """Point d'entrÃ©e principal."""
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    # Afficher la version
    try:
        import ingestor  # type: ignore[import-not-found]
        print(f"\nZomboid Knowledge Engine â€” Multi-Modal Ingestor v{ingestor.__version__}\n")
    except ImportError:
        pass

    # Steam & Mod commands (prioritaires)
    if args.steam_scan:
        await handle_steam_scan(args)
    elif args.steamcmd_download_game is not None:
        await handle_steamcmd_download(args)
    elif args.steamcmd_install_mod is not None:
        await handle_steamcmd_install_mod(args)
    elif args.workshop_scan:
        await handle_workshop_scan(args)
    elif args.mod_ingest is not None:
        await handle_mod_ingest(args)
    # Standard commands
    elif args.search:
        await handle_search(args)
    elif args.url:
        await handle_url(args)
    elif args.crawl:
        await handle_crawl(args)
    elif args.file:
        await handle_file(args)
    elif args.dir:
        await handle_dir(args)
    elif args.list_collections:
        await handle_list_collections(args)
    elif args.search_all:
        await handle_search_all(args)
    elif args.report:
        handle_report()


def run() -> None:
    """Fonction principale (appelÃ©e par `python -m ingestor.cli`)."""
    parser = build_parser()
    args = parser.parse_args()

    if hasattr(args, 'verbose'):
        pass  # already handled in main()

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("\nAnnulÃ© par l'utilisateur.")
    except Exception as exc:
        logger.exception("Erreur critique : %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    run()

