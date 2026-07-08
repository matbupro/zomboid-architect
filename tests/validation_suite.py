import sys
import os
from src.mcp_tools import pz_get_item, pz_search_all, pz_get_guide

# S'assurer que le répertoire racine est inclus dans le chemin pour charger 'src'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def run_test(name: str, result: dict) -> None:
    print(f"--- Test {name} ---")
    if "error" in result:
        print(f"[FAIL] ÉCHEC : {result['error']}")
    else:
        print(f"[OK] SUCCÈS !")
        print(f"Détails : {result}")
    print("-" * 30)

def main():
    # Test 1: Recherche thématique (Panique/Armes)
    # On vérifie que le système trouve des informations sur la panice et les armes.
    res1 = pz_search_all(query="Comment gérer la panique lors d'un combat avec des armes à feu?")
    run_test("Recherche Thématique (Panice/Armes)", res1)

    # Test 2: Accès aux ressources spécifiques (UI Diégétique)
    # On vérifie que le guide de débogage Lua est accessible.
    res2 = pz_get_guide("lua_debug_guide")
    run_test("Accès Resource UI", res2)

    # Test 3: Récupération déterministe (Base.Axe)
    # On vérifie qu'on obtient les stats exactes sans "fuzzy matching".
    res3 = pz_get_item(item_id="Base.Axe")
    run_test("Récupération Déterministe", res3)

if __name__ == "__main__":
    main()
