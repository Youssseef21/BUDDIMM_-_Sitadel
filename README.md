# Qualifier les demandeurs de permis de construire du 78 (Sitadel)

Prototype réalisé pour le cas métier Buddimm (stage IA agentique et développement web, 2027).

**Démo en ligne :** https://youssseef21.github.io/BUDDIMM_-_Sitadel/

Sitadel dit **qui** construit (SIREN, catégorie juridique, code APE), mais pas **ce qu'est** le demandeur pour un acteur de l'immobilier médico-social. Ce prototype qualifie chaque demandeur personne morale des Yvelines, repère des patterns et propose une liste de cibles où chaque résultat renvoie à sa source publique.

## L'approche : des règles d'abord, l'IA en dernier

```
Permis Sitadel (78) ──► Règles ──────────────┐
                                              ├──► Score et cibles ──► Page web ──► Humain (décide)
Annuaire des entreprises ──► Enrichissement ─┤
                                              │
              cas ambigus seulement ──► Agent IA
```

1. **Règles** (`classer_78.py`) : 15 règles ordonnées sur la catégorie juridique et le code APE. Chaque permis porte la règle qui l'a classé et une confiance (forte, moyenne, faible).
2. **Enrichissement** (`enrichir_78.py`) : l'API publique Recherche d'entreprises donne le code APE à jour, l'état (active ou cessée), les marqueurs ESS / FINESS et les dirigeants **qui sont des sociétés**. Les personnes physiques sont comptées, jamais nommées.
3. **Agent IA** (`agent_78.py`) : un LLM doté d'un outil `consulter_annuaire`, appelé seulement pour les cas ambigus (environ 0,4 % des demandeurs). Il justifie sa réponse avec ses sources, ou répond « non déterminé ». Si le service d'IA est indisponible, la chaîne fonctionne avec les règles seules.
4. **Score et cibles** (`cibles_78.py`) : un score de pertinence en points lisibles, et cinq patterns.
5. **Page web** (`export_web.py` → `docs/`) : une page statique, sans serveur ni clé d'API.

## Lancer la chaîne

Prérequis : Python 3.10+ et `pip install pandas openai`.

```bash
python analyse_78.py     # optionnel : refiltre les fichiers nationaux placés dans raw/ (1,3 Go, non versionnés)
python classer_78.py     # règles  -> permis_qualifies_78.csv
python enrichir_78.py    # annuaire -> cache_annuaire.jsonl (reprend là où il s'est arrêté)
python agent_78.py       # agent IA -> agent_78.csv (voir la configuration ci-dessous)
python cibles_78.py      # score et patterns -> cibles_78.csv, patterns_78.txt
python export_web.py     # données de la page -> docs/data.js
```

L'agent lit sa configuration dans des variables d'environnement. **Aucune clé n'est dans le code.**

```bash
set LLM_BASE_URL=<adresse d'une API compatible OpenAI>
set LLM_API_KEY=<clé>
```

## Contenu du dépôt

| Fichier | Rôle |
|---|---|
| `data/` | permis de construire du 78 extraits de Sitadel (octobre 2026) |
| `permis_qualifies_78.csv` | un permis par ligne : famille, règle, confiance, sources |
| `cache_annuaire.jsonl` | les 640 fiches de l'annuaire consultées (preuve, sans nom de personne) |
| `agent_78.csv` | les 14 cas ambigus : classement des règles et classement de l'agent, avec justification |
| `cibles_78.csv` | les 274 cibles, avec score, raisons et sources |
| `patterns_78.txt`, `resume_classement_78.txt` | les chiffres des patterns et du classement |
| `docs/` | la page de démonstration |

## Limites principales

- Les personnes morales non retrouvées dans Sirène n'ont pas de SIREN : elles échappent au filtre.
- Environ 15 % des ouvertures de chantier et un tiers des achèvements ne remontent jamais : un permis sans chantier connu n'est pas forcément bloqué.
- Une ligne porte le dernier état connu du permis, sans historique des modifications.
- L'annuaire n'a été consulté que pour 640 demandeurs sur 3 957 (échantillon non aléatoire).
- L'agent n'a pas été évalué sur un échantillon vérifié à la main, et il n'a répondu « non déterminé » sur aucun cas : un excès de confiance probable.
- Les poids du score sont des choix, à ajuster avec les équipes métier.

## Sources et règles respectées

- [Sitadel, liste des autorisations d'urbanisme](https://www.data.gouv.fr/datasets/liste-des-permis-de-construire-et-autres-autorisations-durbanisme) (SDES) et sa note de présentation.
- [Annuaire des entreprises](https://annuaire-entreprises.data.gouv.fr), API Recherche d'entreprises : 3 requêtes par seconde au maximum, avec un cache.
- Personnes morales uniquement, aucun nom de personne physique. L'outil ne contacte personne : un humain décide.

Outils : Python et pandas, GPT-5.4 pour l'agent, Claude Code comme assistant de code.
