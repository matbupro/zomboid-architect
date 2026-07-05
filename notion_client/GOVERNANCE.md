# 🏛️ Gouvernance du notion_client

## Principes

1. **Least Privilege** : API key limitée à 1 seule DB, pas d'accès workspace global
2. **Séparation des secrets** : Config réelle (`.env.notion`) jamais dans Git ; seul le template (`.env.notion.example`) est versionné
3. **Audit trail** : Toutes les sync Notion sont traçables via l'Activity log de la base
4. **Idempotence** : Relancer le sync deux fois produit le même résultat

## Responsabilités

| Rôle | Responsabilité |
|---|---|
| **Dev Local** | Générer sa propre `.env.notion`, ne jamais la committer |
| **Git Repo** | Versionner `.env.notion.example` (template) + `.gitignore` |
| **CI/CD** | Injecter `NOTION_API_KEY` et `NOTION_DATABASE_ID` comme secrets (GitHub Secrets ou équivalent) |
| **Notion Admin** | Vérifier régulièrement l'Activity log de la DB pour détecter tout abus |

## Incident Response

### En cas de fuite du token NOTION_API_KEY

1. Révoquer immédiatement sur https://notion.so/my-integrations
2. Examiner l'Activity log : dernière modification, dernière lecture
3. Auditer les changements apportés (surtout suppressions)
4. Déployer un nouveau token dans CI/CD et `.env.notion` local
5. Documenter l'incident dans le ticket associé

### En cas d'accès non autorisé à la DB Notion

1. Vérifier que les permissions de l'intégration sont limitées à cette seule DB
2. Examiner l'Activity log pour identifier le périmètre des modifications
3. Restaurer les données supprimées (Notion conserve 30 jours par défaut)
4. Régénérer le token et révoquer l'ancienne intégration

## Conformité

- **RGPD** : Vérifier si `agent/todo.md` contient des données personnelles (PII) avant la sync ; si oui, s'assurer du Data Processing Agreement (DPA) Notion
- **EU AI Act** : Ce client respecte les exigences de transparence (logs traçables)
- **ISO 42001** : Pratiques alignées — audit trail + least privilege

## Contrôle d'accès Notion

L'intégration Notion doit avoir les permissions minimales :
- ✅ Lecture/Écriture sur la database spécifique uniquement
- ❌ Pas d'accès à d'autres pages / workspaces
- ❌ Pas d'accès Admin workspace-wide

Toutes les modifications via l'API créent une trace dans l'Activity log de la page.
Vérifier régulièrement : Notion → Database → "Activity" (en bas à droite).
