# -*- coding: utf-8 -*-
r"""
Étape 5 du cas Buddimm / Sitadel : repérer des patterns et sortir une liste de cibles.

Entrées : permis_qualifies_78.csv (classer_78.py)
          cache_annuaire.jsonl    (enrichir_78.py, partiel : 640 demandeurs, utilisé s'il est là)
Sorties : cibles_78.csv   -> une ligne par demandeur intéressant pour Buddimm, avec score et raisons
          patterns_78.txt -> les 5 patterns, chiffrés

Le score est volontairement simple et lisible (des points, pas de modèle) :
  +3 cœur de cible : association / fondation médico-sociale ou de santé, opérateur médico-social
  +1 association / fondation hors médico-social (culte, sport, école...)
  +2 bailleur social (client ou partenaire)
  +2 au moins un projet médico-social (résidence seniors / handicapés / sociale, équipement santé ou action sociale)
  +1 récurrent (3 permis ou plus)
  +1 actif récemment (un permis autorisé en 2024 ou après)
  +1 confirmé FINESS ou ESS par l'annuaire (seulement si la fiche a été consultée)
  exclu si l'annuaire dit que la structure a cessé son activité
Un humain chez Buddimm lit la liste et décide. L'outil ne contacte personne.

Lancement :
    cd BUDDIMM_-_Sitadel
    python cibles_78.py
"""
import json
from pathlib import Path

import pandas as pd

ICI = Path(__file__).resolve().parent
EXTRACTION = pd.Timestamp("2026-10-31")
COEUR = {"ESS : association / fondation", "opérateur santé / médico-social privé"}


def charger():
    p = pd.read_csv(ICI / "permis_qualifies_78.csv", sep=";", dtype=str, encoding="utf-8-sig")
    p["date_aut"] = pd.to_datetime(p.DATE_REELLE_AUTORISATION, errors="coerce")
    p["annee"] = p.date_aut.dt.year
    p["nb_logements"] = pd.to_numeric(p.nb_logements, errors="coerce").fillna(0)
    p["medico"] = p.signal_projet.notna() & (p.signal_projet != "")
    annuaire = {}
    if (ICI / "cache_annuaire.jsonl").exists():
        for l in (ICI / "cache_annuaire.jsonl").read_text(encoding="utf-8").splitlines():
            if l.strip():
                f = json.loads(l)
                annuaire[f["siren"]] = f
    return p, annuaire


def main():
    p, annuaire = charger()
    L = []
    out = L.append

    # Une ligne par demandeur. La famille retenue est celle du permis le plus récent
    # (un demandeur peut changer de code APE au fil des ans, cf. Altarea Cogedim).
    p = p.sort_values("date_aut")
    d = p.groupby("SIREN_DEM").agg(
        denomination=("DENOM_DEM", "last"), famille=("famille", "last"), sous_type=("sous_type", "last"),
        regle=("regle", "last"), nb_permis=("NUM_DAU", "count"), nb_logements=("nb_logements", "sum"),
        premiere=("annee", "min"), derniere=("annee", "max"), nb_communes=("COMM", "nunique"),
        nb_medico=("medico", "sum"),
        projets_medico=("signal_projet", lambda s: " | ".join(sorted(set(s.dropna()) - {""}))),
        permis=("NUM_DAU", lambda s: " ".join(s.tail(5))),
    ).reset_index()

    # --- PATTERN 1 : qui construit régulièrement ? ------------------------------------
    out("=== PATTERN 1 : les demandeurs récurrents (3 permis ou plus) ===")
    rec = d[d.nb_permis >= 3]
    out(f"{len(rec)} demandeurs sur {len(d)} ({len(rec)/len(d):.0%}) font {rec.nb_permis.sum()} permis "
        f"sur {len(p)} ({rec.nb_permis.sum()/len(p):.0%})")
    out(rec.groupby("famille").agg(demandeurs=("SIREN_DEM", "count"), permis=("nb_permis", "sum"))
        .sort_values("permis", ascending=False).to_string())

    # --- PATTERN 2 : les clients potentiels directs -------------------------------------
    out("\n=== PATTERN 2 : associations, fondations et opérateurs médico-sociaux qui construisent ===")
    coeur = d[d.famille.isin(COEUR)].sort_values("nb_permis", ascending=False)
    out(f"{len(coeur)} structures, {coeur.nb_permis.sum()} permis")
    out(coeur.head(15)[["denomination", "sous_type", "nb_permis", "derniere"]].to_string(index=False))

    # --- PATTERN 3 : qui porte les projets médico-sociaux ? -----------------------------
    out("\n=== PATTERN 3 : qui dépose les permis à vocation médico-sociale ? ===")
    med = p[p.medico]
    out(f"{len(med)} permis avec un signal médico-social")
    out(med.famille.value_counts().to_string())
    out("\nRésidences seniors / handicapés déposées par des promoteurs ou SCI "
        "(le futur exploitant n'est pas dans Sitadel : piste à creuser) :")
    res = med[med.signal_projet.str.contains("pers. âgées|handicapés") &
              med.famille.isin(["promoteur / constructeur", "SCI / foncière"])]
    out(res[["DENOM_DEM", "COMM", "annee", "signal_projet", "nb_logements"]]
        .sort_values("annee", ascending=False).head(15).to_string(index=False))

    # --- PATTERN 4 : permis autorisés depuis plus de 3 ans, sans chantier connu ---------
    out("\n=== PATTERN 4 : autorisés depuis plus de 3 ans, aucun chantier connu (FRAGILE) ===")
    vieux = p[(p.etat == "autorisé") & (p.date_aut < EXTRACTION - pd.DateOffset(years=3))]
    out(f"{len(vieux)} permis sur {(p.date_aut < EXTRACTION - pd.DateOffset(years=3)).sum()} autorisés avant "
        f"{(EXTRACTION - pd.DateOffset(years=3)).date()}")
    out("Attention : ~15 % des ouvertures de chantier ne remontent jamais (note SDES). Un projet de cette liste")
    out("peut être bloqué, abandonné... ou simplement commencé sans déclaration.")
    out(vieux.famille.value_counts().to_string())

    # --- PATTERN 5 : le rythme dans le temps, pour les familles qui intéressent Buddimm --
    out("\n=== PATTERN 5 : nombre de permis par an (familles cibles) ===")
    cib = p[p.famille.isin(COEUR | {"bailleur social"})]
    out(pd.crosstab(cib.famille, cib.annee).to_string())
    out("Nouveaux entrants (premier permis en 2024 ou après) parmi ces familles :")
    nouveaux = d[d.famille.isin(COEUR | {"bailleur social"}) & (d.premiere >= 2024)]
    out(nouveaux[["denomination", "famille", "nb_permis", "premiere"]].to_string(index=False))
    out("(2026 est incomplet : extraction d'octobre)")

    # --- LA LISTE DES CIBLES -------------------------------------------------------------
    def scorer(r):
        pts, raisons = 0, []
        a = annuaire.get(r.SIREN_DEM)
        medico_social = (r.famille == "opérateur santé / médico-social privé"
                         or any(m in str(r.sous_type) for m in ("médico", "santé"))
                         or bool(a and a.get("est_finess")))
        if r.famille in COEUR and medico_social:
            pts += 3; raisons.append("cœur de cible : " + r.famille + " (médico-social / santé)")
        elif r.famille in COEUR:
            pts += 1; raisons.append("association / fondation hors médico-social (" + str(r.sous_type) + ")")
        if r.famille == "bailleur social":
            pts += 2; raisons.append("bailleur social")
        if r.nb_medico > 0:
            pts += 2; raisons.append(f"{r.nb_medico} projet(s) médico-social(aux)")
        if r.nb_permis >= 3:
            pts += 1; raisons.append(f"récurrent ({r.nb_permis} permis)")
        if r.derniere >= 2024:
            pts += 1; raisons.append(f"actif récemment ({int(r.derniere)})")
        if a and a.get("statut") == "ok":
            if a.get("etat") == "C":
                return -1, "EXCLU : activité cessée selon l'annuaire"
            if a.get("est_finess") or a.get("est_ess"):
                pts += 1; raisons.append("confirmé " + ("FINESS" if a.get("est_finess") else "ESS") + " (annuaire)")
        return pts, " ; ".join(raisons)

    d[["score", "raisons"]] = d.apply(scorer, axis=1, result_type="expand")
    d["annuaire_consulte"] = d.SIREN_DEM.map(lambda s: "oui" if s in annuaire else "non")
    d["source_demandeur"] = "https://annuaire-entreprises.data.gouv.fr/entreprise/" + d.SIREN_DEM
    d["source_permis"] = ("https://www.data.gouv.fr/datasets/liste-des-permis-de-construire-et-autres-"
                          "autorisations-durbanisme (NUM_DAU : " + d.permis + ")")
    cibles = d[d.score >= 3].sort_values(["score", "nb_permis"], ascending=False)
    cibles[["denomination", "SIREN_DEM", "famille", "sous_type", "score", "raisons", "nb_permis",
            "nb_logements", "premiere", "derniere", "projets_medico", "regle", "annuaire_consulte",
            "source_demandeur", "source_permis"]].to_csv(
        ICI / "cibles_78.csv", sep=";", index=False, encoding="utf-8-sig")

    out("\n=== LISTE DES CIBLES (score >= 3) ===")
    out(f"{len(cibles)} demandeurs retenus | exclus car cessés : {(d.score == -1).sum()}")
    out(cibles.score.value_counts().sort_index(ascending=False).to_string())
    out("\nTop 20 :")
    out(cibles.head(20)[["denomination", "famille", "score", "raisons"]].to_string(index=False))

    texte = "\n".join(L)
    print(texte)
    (ICI / "patterns_78.txt").write_text(texte, encoding="utf-8")


if __name__ == "__main__":
    main()
