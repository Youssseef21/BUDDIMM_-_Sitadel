# -*- coding: utf-8 -*-
r"""
Étape 1 du cas Buddimm / Sitadel : filtrer les permis de construire du département 78.

Entrée  : les deux fichiers nationaux Sitadel (logements ~1 Go, locaux ~360 Mo), à télécharger sur
          https://www.data.gouv.fr/datasets/liste-des-permis-de-construire-et-autres-autorisations-durbanisme
          et à placer dans le dossier raw/ (non versionné, trop lourd pour git).
Sorties : data/logements_78.csv et data/locaux_78.csv (permis de construire du 78)
          data/resultats_78.txt (taux de remplissage, codes les plus fréquents)

Lancement :
    python analyse_78.py
"""
import sys
import time
from pathlib import Path

import pandas as pd

ICI = Path(__file__).resolve().parent
RAW = ICI / "raw"
DATA = ICI / "data"
LOG = RAW / "Liste-des-autorisations-durbanisme-creant-des-logements.2026-10.csv"
LOC = RAW / "Liste-des-autorisations-durbanisme-creant-des-locaux-non-residentiels.2026-10.csv"

DATA.mkdir(exist_ok=True)
sortie = open(DATA / "resultats_78.txt", "w", encoding="utf-8")


def p(*args):
    """Affiche et écrit dans resultats_78.txt."""
    texte = " ".join(str(a) for a in args)
    print(texte)
    sortie.write(texte + "\n")


def filtre_78(chemin):
    """Lit le gros CSV par morceaux (tout en texte) et ne garde que les PC du 78."""
    for encodage in ("utf-8", "latin-1"):
        try:
            morceaux = []
            for i, chunk in enumerate(pd.read_csv(chemin, sep=";", dtype=str, chunksize=100_000,
                                                  low_memory=False, encoding=encodage)):
                morceaux.append(chunk[(chunk["DEP_CODE"].str.strip() == "78") &
                                      (chunk["TYPE_DAU"].str.strip() == "PC")])
                print(f"  morceau {i+1} lu...", end="\r")
            print()
            p(f"  (encodage utilisé : {encodage})")
            return pd.concat(morceaux)
        except UnicodeDecodeError:
            print(f"  encodage {encodage} refusé, j'essaie le suivant")
    sys.exit("Impossible de lire le fichier : encodage inconnu")


def personnes_morales(df):
    """Personne morale = SIREN diffusé (vide pour les particuliers)."""
    return df[df["SIREN_DEM"].fillna("").str.strip() != ""]


for f in (LOG, LOC):
    if not f.exists():
        sys.exit(f"Fichier manquant : {f}\nTélécharge-le sur data.gouv.fr et place-le dans raw/.")

debut = time.time()
p("=== Lecture du fichier LOGEMENTS (environ 1 Go, patience) ===")
log = filtre_78(LOG)
p("=== Lecture du fichier LOCAUX ===")
loc = filtre_78(LOC)
log.to_csv(DATA / "logements_78.csv", sep=";", index=False, encoding="utf-8")
loc.to_csv(DATA / "locaux_78.csv", sep=";", index=False, encoding="utf-8")

p("\n========== VUE D'ENSEMBLE ==========")
p("PC logements 78 :", len(log))
p("PC locaux 78    :", len(loc))
p("Présents dans les deux fichiers (même NUM_DAU) :", len(set(log["NUM_DAU"]) & set(loc["NUM_DAU"])))

cols = ["DENOM_DEM", "SIRET_DEM", "APE_DEM", "CJ_DEM",
        "DATE_REELLE_AUTORISATION", "DATE_REELLE_DOC", "DATE_REELLE_DAACT"]
for nom, df in [("LOGEMENTS", log), ("LOCAUX", loc)]:
    pm = personnes_morales(df)
    part = len(pm) / len(df) if len(df) else 0
    p(f"\n========== {nom} : {len(pm)} personnes morales sur {len(df)} ({part:.0%}) ==========")
    p("\n-- Taux de remplissage (%) sur les personnes morales --")
    p(pm[cols].apply(lambda c: (c.fillna("").str.strip() != "").mean() * 100).round(1).to_string())
    p("\n-- Top 15 catégories juridiques (CJ_DEM) --")
    p(pm["CJ_DEM"].value_counts(dropna=False).head(15).to_string())
    p("\n-- Top 15 codes APE (APE_DEM) --")
    p(pm["APE_DEM"].value_counts(dropna=False).head(15).to_string())
    p("\n-- État du permis (ETAT_DAU) --")
    p(pm["ETAT_DAU"].value_counts(dropna=False).to_string())
    p("\n-- Top 15 demandeurs (DENOM_DEM) par nombre de permis --")
    p(pm["DENOM_DEM"].value_counts(dropna=False).head(15).to_string())

p(f"\nTerminé en {time.time() - debut:.0f} secondes.")
sortie.close()
