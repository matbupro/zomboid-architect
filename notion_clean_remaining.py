"""Nettoie les 15 tâches restantes qui n'ont pas été mappées dans le script précédent."""

import sys

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

from notion_client import api

config = api.get_config()
client = api.NotionClient(config)

# Mapping des tâches restantes (non mappées dans le script principal)
REMAINING_MAP = {
    # Phase 10 - tâches terminees
    "ChromaDB : docker compose Up": "P09",   # deployment necessaire mais maintenant fait
    "Ollama : qwen3.6:35b-a3b en ligne": "P12",  # model deja online
    "P0 fix async health checks": "P17",  # correctif mineur fait
    "Corrections : fix send_embed": "P19",  # correctif mineur fait

    # Phase 9 - tâches terminees
    "CLI --file <path> + --dir <path> testes": "P08",  # testing CLI important mais non-critique maintenant

    # Phase 8 - tasks à faire
    "Stockage dans ChromaDB (pz_web_pages)": "P10",  # stockage web pages necessaire

    # Phase 7 - tâches terminees
    "Dépendances installées : pip install": "P15",  # prerequisite fait

    # Phase 6 - tasks à faire
    "Générer automatiquement les patch notes": "P20",  # automatisation bonus pure

    # Phase 4 - tasks à faire
    "Connecter le serveur à l'agent local": "P07",  # connectivité agent necessaire
    "Déclarer outil MCP pz_get_item": "P06",  # MCP lookup déterministe pour items precis
}

items = client.query_items()
priority_col = client._priority_col
title_col = client._title_col

fixed = 0
skipped = 0
for item in items:
    props = item.get("properties", {})

    # Priorité actuelle
    pri_prop = props.get(priority_col, {})
    pri_name = (pri_prop.get("select") or {}).get("name", "") if isinstance(pri_prop, dict) else "?"

    # Nom de la tâche
    name_prop = props.get(title_col, {})
    name_val = ""
    if isinstance(name_prop, dict):
        blocks = name_prop.get("title", [])
        if blocks:
            name_val = blocks[0].get("text", {}).get("content", "")

    # Si la priorité est P1 ou P3 (non mappées), on assigne
    if pri_name in ("P1", "P3"):
        mapped = REMAINING_MAP.get(name_val)
        if mapped:
            try:
                client.update_item(
                    item["id"],
                    extra_props={priority_col: {"select": {"name": mapped}}},
                )
                print(f"  {name_val[:70]} -> {mapped}")
                fixed += 1
            except Exception as e:
                print(f"  ERREUR sur '{name_val[:40]}': {e}")
        else:
            skipped += 1
            print(f"  SKIP (non trouve dans REMAINING_MAP): {name_val[:70]}")

    # Nettoyage des valeurs vides aussi
    elif pri_name == "":
        # Donnee sans priorité assignee - par defaut P10 (moyen)
        try:
            client.update_item(
                item["id"],
                extra_props={priority_col: {"select": {"name": "P10"}}},
            )
            print(f"  {name_val[:70]} -> P10 (vide)")
            fixed += 1
        except Exception as e:
            print(f"  ERREUR sur '{name_val[:40]}': {e}")

print(f"\nFixes: {fixed} | Skipped (non trouve): {skipped}")

# Verification finale
items2 = client.query_items()
pri_counts = {}
for item in items2:
    pri_prop = item.get("properties", {}).get(priority_col, {})
    pri_name = (pri_prop.get("select") or {}).get("name", "") if isinstance(pri_prop, dict) else "?"
    pri_counts[pri_name] = pri_counts.get(pri_name, 0) + 1

print(f"\n{'='*60}")
print("Distribution finale P01-P20 :")
for k in sorted(k for k in pri_counts):
    bar = "█" * min(pri_counts[k], 40)
    print(f"  {k:4s} | {bar} ({pri_counts[k]})")

client.close()
