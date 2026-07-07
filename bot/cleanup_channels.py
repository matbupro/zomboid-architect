"""
cleanup_channels.py — Vide tout le contenu (messages) des canaux du serveur Discord.

ATTENTION : cette action est IRREVERSIBLE. Les messages sont supprimés à jamais.
Toujours lancer --dry-run d'abord pour vérifier le compte.

Usage :
    python -m bot.cleanup_channels --dry-run                # simule et affiche (SAFE)
    python -m bot.cleanup_channels --confirm-all            # purge réelle (IRREVERSIBLE)
"""
from __future__ import annotations

import asyncio
import sys

import discord

from src.governance.logger import get_logger

logger = get_logger("cleanup")


def load_token() -> str:
    """Charge le token depuis .env."""
    import os
    from pathlib import Path

    env_file = Path(__file__).parent.parent / ".env.unified"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                if key == "DISCORD_TOKEN" and value:
                    return value
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN manquant dans .env ou env var.")
        sys.exit(1)
    return token


intents = discord.Intents.default()
intents.guilds = True
intents.messages = True

bot = discord.Client(intents=intents)


@bot.event
async def on_ready():
    print(f"\n{'='*60}")
    print(f"Connecte en tant que : {bot.user.name} (ID: {bot.user.id})")
    guilds_str = [f"{g.name}" for g in bot.guilds]
    print(f"Serveurs ({len(bot.guilds)}) : {', '.join(guilds_str)}")
    print(f"{'='*60}\n")


async def do_cleanup(dry_run: bool):
    """Logique de cleanup — appelée une fois le bot pret."""
    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        logger.error("Aucun serveur trouve.")
        return

    all_text_channels = list(guild.text_channels)
    print(f"\nServeur : {guild.name}")
    print(f"   Canaux textes  : {len(all_text_channels)}\n")

    total_deleted = 0

    for ch in all_text_channels:
        if dry_run:
            msg_count = 0
            async for _ in ch.history(limit=None):
                msg_count += 1
            print(f"   #{ch.name} : ~{msg_count} messages")
        else:
            deleted = 0
            try:
                purged = await ch.purge(limit=None)
                deleted = len(purged)
                logger.info("OK #%s : %d messages supprimes", ch.name, deleted)
            except discord.Forbidden:
                count = 0
                async for msg in ch.history():
                    try:
                        await msg.delete()
                        deleted += 1
                        count += 1
                        if count % 5 == 0:
                            await asyncio.sleep(1.0)
                    except discord.Forbidden:
                        logger.warning("Message %s non supprimable", msg.id)
            total_deleted += deleted
            print(f"   #{ch.name} : {deleted} supprimes")
            await asyncio.sleep(1.0)

    print(f"\n{'='*60}")
    if dry_run:
        print("FIN SIMULATION -- aucun message n'a ete supprime.")
    else:
        print(f"TERMINE -- {total_deleted} messages supprimes sur {len(all_text_channels)} canaux")
    print(f"{'='*60}\n")


async def run(dry_run: bool):
    token = load_token()

    if dry_run:
        logger.warning("="*60)
        logger.warning("MODE SIMULATION -- aucun message ne sera supprime")
        logger.warning("="*60)

    @bot.event
    async def on_connect():
        # Le bot est pret, lance le cleanup puis quitte proprement
        await do_cleanup(dry_run)
        await bot.close()

    # discord.Client : on utilise bot.run(), pas async with
    try:
        await bot.start(token)
    except KeyboardInterrupt:
        print("\nAnnule par l'utilisateur (Ctrl+C).")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Purge tout le contenu des canaux du serveur Discord.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Simule sans supprimer (SAFE)")
    group.add_argument("--confirm-all", action="store_true", help="Confirme la purge reelie (IRREVERSIBLE)")
    args = parser.parse_args()

    if args.confirm_all:
        confirm = input("TU VAS SUPPRIMER TOUT LE CONTENU DE TOUS LES CANAUX.\n   Tape YES pour confirmer : ")
        if confirm.strip().upper() != "YES":
            print("Anule.")
            sys.exit(0)

    asyncio.run(run(args.dry_run))
