# -*- coding: utf-8 -*-
r"""
Prépare les données de la page de démonstration (docs/index.html).

Entrées : permis_qualifies_78.csv, cibles_78.csv, agent_78.csv
Sortie  : docs/data.js  (window.DATA = {...}) — un fichier JS plutôt que JSON pour que la page
          marche aussi en l'ouvrant directement depuis le disque, sans serveur.
Aucune clé, aucun appel réseau : la page est 100 % statique (publiable sur GitHub Pages).

Lancement :
    python export_web.py
"""
import json
from pathlib import Path

import pandas as pd

ICI = Path(__file__).resolve().parent
lire = lambda f: pd.read_csv(ICI / f, sep=";", dtype=str, encoding="utf-8-sig").fillna("")

p = lire("permis_qualifies_78.csv")
c = lire("cibles_78.csv")
a = lire("agent_78.csv")

p["annee"] = p.DATE_REELLE_AUTORISATION.str[:4]
num = lambda s: pd.to_numeric(s, errors="coerce").fillna(0)

# Permis de chaque cible (pour la vue détaillée et la « simulation » de la chaîne)
cols_permis = ["NUM_DAU", "COMM", "DATE_REELLE_AUTORISATION", "etat", "regle", "confiance", "signal_projet",
               "nb_logements", "CJ_DEM", "APE_DEM"]
permis_par_siren = {s: g[cols_permis].tail(8).to_dict("records")
                    for s, g in p[p.SIREN_DEM.isin(c.SIREN_DEM)].sort_values("DATE_REELLE_AUTORISATION")
                    .groupby("SIREN_DEM")}

cibles = []
for r in c.to_dict("records"):
    cibles.append({
        "nom": r["denomination"], "siren": r["SIREN_DEM"], "famille": r["famille"], "sous_type": r["sous_type"],
        "score": int(num(pd.Series([r["score"]]))[0]), "raisons": r["raisons"],
        "nb_permis": int(num(pd.Series([r["nb_permis"]]))[0]),
        "nb_logements": int(num(pd.Series([r["nb_logements"]]))[0]),
        "premiere": r["premiere"][:4], "derniere": r["derniere"][:4],
        "projets": r["projets_medico"], "regle": r["regle"], "annuaire": r["annuaire_consulte"],
        "source": r["source_demandeur"], "permis": permis_par_siren.get(r["SIREN_DEM"], []),
    })

fam = p.famille.value_counts()
cibles_fam = ["ESS : association / fondation", "bailleur social", "opérateur santé / médico-social privé"]
par_an = pd.crosstab(p[p.famille.isin(cibles_fam)].famille, p.annee)

data = {
    "chiffres": {
        "permis": len(p), "demandeurs": int(p.SIREN_DEM.nunique()), "cibles": len(c),
        "medico": int((p.signal_projet != "").sum()),
        "non_determine_pct": round(100 * fam.get("non déterminé", 0) / len(p), 1),
        "agent_cas": len(a), "agent_change": int((a.change == "oui").sum()),
        "ape_perime_pct": 5.8, "cessees_pct": 7.5, "annuaire_n": 640,
    },
    "familles": [{"famille": f, "n": int(n)} for f, n in fam.items()],
    "confiance": {k: int(v) for k, v in p.confiance.value_counts().items()},
    "regles": {k: int(v) for k, v in p.regle.value_counts().items()},
    "par_an": {"annees": [x for x in par_an.columns if x],
               "series": {f: [int(par_an.loc[f, y]) for y in par_an.columns if y] for f in par_an.index}},
    "cibles": cibles,
    "agent": a[["denomination", "siren", "pourquoi_flou", "famille_regles", "regle", "famille_agent",
                "sous_type_agent", "confiance_agent", "justification", "outils_appeles", "change"]]
             .to_dict("records"),
}

(ICI / "docs").mkdir(exist_ok=True)
(ICI / "docs" / "data.js").write_text("window.DATA = " + json.dumps(data, ensure_ascii=False) + ";\n",
                                      encoding="utf-8")
print(f"docs/data.js écrit : {len(cibles)} cibles, {len(data['agent'])} cas agent, "
      f"{(ICI / 'docs' / 'data.js').stat().st_size // 1024} Ko")
