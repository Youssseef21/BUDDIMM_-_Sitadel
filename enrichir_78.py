# -*- coding: utf-8 -*-
r"""
Étape 4a du cas Buddimm / Sitadel : enrichir chaque demandeur avec l'annuaire des entreprises.

Source  : API publique Recherche d'entreprises (gratuite, sans clé)
          https://recherche-entreprises.api.gouv.fr
Entrée  : data/logements_78.csv et data/locaux_78.csv (on y prend les SIREN des personnes morales)
Sorties : cache_annuaire.jsonl -> une réponse par ligne, réutilisée aux lancements suivants
          annuaire_78.csv      -> une ligne par SIREN, prête à croiser avec les permis

Règles respectées :
  - cadence raisonnable : une requête toutes les 0,35 s, pause plus longue si l'API dit « trop vite » ;
  - données personnelles : on ne garde JAMAIS le nom d'un dirigeant personne physique,
    seulement leur nombre. Les dirigeants qui sont des sociétés sont gardés (SIREN + nom).

Lancement :
    cd BUDDIMM_-_Sitadel
    python enrichir_78.py            (tous les SIREN, ~25 min la première fois)
    python enrichir_78.py --test 20  (seulement 20 SIREN, pour vérifier)
"""
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

ICI = Path(__file__).resolve().parent
DONNEES = ICI / "data"
CACHE = ICI / "cache_annuaire.jsonl"
SORTIE = ICI / "annuaire_78.csv"
API = "https://recherche-entreprises.api.gouv.fr/search?q={}"
FICHE = "https://annuaire-entreprises.data.gouv.fr/entreprise/{}"
PAUSE = 0.35  # secondes entre deux requêtes


# 1. LA LISTE DES SIREN À INTERROGER ------------------------------------------
def lister_siren():
    sirens = set()
    for f in ("logements_78.csv", "locaux_78.csv"):
        df = pd.read_csv(DONNEES / f, sep=";", dtype=str, usecols=["SIREN_DEM"])
        sirens |= set(df.SIREN_DEM.dropna().str.strip())
    return sorted(s for s in sirens if s)


# 2. LE CACHE : ce qu'on a déjà demandé n'est pas redemandé ----------------------
def lire_cache():
    deja = {}
    if CACHE.exists():
        for ligne in CACHE.read_text(encoding="utf-8").splitlines():
            if ligne.strip():
                fiche = json.loads(ligne)
                deja[fiche["siren"]] = fiche
    return deja


# 3. UNE QUESTION À L'API, ET LE TRI DE LA RÉPONSE ------------------------------
def interroger(siren):
    """Renvoie un dict propre pour ce SIREN (jamais de nom de personne physique)."""
    url = API.format(siren)
    for essai in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "prototype-sitadel-78"})
            with urllib.request.urlopen(req, timeout=20) as r:
                resultats = json.load(r).get("results", [])
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:            # « trop de requêtes » : on ralentit
                time.sleep(5 * (essai + 1))
                continue
            return {"siren": siren, "statut": f"erreur HTTP {e.code}"}
        except Exception as e:           # réseau coupé, délai dépassé...
            time.sleep(3)
            if essai == 3:
                return {"siren": siren, "statut": f"erreur {type(e).__name__}"}
    else:
        return {"siren": siren, "statut": "erreur: trop de refus"}

    # l'API fait une recherche : on ne garde que le résultat qui a EXACTEMENT ce SIREN
    r = next((x for x in resultats if x.get("siren") == siren), None)
    if r is None:
        return {"siren": siren, "statut": "introuvable"}

    c = r.get("complements") or {}
    societes, nb_personnes = [], 0
    for d in r.get("dirigeants") or []:
        if d.get("type_dirigeant") == "personne morale":
            societes.append({"siren": d.get("siren"), "nom": d.get("denomination"),
                             "qualite": d.get("qualite")})
        else:
            nb_personnes += 1            # on compte, on ne garde rien d'autre

    return {
        "siren": siren,
        "statut": "ok",
        "date_consultation": date.today().isoformat(),
        "nom": r.get("nom_complet"),
        "cj_annuaire": r.get("nature_juridique"),
        "ape_annuaire": r.get("activite_principale"),
        "etat": r.get("etat_administratif"),          # A = active, C = cessée
        "date_creation": r.get("date_creation"),
        "date_fermeture": r.get("date_fermeture"),
        "categorie": r.get("categorie_entreprise"),   # PME, ETI, GE
        "tranche_effectif": r.get("tranche_effectif_salarie"),
        "est_ess": c.get("est_ess"),
        "est_finess": c.get("est_finess"),
        "finess_juridique": c.get("liste_finess_juridique"),
        "est_association": c.get("est_association"),
        "est_siae": c.get("est_siae"),
        "type_siae": c.get("type_siae"),
        "est_service_public": c.get("est_service_public"),
        "dirigeants_societes": societes,
        "nb_dirigeants_personnes_physiques": nb_personnes,
    }


# 4. LA BOUCLE PRINCIPALE ---------------------------------------------------------
def main():
    sirens = lister_siren()
    if "--test" in sys.argv:
        sirens = sirens[: int(sys.argv[sys.argv.index("--test") + 1])]
    deja = lire_cache()
    a_faire = [s for s in sirens if s not in deja or deja[s].get("statut", "").startswith("erreur")]
    print(f"{len(sirens)} SIREN | déjà en cache : {len(sirens) - len(a_faire)} | à interroger : {len(a_faire)}")

    with CACHE.open("a", encoding="utf-8") as cache:
        for i, s in enumerate(a_faire, 1):
            fiche = interroger(s)
            deja[s] = fiche
            cache.write(json.dumps(fiche, ensure_ascii=False) + "\n")
            cache.flush()                # écrit tout de suite : rien n'est perdu si ça s'arrête
            if i % 100 == 0 or i == len(a_faire):
                print(f"  {i}/{len(a_faire)}  (dernier : {s} -> {fiche['statut']})", flush=True)
            time.sleep(PAUSE)

    # Le tableau final, une ligne par SIREN
    lignes = []
    for s in sirens:
        f = dict(deja[s])
        # les commissaires aux comptes vérifient les comptes : ils ne dirigent ni ne possèdent rien
        f["dirigeants_societes"] = " | ".join(
            f"{d['nom']} ({d['siren']}, {d['qualite']})" for d in f.get("dirigeants_societes") or []
            if "commissaire aux comptes" not in str(d.get("qualite")).lower())
        f["finess_juridique"] = " ".join(f.get("finess_juridique") or [])
        f["source_annuaire"] = FICHE.format(s)
        lignes.append(f)
    tab = pd.DataFrame(lignes)
    tab.to_csv(SORTIE, sep=";", index=False, encoding="utf-8-sig")

    print("\nStatuts :", tab.statut.value_counts().to_dict())
    ok = tab[tab.statut == "ok"]
    if len(ok):
        print(f"Actives : {(ok.etat == 'A').sum()} | cessées : {(ok.etat == 'C').sum()}")
        print(f"ESS : {(ok.est_ess == True).sum()} | FINESS : {(ok.est_finess == True).sum()}")
        print(f"Avec au moins un dirigeant société : {(ok.dirigeants_societes != '').sum()}")
    print(f"Écrit : {SORTIE}")


if __name__ == "__main__":
    main()
