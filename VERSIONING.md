# Versioning — Règles et Cycle de Vie

## Principe Fondamental

> **VERSION** est la _seule_ source de vérité. Nulle part ailleurs dans le
> dépôt, le numéro de version ne doit être codé en dur.

## Gestion Sémantique (SemVer)

| Composant | Signification | Exemple |
|-----------|---------------|---------|
| `MAJOR`   | Cassure d'API / refonte complète | `1.0.0` |
| `MINOR`   | Nouvelle fonctionnalité retro-compatible | `0.2.0` |
| `PATCH`   | Correction de bug, sans changement d'API | `0.1.1` |

### Pré-publication

| Suffixe  | Signification |
|----------|---------------|
| `-alpha` | Développement actif, API susceptible de changer |
| `-beta`  | API gelée, stabilisation en cours |
| `-rc`    | Release candidate, pas de nouvelle feature |

## Cycle de Vie des Versions

```
alpha  →  beta  →  rc  →  stable  →  deprecated  →  sunset
 │         │        │        │           │             │
 └── API instable ──┘        │           │             │
        ─── API gelée ───────┘           │             │
                  ─── Security patches ───┘             │
                           ─── Fin de support ─────────┘
```

| Étiquette    | Support | Correctifs | Nouvelles Feature |
|--------------|---------|------------|-------------------|
| `alpha`      | ❌      | ❌         | ✅                |
| `beta`       | ⚠️      | ✅         | ✅                |
| `stable`     | ✅      | ✅         | ❌                |
| `deprecated` | ⚠️      | ⚠️ (sec.)  | ❌                |
| `sunset`     | ❌      | ❌         | ❌                |

## Version des Données (Chunks storage vectoriel)

Chaque chunk ingéré **doit** porter le champ `game_version` pour isoler les
deux jeux de données Project Zomboid (B41 / B42).

```json
{
  "game_version": "b42",
  "version": "0.1.0-alpha",
  "chunk_id": "item.Base.Axe",
  ...
}
```

| Valeur possible | Signification |
|-----------------|---------------|
| `"b41"`        | Build 41 (stable historique) |
| `"b42"`        | Build 42 (current) |
| `"legacy"`     | Données pré-versioning |

## Workflow

1. Modifier la version → modifier **uniquement** `VERSION`
2. `make version-check` vérifie qu'aucun fichier ne contient un numéro en dur
3. `make tag` incrémente automatiquement via `make-bump-version`

## Règles Absolues

1. **Jamais** de version hardcodée dans le code source (use `src/version.py`)
2. **Jamais** de tag Git sans changelog correspondant
3. **Toujours** que le `game_version` des chunks reflète la vraie version du jeu

---
