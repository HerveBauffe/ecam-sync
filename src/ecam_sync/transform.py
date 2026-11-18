"""Règles de transformation d'un événement (fonctions pures, faciles à tester).

Règle métier :
  * la 1re ligne de DESCRIPTION devient le titre (SUMMARY) ;
  * le préfixe « Act: » est supprimé du titre ;
  * les lignes suivantes de DESCRIPTION restent dans la description ;
  * l'ancien SUMMARY (code technique du type « ®-XX3T-T1-G1> ») est abandonné,
    sauf pour lever l'ambiguïté d'un titre générique (« théorie », « exercices »...) :
    on le préfixe alors du nom du cours, retrouvé grâce au code (TH2C) dans les
    examens du même fichier (« TH2C:Thermo ») -> « Thermo – théorie ».
    Si le fichier ne contient aucun examen pour ce code, le code lui-même sert de préfixe.

Deux formats existent dans la source :
  "Act:Signals and systems\\nGroupe:G1\\nEns:AAA"
  "PM1C:Pont Math[ECRIT]\\ \\nEns:BBB CCC"      (examens ; « \\ » parasite en fin de ligne)

>>> Pour changer ce qui est supprimé du titre, modifier LABEL_PREFIX ci-dessous ;
>>> pour la liste des titres jugés trop vagues, GENERIC_TITLES. <<<
Attention : changer ces règles change les titres, donc l'identité des événements (voir sync.py).
"""
from __future__ import annotations

import re

# Préfixe de champ à retirer au début du titre. Ajouter ici d'autres préfixes si besoin,
# par ex. r"^\s*(?:Act|[A-Z0-9]{4})\s*:\s*" retirerait aussi les codes de cours (PM1C:, PH1C:...).
LABEL_PREFIX = re.compile(r"^\s*Act\s*:\s*", re.IGNORECASE)

# Antislashs / espaces parasites en fin de ligne (« [ECRIT]\ »).
TRAILING_JUNK = re.compile(r"[\\\s]+$")

FALLBACK_TITLE = "(sans titre)"

# Titres trop vagues pour être compris seuls dans un agenda (comparaison sans tenir compte de la casse).
GENERIC_TITLES = frozenset({
    "théorie", "theorie", "exercices", "exercice", "labo", "laboratoire", "tp", "td", "travaux pratiques",
})

# Code de cours en tête de l'ancien SUMMARY : « ®-TH2C-T1-2BA », « TH2C:Thermo ».
COURSE_CODE = re.compile(r"^\s*(?:®-)?([A-Z0-9]{4})[-:]")
# Examen : « TH2C:Thermo » -> nom du cours (éventuel « [ECRIT] » retiré).
EXAM_SUMMARY = re.compile(r"^\s*([A-Z0-9]{4}):(.+?)(?:\[[^\]]*\])?\s*$")


def clean_title(line: str) -> str:
    title = LABEL_PREFIX.sub("", line)
    title = TRAILING_JUNK.sub("", title)
    return re.sub(r"\s+", " ", title).strip()


def course_names(summaries) -> dict[str, str]:
    """Table code -> nom de cours, déduite des examens (« TH2C:Thermo »). Le 1er nom (ordre trié) l'emporte."""
    names: dict[str, str] = {}
    for summary in sorted(summaries):
        match = EXAM_SUMMARY.match(summary)
        if match and (name := clean_title(match.group(2))):
            names.setdefault(match.group(1), name)
    return names


def transform_texts(summary: str, description: str, names: dict[str, str] | None = None) -> tuple[str, str]:
    """Retourne (titre, description) tels qu'ils iront dans Google Calendar.
    `names` : table code -> nom de cours (voir course_names) pour préciser les titres génériques."""
    lines = description.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title = clean_title(lines[0]) if lines else ""
    rest = "\n".join(line.strip() for line in lines[1:] if line.strip())

    if not title:  # description vide : on garde l'ancien titre plutôt que rien
        title = clean_title(summary) or FALLBACK_TITLE
        rest = "\n".join(line.strip() for line in lines if line.strip())
    if title.casefold() in GENERIC_TITLES and (code := COURSE_CODE.match(summary)):
        title = f"{(names or {}).get(code.group(1), code.group(1))} – {title}"
    return title, rest
