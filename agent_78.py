# -*- coding: utf-8 -*-
r"""
Étape 4b du cas Buddimm / Sitadel : un agent IA pour les cas que les règles classent mal.

Principe :
  - les règles (classer_78.py) traitent les 7 000 permis ; l'agent ne voit qu'une QUINZAINE de cas flous ;
  - l'agent a UN outil : consulter_annuaire(siren). Il décide lui-même s'il l'appelle, et combien de fois
    (par ex. pour remonter d'une SCI vers la société qui la dirige) ;
  - il doit répondre par une famille de la liste, une justification et ses sources ;
  - s'il n'a pas de preuve, il répond « non déterminé » ;
  - les noms de personnes physiques ne lui sont jamais transmis (masqués par l'outil).

Modèle : GPT-5.4 via le proxy de l'université (API compatible OpenAI).
Configuration (jamais de clé dans le code) :
    set LLM_BASE_URL=<adresse d'une API compatible OpenAI>
    set LLM_API_KEY=<ta clé>
Lancement :
    cd BUDDIMM_-_Sitadel
    python agent_78.py
Sortie : agent_78.csv (une ligne par cas : classement des règles vs classement de l'agent)
"""
import json
import os
import time
import urllib.request
from pathlib import Path

import pandas as pd
from openai import OpenAI

ICI = Path(__file__).resolve().parent
MODELE = "azure_ai/gpt-5.4"
FICHE = "https://annuaire-entreprises.data.gouv.fr/entreprise/{}"
FAMILLES = ["bailleur social", "ESS : association / fondation", "opérateur santé / médico-social privé",
            "collectivité / établissement public", "promoteur / constructeur", "SCI / foncière",
            "entreprise", "exploitation agricole", "non déterminé"]

SYSTEME = f"""Tu qualifies le demandeur d'un permis de construire (base Sitadel, Yvelines) pour Buddimm,
une direction immobilière externalisée qui accompagne des associations médico-sociales, des structures
de l'ESS et des bailleurs sociaux.

On te donne un demandeur que des règles automatiques ont du mal à classer, avec ses codes Sitadel
(catégorie juridique CJ, code d'activité APE) et ses permis. Tu disposes de l'outil consulter_annuaire
pour lire la fiche officielle d'une entreprise (code APE à jour, état, ESS/FINESS, dirigeants qui sont
des sociétés). Tu peux l'appeler plusieurs fois, par exemple pour consulter la société qui dirige une SCI.

Repères (n'affirme pas la signification d'un code absent de cette liste) :
- CJ 65xx = société civile (6540 SCI, 6541 SCI de construction-vente) ; 5499 = SARL ; 5599 / 5699 = SA
  ordinaire ; 5710 = SAS ; 5546 / 5646 = SA d'HLM ; 5515 = SEM ; 92xx = association ; 9300 = fondation.
- APE 41.10x / 41.20x = promotion ou construction ; 68.10Z = marchand de biens ; 68.20A = location de
  logements ; 68.20B = location d'autres biens ; 86 / 87 / 88 = santé, médico-social, action sociale.

Règles :
- Choisis UNE famille dans cette liste exacte : {FAMILLES}.
- Le code APE À JOUR de la fiche annuaire prime sur celui de Sitadel (qui peut être périmé).
  Exemple : APE à jour 41.10A -> promoteur / constructeur, quelle que soit la forme juridique.
- Seulement si la CJ est une société civile (65xx) ou l'APE 41.10D (société de programme) : regarde
  les dirigeants qui sont des sociétés ; si l'un d'eux est clairement un promoteur, un bailleur ou une
  association, prends sa famille. Sinon, SCI / foncière.
- Appuie-toi sur des faits (codes, fiches consultées). Ta connaissance générale d'un nom connu peut
  servir, mais dis-le explicitement.
- Confiance : "forte" seulement si une fiche officielle prouve directement la famille (CJ ou APE à jour
  sans ambiguïté) ; "moyenne" si c'est une déduction (via un dirigeant, un nom, ta connaissance) ;
  "faible" sinon.
- Si deux familles restent plausibles, ou si la preuve manque, réponds "non déterminé". C'est une
  réponse attendue, pas un échec.
- Ne mentionne jamais de personne physique.

Réponds uniquement par un objet JSON :
{{"famille": "...", "sous_type": "...", "confiance": "forte|moyenne|faible",
  "justification": "2 phrases maximum", "sources": ["URL des fiches consultées"]}}"""

OUTILS = [{"type": "function", "function": {
    "name": "consulter_annuaire",
    "description": "Fiche officielle d'une entreprise française dans l'annuaire des entreprises, par SIREN "
                   "(9 chiffres). Renvoie nom, catégorie juridique, code APE à jour, état (A active, C cessée), "
                   "indicateurs ESS / FINESS, et les dirigeants qui sont des sociétés.",
    "parameters": {"type": "object", "properties": {"siren": {"type": "string"}}, "required": ["siren"]}}}]


# --- L'outil -----------------------------------------------------------------------
def consulter_annuaire(siren: str) -> dict:
    """Lit d'abord le cache d'enrichir_78.py, sinon interroge l'API publique. Jamais de nom de personne."""
    siren = "".join(ch for ch in str(siren) if ch.isdigit())[:9]
    cache = ICI / "cache_annuaire.jsonl"
    if cache.exists():
        for l in cache.read_text(encoding="utf-8").splitlines():
            if l.strip() and json.loads(l).get("siren") == siren:
                f = json.loads(l)
                break
        else:
            f = None
    else:
        f = None
    if f is None:
        time.sleep(0.4)  # cadence raisonnable
        req = urllib.request.Request(f"https://recherche-entreprises.api.gouv.fr/search?q={siren}",
                                     headers={"User-Agent": "prototype-sitadel-78"})
        try:
            res = json.load(urllib.request.urlopen(req, timeout=20)).get("results", [])
        except Exception as e:
            return {"siren": siren, "erreur": type(e).__name__}
        r = next((x for x in res if x.get("siren") == siren), None)
        if r is None:
            return {"siren": siren, "erreur": "introuvable"}
        c = r.get("complements") or {}
        f = {"siren": siren, "nom": r.get("nom_complet"), "cj_annuaire": r.get("nature_juridique"),
             "ape_annuaire": r.get("activite_principale"), "etat": r.get("etat_administratif"),
             "est_ess": c.get("est_ess"), "est_finess": c.get("est_finess"),
             "dirigeants_societes": [{"siren": d.get("siren"), "nom": d.get("denomination"),
                                      "qualite": d.get("qualite")}
                                     for d in r.get("dirigeants") or []
                                     if d.get("type_dirigeant") == "personne morale"],
             "nb_dirigeants_personnes_physiques": sum(1 for d in r.get("dirigeants") or []
                                                      if d.get("type_dirigeant") != "personne morale")}
    f = dict(f)
    f["dirigeants_societes"] = [d for d in f.get("dirigeants_societes") or []
                                if "commissaire aux comptes" not in str(d.get("qualite")).lower()]
    f["source"] = FICHE.format(siren)
    return f


# --- Le choix des cas flous ----------------------------------------------------------
def choisir_cas(p: pd.DataFrame) -> pd.DataFrame:
    d = p.sort_values("DATE_REELLE_AUTORISATION").groupby("SIREN_DEM").agg(
        denomination=("DENOM_DEM", "last"), cj=("CJ_DEM", "last"), ape=("APE_DEM", "last"),
        famille_regles=("famille", "last"), regle=("regle", "last"), confiance_regles=("confiance", "last"),
        nb_permis=("NUM_DAU", "count"),
        projets=("signal_projet", lambda s: " | ".join(sorted(set(s.dropna()) - {""}))),
        communes=("COMM", lambda s: " ".join(sorted(set(s))[:5])),
    ).reset_index()
    d["pourquoi_flou"] = ""
    groupes = [
        # SCI / foncières qui portent un projet médico-social : qui est derrière ?
        (d.famille_regles.eq("SCI / foncière") & d.projets.str.contains("pers. âgées|handicapés|santé|sociale"),
         "SCI/foncière avec projet médico-social", 6),
        # foncières très actives : vraie foncière ou autre métier ?
        (d.famille_regles.eq("SCI / foncière") & d.nb_permis.ge(9), "foncière très active", 3),
        # aucune règle
        (d.famille_regles.eq("non déterminé"), "aucune règle ne s'applique", 3),
        # bailleur repéré seulement par le nom
        (d.regle.str.startswith("R08_"), "bailleur repéré seulement par le nom", 2),
    ]
    choisis = []
    for masque, raison, n in groupes:
        sel = d[masque & ~d.SIREN_DEM.isin([c.SIREN_DEM for c in choisis])].nlargest(n, "nb_permis").copy()
        sel["pourquoi_flou"] = raison
        choisis += [r for _, r in sel.iterrows()]
    return pd.DataFrame(choisis)


# --- La boucle de l'agent ----------------------------------------------------------------
def qualifier(client: OpenAI, cas: pd.Series):
    messages = [{"role": "system", "content": SYSTEME},
                {"role": "user", "content": json.dumps({
                    "siren": cas.SIREN_DEM, "denomination": cas.denomination,
                    "cj_sitadel": cas.cj, "ape_sitadel": cas.ape, "nb_permis_78": int(cas.nb_permis),
                    "projets_medico_sociaux": cas.projets or "aucun", "communes": cas.communes,
                    "classement_par_les_regles": cas.famille_regles}, ensure_ascii=False)}]
    appels = []
    for _ in range(5):  # au plus 5 tours : l'agent ne peut pas boucler sans fin
        r = client.chat.completions.create(model=MODELE, messages=messages, tools=OUTILS)
        m = r.choices[0].message
        if not m.tool_calls:
            texte = (m.content or "").strip().removeprefix("```json").removesuffix("```").strip()
            try:
                rep = json.loads(texte)
            except json.JSONDecodeError:
                rep = {"famille": "non déterminé", "justification": "réponse illisible : " + texte[:150]}
            if rep.get("famille") not in FAMILLES:
                rep["justification"] = f"famille hors liste ({rep.get('famille')}) ; " + str(rep.get("justification"))
                rep["famille"] = "non déterminé"
            return rep, appels
        messages.append(m.model_dump(exclude_none=True))
        for t in m.tool_calls:
            args = json.loads(t.function.arguments or "{}")
            resultat = consulter_annuaire(args.get("siren", ""))
            appels.append(f"{args.get('siren')}:{resultat.get('nom', resultat.get('erreur'))}")
            messages.append({"role": "tool", "tool_call_id": t.id,
                             "content": json.dumps(resultat, ensure_ascii=False)})
    return {"famille": "non déterminé", "justification": "trop d'étapes sans conclusion"}, appels


def main():
    client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
    p = pd.read_csv(ICI / "permis_qualifies_78.csv", sep=";", dtype=str, encoding="utf-8-sig")
    cas = choisir_cas(p)
    print(f"{len(cas)} cas flous envoyés à l'agent\n")
    lignes = []
    for _, c in cas.iterrows():
        rep, appels = qualifier(client, c)
        lignes.append({
            "denomination": c.denomination, "siren": c.SIREN_DEM, "pourquoi_flou": c.pourquoi_flou,
            "famille_regles": c.famille_regles, "regle": c.regle,
            "famille_agent": rep.get("famille"), "sous_type_agent": rep.get("sous_type"),
            "confiance_agent": rep.get("confiance"), "justification": rep.get("justification"),
            "outils_appeles": " ; ".join(appels), "sources": " ".join(rep.get("sources") or []),
            "change": "oui" if rep.get("famille") != c.famille_regles else "non"})
        print(f"- {c.denomination[:40]:40s} règles: {c.famille_regles:28s} -> agent: {rep.get('famille')} "
              f"({rep.get('confiance')}) [{len(appels)} appel(s) outil]")
    out = pd.DataFrame(lignes)
    out.to_csv(ICI / "agent_78.csv", sep=";", index=False, encoding="utf-8-sig")
    print(f"\nL'agent a changé le classement dans {(out.change == 'oui').sum()} cas sur {len(out)}.")
    print(f"Non déterminé par l'agent : {(out.famille_agent == 'non déterminé').sum()}")


if __name__ == "__main__":
    main()
