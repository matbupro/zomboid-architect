"""
cli — Interface CLI de l'ingestion multi-format Zomboid Knowledge Engine.

Commandes principales :
    --search "query"           Recherche web via DuckDuckGo + crawl des résultats
    --url <url>                Crawl une seule URL (tout le contenu d'une page)
    --crawl <seed_url>         Crawl BFS (follow liens internes, depth=5 par défaut)
    --file <path>              Ingestion d'un fichier unique (auto-détection du format)
    --dir <path>               Ingestion de tout un dossier
    --list-collections         Liste les collections ChromaDB disponibles
    --search-all <query>       Recherche sur TOUTES les collections ChromaDB
    --help                     Affiche cette aide

Exemples :
    # Web search + crawl
    python -m ingestor.cli --search "Project Zomboid wiki guide"

    # Crawl d'un site complet (depth limité)
    python -m ingestor.cli --crawl "https://pzmods.net"

    # Ingestion PDF
    python -m ingestor.cli --file "C:/docs/manual_pz.pdf"

    # Ingestion dossier complet
    python -m ingestor.cli --dir "C:/my_documents/"

    # Recherche dans la base de connaissances
    python -m ingestor.cli --search-all "comment fabriquer un feu de camp"

    # Vérifier les collections disponibles
    python -m ingestor.cli --list-collections
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)

# Windows CMD / PowerShell : forcer UTF-8 sur stdout/stderr (évite charmap encode errors sur emojis)
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")
if hasattr(_sys.stderr, "reconfigure"):
    _sys.stderr.reconfigure(encoding="utf-8")

logger = logging.getLogger("ingestor.cli")


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ingestor",
        description="Zomboid Knowledge Engine — Multi-Modal Ingestor v0.2.0-alpha",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Exemples :
  %(prog)s --search "Project Zomboid modding guide"
  %(prog)s --crawl "https://pzwiki.net"
  %(prog)s --file "C:/docs/pz_manual.pdf"
  %(prog)s --dir "C:/my_docs/"
  %(prog)s --list-collections
  %(prog)s --search-all "comment survivre en B42"
""",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--search", type=str, help="Recherche web + crawl (via DuckDuckGo)")
    group.add_argument("--url", type=str, help="Ingestion d'une seule URL")
    group.add_argument("--crawl", type=str, help="Crawl BFS d'un site depuis une seed URL")
    group.add_argument("--file", type=str, help="Ingestion d'un fichier unique (auto-détection)")
    group.add_argument("--dir", type=str, help="Ingestion d'un dossier complet")
    group.add_argument("--list-collections", action="store_true", help="Liste les collections ChromaDB disponibles")
    group.add_argument("--search-all", type=str, help="Recherche sur TOUTES les collections ChromaDB")

    # Options globales
    parser.add_argument("--max-depth", type=int, default=5, help="Profondeur max de crawl (défaut: 5)")
    parser.add_argument("--max-pages", type=int, default=20, help="Pages max par search/crawl (défaut: 20)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Mode verbeux")

    return parser


# ---------------------------------------------------------------------------
# Handlers des commandes
# ---------------------------------------------------------------------------

async def handle_search(args: argparse.Namespace) -> None:
    """Commande : --search <query>"""
    from .engine import IngestionEngine
    from .config import load_config
    from .search.duckduckgo import search_and_crawl

    config = load_config()
    engine = IngestionEngine(config)

    logger.info("Recherche + crawl web : '%s'", args.search)

    # Phase 1 : recherche DDG + crawl simultané
    start = time.time()
    results = await search_and_crawl(
        args.search,
        max_results=min(args.max_pages, 10),
        crawler=None,  # use default
    )
    elapsed = time.time() - start

    if not results:
        logger.warning("Aucun résultat trouvé pour '%s'", args.search)
        return

    logger.info("Recherche + crawl terminé en %.1fs — %d pages extraites\n", elapsed, len(results))

    for i, r in enumerate(results, 1):
        title = (r.title or "Sans titre")[:60]
        url = (r.url or "")[:80]
        body_len = len(r.body) if r.body else 0
        print(f"\n{'='*70}")
        print(f"#{i} {title}")
        print(f"   URL : {url}")
        print(f"   Contenu : {body_len} chars, ~{body_len // 5} mots")
        print(f"   Description : {r.description[:200]}")

        # Afficher un extrait du contenu
        if r.body:
            preview = r.body[:600].replace("\n", " ").strip()
            if len(r.body) > 600:
                preview += "..."
            print(f"\n   Extrait :\n   {preview}")

    # Stocker dans ChromaDB (auto-accept si stdin pipé / non-terminal, sinon demande confirmation)
    import os as _os
    _auto_accept = not sys.stdin.isatty()  # piped/CI → auto yes
    if _auto_accept:
        store = "y"
    else:
        try:
            store = input("\nIngrérer ces résultats dans ChromaDB ? [y/N] ").strip().lower()
        except EOFError:
            store = "y"  # pipe fermé → auto yes
    if store == "y":
        print(f"\nIngestion de {len(results)} pages dans ChromaDB...")
        # Utiliser les résultats du crawl (pas engine.ingest(query) qui plante)
        from .processors.base import Chunk as BaseChunk
        from .storage.chroma_writer import write_chunks_to_chroma
        all_chunks = []
        for i, r in enumerate(results):
            if r.body:
                all_chunks.append(BaseChunk(text=r.body, index=i, start_offset=0))  # chunk_index=i, start_offset obligatoire
        success = await write_chunks_to_chroma(
            chunks=all_chunks,
            source=args.search,
            content_type="web_search",
            collection="pz_web_pages",
            metadata={"search_query": args.search},
        )
        print(f"ChromaDB : {'OK' if success else 'ÉCHEC'}")
    else:
        logger.info("Stockage ChromaDB ignoré par l'utilisateur.")


async def handle_url(args: argparse.Namespace) -> None:
    """Commande : --url <url>"""
    from .engine import IngestionEngine
    from .config import load_config
    from .storage.chroma_writer import write_chunks_to_chroma

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
    store = input("\nStocker dans ChromaDB ? [y/N] ").strip().lower()
    if store == "y":
        success = await write_chunks_to_chroma(
            chunks=result.chunks,
            source=args.url,
            content_type="web",
            collection="pz_web_pages",
        )
        print(f"ChromaDB : {'OK' if success else 'ÉCHEC'}")


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
    print(f"  Pages visitées : {stats.pages_visited}")
    print(f"  Pages échouées : {stats.pages_failed}")
    print(f"  Liens trouvés : {stats.links_found}")
    print(f"  Liens suivis   : {stats.links_followed}")
    print(f"  Bloqués robots : {stats.links_robots_blocked}")
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
    from .storage.chroma_writer import write_chunks_to_chroma

    file_path = Path(args.file)
    if not file_path.exists():
        logger.error("Fichier non trouvé : %s", args.file)
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
    collection = result.collection or "pz_pdfs"
    try:
        _auto_file = not sys.stdin.isatty()
        if _auto_file:
            store = "y"
        else:
            store = input(f"\nStocker dans ChromaDB ('{collection}') ? [y/N] ").strip().lower()
    except EOFError:
        store = "y"
    if store == "y":
        success = await write_chunks_to_chroma(
            chunks=result.chunks,
            source=str(file_path),
            content_type=content_type,
            collection=collection,
            metadata={"original_file": str(file_path)},
        )
        print(f"ChromaDB : {'OK' if success else 'ÉCHEC'}")


async def handle_dir(args: argparse.Namespace) -> None:
    """Commande : --dir <path>"""
    from pathlib import Path
    from .engine import IngestionEngine
    from .config import load_config

    dir_path = Path(args.dir) if isinstance(args.dir, str) else args.dir
    if not dir_path.is_dir():
        logger.error("Dossier non trouvé : %s", dir_path)
        return

    logger.info("Ingestion dossier : %s", dir_path)
    config = load_config()
    engine = IngestionEngine(config)

    results = await engine.ingest_directory(str(dir_path))

    # Stats globales
    total_files = len(results)
    total_chunks = sum(len(r.chunks) for r in results)
    total_words = sum(r.word_count for r in results)
    failed = 0  # comptés dans quarantine_manager.py
    print(f"\n{'='*70}")
    print(f"Dossier : {dir_path}")
    print(f"  Fichiers traités : {total_files}")
    print(f"  Total chunks     : {total_chunks}")
    print(f"  Total mots       : {total_words}")

    # Stocker dans ChromaDB (optionnel)
    store = input("\nStocker tous les fichiers dans ChromaDB ? [y/N] ").strip().lower()
    if store == "y":
        from .storage.chroma_writer import write_chunks_to_chroma
        for result in results:
            await write_chunks_to_chroma(
                chunks=result.chunks,
                source=result.source,
                content_type=result.content_type or "(auto)",
                collection=result.collection or "pz_pdfs",
                metadata={"directory": str(dir_path)},
            )
        print("ChromaDB : stockage terminé.")


async def handle_list_collections(args: argparse.Namespace) -> None:
    """Commande : --list-collections"""
    from .storage.chroma_writer import ChromaWriter
    writer = ChromaWriter()
    collections = await writer.list_collections()

    print(f"\n{'='*70}")
    print("Collections ChromaDB disponibles :")
    for col in sorted(collections):
        # Essayer de compter les documents dans la collection
        try:
            count = await writer.count_collection(col)
            marker = "  ★ nouveau" if col.startswith("pz_") and col not in [
                "pz_items", "pz_recipes", "pz_mechanics", "pz_lua_api", "pz_java_api"
            ] else ""
            print(f"  • {col} ({count} documents){marker}")
        except Exception:
            print(f"  • {col} (non accessible)")


async def handle_search_all(args: argparse.Namespace) -> None:
    """Commande : --search-all <query>"""
    from .storage.chroma_writer import ChromaWriter

    query = args.search_all
    logger.info("Recherche cross-collection : '%s'", query)

    writer = ChromaWriter()
    results = await writer.cross_collection_search(query, n_results=10)

    if not results:
        logger.warning("Aucun résultat trouvé pour '%s'", query)
        return

    print(f"\n{'='*70}")
    print(f"Recherche cross-collection : '{query}'")
    print(f"{len(results)} résultats trouvés\n")

    for i, r in enumerate(results, 1):
        col = getattr(r, "collection", "unknown")
        rid = getattr(r, "id", "?")
        dist = getattr(r, "distance", "?")
        prose = getattr(r, "prose", "")[:200]

        print(f"{i}. [{col}] {rid} (dist={dist:.3f})")
        if prose:
            print(f"   {prose}")
        print()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def main(args: argparse.Namespace) -> None:
    """Point d'entrée principal."""
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    # Afficher la version
    try:
        import ingestor  # type: ignore[import-not-found]
        print(f"\nZomboid Knowledge Engine — Multi-Modal Ingestor v{ingestor.__version__}\n")
    except ImportError:
        pass

    if args.search:
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


def run() -> None:
    """Fonction principale (appelée par `python -m ingestor.cli`)."""
    parser = build_parser()
    args = parser.parse_args()

    if hasattr(args, 'verbose'):
        pass  # already handled in main()

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("\nAnnulé par l'utilisateur.")
    except Exception as exc:
        logger.exception("Erreur critique : %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    run()
