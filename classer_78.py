# -*- coding: utf-8 -*-
r"""
Étape 3 du cas Buddimm / Sitadel : qualifier le demandeur de chaque permis.

Entrée  : data/logements_78.csv et data/locaux_78.csv (PC du 78, produits par analyse_78.py)
Sorties : permis_qualifies_78.csv  -> une ligne par permis, avec famille + règle + source
          demandeurs_78.csv        -> une ligne par demandeur (SIREN), agrégée
          resume_classement_78.txt -> les chiffres clés

Principe : des règles explicites, appliquées dans l'ordre. La première qui
s'applique gagne, et son identifiant est écrit dans la colonne `regle`.
Aucune IA ici : chaque classement peut être expliqué et contesté.
Si aucune règle ne s'applique, le demandeur reste « non déterminé ».

Lancement :
    cd BUDDIMM_-_Sitadel
    python classer_78.py
"""
import re
from pathlib import Path

import pandas as pd

ICI = Path(__file__).resolve().parent
DONNEES = ICI / "data"  # CSV filtrés produits par analyse_78.py
SITADEL_URL = "https://www.data.gouv.fr/datasets/liste-des-permis-de-construire-et-autres-autorisations-durbanisme"
FICHE_URL = "https://annuaire-entreprises.data.gouv.fr/entreprise/{}"
DATE_EXTRACTION = pd.Timestamp("2026-10-31")  # fichiers « 2026-10 »

# --- Nomenclatures (catégories juridiques Sirène, codes NAF rév. 2) ---------
CJ_HLM = {"5546", "5547", "5646", "5647"}      # SA d'HLM (conseil d'admin. / directoire)
CJ_OPH = {"4140"}                               # EPIC local, dont les offices publics de l'habitat
CJ_HOPITAL = {"7364"}                           # établissement public d'hospitalisation
APE_PROMOTION = ("41.10", "41.20")              # promotion immobilière, construction de bâtiments
APE_SANTE_MEDICO = ("86.", "87.", "88.")        # santé, hébergement médico-social, action sociale
NOM_BAILLEUR = re.compile(
    r"\bH\.?L\.?M\b|HABITATIONS? A LOYER MODERE|ENTREPRISE SOCIALE POUR L.HABITAT|"
    r"OFFICE PUBLIC|\bOPH\b|LOGEMENT SOCIAL|\bESH\b"
)

# Lecture du dictionnaire Sitadel (vérifiée)
ETAT = {"2": "autorisé", "4": "annulé", "5": "commencé", "6": "terminé"}
RESIDENCE = {"1": "pers. âgées", "2": "étudiants", "3": "tourisme", "4": "hôtelière sociale",
             "5": "sociale", "6": "handicapés", "7": "autre", "8": "mixte"}
SERVICE_PUBLIC = {"1": "transport", "2": "enseignement", "3": "santé", "4": "action sociale",
                  "5": "ouvrage spécial", "6": "culture-loisir", "8": "plusieurs"}


def secteur_ape(ape: str) -> str:
    """Sous-type lisible pour les entreprises, à partir des 2 premiers chiffres du NAF."""
    try:
        n = int(ape[:2])
    except (TypeError, ValueError):
        return "?"
    if n <= 3:   return "agriculture"
    if n <= 33:  return "industrie"
    if n <= 39:  return "énergie / eau / déchets"
    if n <= 43:  return "BTP"
    if n <= 47:  return "commerce"
    if n <= 53:  return "transport / logistique"
    if n <= 56:  return "hôtellerie / restauration"
    if n <= 66:  return "information / finance"
    if n <= 68:  return "immobilier"
    return "services"


def classer(cj: str, ape: str, nom: str, profil_social: bool = False):
    """Renvoie (famille, sous_type, regle, confiance). Première règle qui s'applique.
    profil_social : le demandeur a créé >= 20 logements dans le 78, dont >= 50 % en
    prêt locatif social (calculé sur NB_LGT_PRET_LOC_SOCIAL, voir main)."""
    propre = lambda v: "" if pd.isna(v) else str(v).strip()
    cj, ape, nom = propre(cj), propre(ape), propre(nom).upper()

    # 1. Bailleurs sociaux : la forme juridique suffit (fait établi par Sirène)
    if cj in CJ_HLM:
        return "bailleur social", "SA d'HLM", "R01_CJ_SA_HLM", "forte"
    if cj in CJ_OPH and ape.startswith("68.20A"):
        return "bailleur social", "office public de l'habitat", "R02_CJ_EPIC_LOCAL+APE_LOCATION_LOGEMENT", "forte"

    # 2. Économie sociale et solidaire : associations, fondations, mutuelles
    if cj.startswith("92") or cj.startswith("93"):
        sous = "fondation" if cj.startswith("93") else "association"
        if ape.startswith(("87.", "88.")):
            sous += " médico-sociale"
        elif ape.startswith("86."):
            sous += " de santé"
        elif ape.startswith("94.91"):
            sous += " cultuelle"
        return "ESS : association / fondation", sous, "R03_CJ_ASSOCIATION_FONDATION", "forte"
    if cj.startswith("8"):
        return "ESS : association / fondation", "mutuelle / organisme social", "R04_CJ_ORGANISME_SOCIAL", "forte"

    # 3. Secteur public
    if cj in CJ_HOPITAL:
        return "collectivité / établissement public", "hôpital public", "R05_CJ_HOPITAL_PUBLIC", "forte"
    if cj.startswith("7") or cj.startswith("41"):
        sous = {"7210": "commune", "7220": "département", "7230": "région"}.get(cj, "autre public")
        return "collectivité / établissement public", sous, "R06_CJ_PERSONNE_PUBLIQUE", "forte"

    # 4. Opérateurs privés de santé / médico-social (EHPAD commerciaux, cliniques...)
    if ape.startswith(APE_SANTE_MEDICO):
        return "opérateur santé / médico-social privé", ape, "R07_APE_SANTE_MEDICO_SOCIAL", "moyenne"

    # 5. Bailleurs sociaux sous une autre forme : seulement sur le nom -> confiance faible
    if NOM_BAILLEUR.search(nom) and ape.startswith("68."):
        return "bailleur social", "repéré par le nom", "R08_NOM_BAILLEUR+APE_IMMOBILIER", "faible"
    # ... ou par ce qu'il construit : majorité de logements financés en prêt locatif social
    if profil_social and ape.startswith("68.20"):
        return "bailleur social", "repéré par la part de logements sociaux", "R08B_PART_LOGEMENT_SOCIAL>=50%", "moyenne"

    # 6. Promoteurs et constructeurs (y compris les sociétés de programme type SCCV)
    if ape.startswith(APE_PROMOTION):
        sous = "société de programme" if ape == "41.10D" else "promoteur / constructeur"
        return "promoteur / constructeur", sous, "R09_APE_PROMOTION_CONSTRUCTION", "moyenne"

    # 7. Agricole
    if cj in {"6598", "6533", "6597", "6534", "6536"} or ape[:2] in {"01", "02", "03"}:
        return "exploitation agricole", "", "R10_CJ_OU_APE_AGRICOLE", "moyenne"

    # 8. SCI, foncières, marchands de biens, holdings patrimoniales
    if cj.startswith("65") and (ape.startswith(("68.", "64.20")) or not ape):
        return "SCI / foncière", "société civile immobilière", "R11_CJ_SOCIETE_CIVILE+APE_IMMOBILIER", "moyenne"
    if cj.startswith("91"):
        return "SCI / foncière", "copropriété", "R12_CJ_SYNDICAT_PROPRIETAIRES", "moyenne"
    if ape.startswith("68.") or ape.startswith("64.20"):
        sous = {"68.10Z": "marchand de biens", "68.20A": "loueur de logements (privé)",
                "64.20Z": "holding"}.get(ape, "foncière / gestion")
        return "SCI / foncière", sous, "R13_APE_IMMOBILIER_OU_HOLDING", "moyenne"

    # 9. Autres entreprises commerciales
    if cj[:1] in {"5", "3", "6"} and ape and not cj.startswith("65"):
        return "entreprise", secteur_ape(ape), "R14_CJ_SOCIETE_COMMERCIALE", "moyenne"

    # 10. Rien de sûr : on assume
    return "non déterminé", f"CJ={cj or '?'} APE={ape or '?'}", "R99_AUCUNE_REGLE", "-"


def signal_projet(r) -> str:
    """Ce que le permis construit, quand c'est pertinent pour Buddimm (indépendant du demandeur)."""
    s = []
    res = str(r.get("RESIDENCE", "") or "")
    if res in {"1", "4", "5", "6"}:
        s.append("résidence " + RESIDENCE[res])
    for col, lib in [("RES_PERS_AGEES", "pers. âgées"), ("RES_HANDICAPES", "handicapés"),
                     ("RES_SOCIALE", "sociale"), ("RES_HOTEL_SOCIALE", "hôtelière sociale")]:
        if str(r.get(col, "")).strip().lower() in {"true", "1"} and ("résidence " + lib) not in s:
            s.append("résidence " + lib)
    tsp = str(r.get("TYPE_SERVICE_PUBLIC", "") or "")
    if tsp in {"3", "4"}:
        s.append("équipement " + SERVICE_PUBLIC[tsp])
    return " ; ".join(s)


def charger():
    lire = lambda f: pd.read_csv(DONNEES / f, sep=";", dtype=str, low_memory=False)
    log, loc = lire("logements_78.csv"), lire("locaux_78.csv")
    log["fichier"], loc["fichier"] = "logements", "locaux"
    # un permis présent dans les deux fichiers : on garde une ligne, en notant les deux origines
    deux = set(log.NUM_DAU) & set(loc.NUM_DAU)
    df = pd.concat([log, loc], ignore_index=True)
    df.loc[df.NUM_DAU.isin(deux), "fichier"] = "logements+locaux"
    # on garde la ligne logements (elle porte RES_*), complétée par TYPE_SERVICE_PUBLIC des locaux
    tsp = loc.set_index("NUM_DAU")["TYPE_SERVICE_PUBLIC"]
    df = df.drop_duplicates("NUM_DAU", keep="first").copy()
    df["TYPE_SERVICE_PUBLIC"] = df["NUM_DAU"].map(tsp).fillna(df.get("TYPE_SERVICE_PUBLIC"))
    return df, len(log), len(loc), len(deux)


def main():
    df, n_log, n_loc, n_deux = charger()
    n_total = len(df)
    pm = df[df.SIREN_DEM.notna() & (df.SIREN_DEM.str.strip() != "")].copy()

    # Profil « bailleur social » observé dans les données : part des logements créés en PLS
    lgt = pd.to_numeric(pm.NB_LGT_TOT_CREES, errors="coerce").fillna(0)
    pls = pd.to_numeric(pm.NB_LGT_PRET_LOC_SOCIAL, errors="coerce").fillna(0)
    tot = lgt.groupby(pm.SIREN_DEM).sum()
    part = pls.groupby(pm.SIREN_DEM).sum() / tot.where(tot > 0)
    sociaux = set(part[(part >= 0.5) & (tot >= 20)].index)

    res = pm.apply(lambda r: classer(r.CJ_DEM, r.APE_DEM, r.DENOM_DEM, r.SIREN_DEM in sociaux),
                   axis=1, result_type="expand")
    pm[["famille", "sous_type", "regle", "confiance"]] = res
    pm["signal_projet"] = pm.apply(signal_projet, axis=1)
    pm["etat"] = pm.ETAT_DAU.map(ETAT)
    pm["nb_logements"] = pd.to_numeric(pm.NB_LGT_TOT_CREES, errors="coerce")
    pm["source_permis"] = SITADEL_URL + " (NUM_DAU " + pm.NUM_DAU + ")"
    pm["source_demandeur"] = pm.SIREN_DEM.map(FICHE_URL.format)

    cols = ["NUM_DAU", "fichier", "COMM", "ADR_LOCALITE_TER", "DATE_REELLE_AUTORISATION",
            "DATE_REELLE_DOC", "DATE_REELLE_DAACT", "etat", "SIREN_DEM", "DENOM_DEM", "CJ_DEM",
            "APE_DEM", "famille", "sous_type", "regle", "confiance", "signal_projet",
            "nb_logements", "SURF_HAB_CREEE", "SURF_LOC_CREEE", "source_permis", "source_demandeur"]
    sortie = pm[cols].sort_values(["famille", "DENOM_DEM", "DATE_REELLE_AUTORISATION"])
    sortie.to_csv(ICI / "permis_qualifies_78.csv", sep=";", index=False, encoding="utf-8-sig")

    # Une ligne par demandeur
    pm["annee"] = pm.DATE_REELLE_AUTORISATION.str[:4]
    dem = pm.groupby("SIREN_DEM").agg(
        denomination=("DENOM_DEM", "first"), famille=("famille", "first"),
        sous_type=("sous_type", "first"), regle=("regle", "first"),
        nb_permis=("NUM_DAU", "count"), nb_logements=("nb_logements", "sum"),
        premiere_annee=("annee", "min"), derniere_annee=("annee", "max"),
        nb_communes=("COMM", "nunique"),
        permis_signal_medico_social=("signal_projet", lambda s: (s != "").sum()),
    ).reset_index().sort_values("nb_permis", ascending=False)
    dem["source_demandeur"] = dem.SIREN_DEM.map(FICHE_URL.format)
    dem.to_csv(ICI / "demandeurs_78.csv", sep=";", index=False, encoding="utf-8-sig")

    # Résumé
    L = []
    p = L.append
    p("=== PÉRIMÈTRE ===")
    p(f"PC logements 78 : {n_log} | PC locaux 78 : {n_loc} | dans les deux : {n_deux}")
    p(f"Permis uniques : {n_total} | dont demandeur personne morale (SIREN diffusé) : {len(pm)} ({len(pm)/n_total:.0%})")
    p(f"Demandeurs distincts (SIREN) : {pm.SIREN_DEM.nunique()}")
    p("\n=== FAMILLES (en nombre de permis) ===")
    fam = pm.famille.value_counts()
    for f, n in fam.items():
        p(f"{f:42s} {n:5d}  {n/len(pm):6.1%}   ({pm[pm.famille == f].SIREN_DEM.nunique()} demandeurs)")
    p(f"\nNON DÉTERMINÉ : {fam.get('non déterminé', 0)} permis ({fam.get('non déterminé', 0)/len(pm):.1%})")
    p("\n=== RÈGLES UTILISÉES ===")
    p(pm.regle.value_counts().to_string())
    p("\n=== CONFIANCE ===")
    p(pm.confiance.value_counts().to_string())
    p("\n=== SOUS-TYPES DÉTAILLÉS ===")
    p(pm.groupby(["famille", "sous_type"]).size().sort_values(ascending=False).head(40).to_string())
    p("\n=== PERMIS AVEC UN SIGNAL MÉDICO-SOCIAL DANS LE PROJET ===")
    sig = pm[pm.signal_projet != ""]
    p(f"{len(sig)} permis")
    p(pd.crosstab(sig.signal_projet, sig.famille).to_string())
    p("\n=== NON DÉTERMINÉS : combinaisons CJ / APE les plus fréquentes (à revoir) ===")
    nd = pm[pm.famille == "non déterminé"]
    p(nd.groupby(["CJ_DEM", "APE_DEM"]).size().sort_values(ascending=False).head(15).to_string())
    p("\n=== CONTRÔLE : top 25 demandeurs et leur famille ===")
    p(dem.head(25)[["denomination", "famille", "sous_type", "nb_permis", "regle"]].to_string(index=False))
    texte = "\n".join(L)
    print(texte)
    (ICI / "resume_classement_78.txt").write_text(texte, encoding="utf-8")


if __name__ == "__main__":
    main()
