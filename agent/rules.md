# Règles & Principes Directeurs du Projet

## 12 Commandements (Roadmap §1)

1. **Zéro hallucination numérique** — Toute valeur chiffrée depuis une source structurée, jamais reformulée.
2. **Le versioning est un citoyen de première classe** — Aucun chunk sans tag de version.
3. **Rappel large, précision finale** — Vectoriel d'abord, reranking ensuite. Jamais l'inverse.
4. **La source de vérité mathématique est humaine** — Le bytecode décompilé n'est jamais une source de formule fiable.
5. **Déterminisme quand possible, sémantique quand nécessaire** — Un lookup par ID n'a rien à faire dans un espace vectoriel.
6. **Échouer localement, jamais globalement** — Isoler, journaliser, reprendre.
7. **Rien en production sans validation** — Le golden set est le gardien du temple.
8. **Dual-Field obligatoire** — Champ prose (vectorisé) + champ JSON brut (valeurs exactes).
9. **Séparation stricte work / prod** — staging/ jamais édité à la main, production/ protégé.
10. **Parsing isolé par entité** — Une donnée cassée ≠ crash global → quarantaine.
11. **Batch adaptatif + checkpoints** — Survivre à l'OOM et reprendre proprement.
12. **Handlers MCP isolés + watchdog** — Le serveur stdio ne meurt jamais.

## Règles d'or

- Rien ne passe de `staging/` → `production/` sans passer le golden set.
- `production/` n'est **jamais** édité à la main.
- Double versioning : SemVer (moteur) + B41/B42 (données du jeu).
