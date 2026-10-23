# SPDX-License-Identifier: LGPL-3.0-or-later
"""Domain table: which element set is design space, which one is not.

The roles are stored in the document object as a string list, one entry per set
(`"<elset>|<role>"`), so the document is the single source of truth - the table
only shows it and writes changes straight back.
"""

# roles used in the document object
DESIGN = "design"
NON_DESIGN = "non_design"
IGNORE = "ignore"

ROLE_LABELS = {
    DESIGN: "Design space (optimized)",
    NON_DESIGN: "Non-design space (kept)",
    IGNORE: "ignore",
}
LABEL_ROLES = {label: role for role, label in ROLE_LABELS.items()}

# element sets that only collect everything - of no use in the table
# (FreeCAD writes Eall/Evolumes, Efaces, Eedges, Enodes for the whole model)
SAMMELSETS = ("eall", "all_available", "evolumes", "efaces", "eedges", "enodes")


def aktive(domains):
    """The domains that take part in the optimization.

    "ignore" means: these elements play no role for the optimization.
    Such sets do not go into the beso configuration - then they need no
    allowable stress either and are not evaluated.
    """
    return {name: rolle for name, rolle in (domains or {}).items() if rolle != IGNORE}


def parse_domains(werte):
    """["set|design", ...] -> {"set": "design"}."""
    ergebnis = {}
    for eintrag in werte or []:
        if "|" not in eintrag:
            continue
        name, rolle = eintrag.split("|", 1)
        name = name.strip()
        if name:
            ergebnis[name] = rolle.strip()
    return ergebnis


def format_domains(domains):
    """{"set": "design"} -> ["set|design", ...] (stable order)."""
    return ["%s|%s" % (name, domains[name]) for name in sorted(domains)]


def parse_stress(werte):
    """["set|235.0", ...] -> {"set": 235.0} (allowable stress in MPa)."""
    ergebnis = {}
    for eintrag in werte or []:
        if "|" not in eintrag:
            continue
        name, wert = eintrag.split("|", 1)
        name = name.strip()
        try:
            zahl = float(wert.strip().replace(",", "."))
        except ValueError:
            continue
        if name and zahl > 0:
            ergebnis[name] = zahl
    return ergebnis


def format_stress(limits, aus=None):
    """{"set": 235.0} -> ["set|235.0", ...] (stable order).

    ``aus`` are the sets with a **deliberately** empty field: they are stored as
    "<set>|0" so that the suggestion from the material does not reappear.
    """
    ergebnis = ["%s|%r" % (name, limits[name]) for name in sorted(limits)]
    ergebnis += ["%s|0" % name for name in sorted(set(aus or ()) - set(limits))]
    return ergebnis


def aus_stress(werte):
    """The sets stored as "<set>|0" (deliberately without stress)."""
    ergebnis = set()
    for eintrag in werte or []:
        if "|" not in eintrag:
            continue
        name, wert = eintrag.split("|", 1)
        try:
            zahl = float(wert.strip().replace(",", "."))
        except ValueError:
            continue
        if name.strip() and zahl <= 0:
            ergebnis.add(name.strip())
    return ergebnis


def vorschlag(elsets):
    """A first suggestion for the incoming sets.

    Every set starts as design space - that is what a user means when a model is
    built and nothing has been decided yet.  Areas that must be kept (bearings,
    screws, ...) are set to "non-design", areas that should not take part at all to
    "ignore".  Sets that only collect everything (Eall) are not offered at all.
    """
    vorschlaege = {}
    for name in elsets:
        if name.lower() in SAMMELSETS:
            continue
        vorschlaege[name] = DESIGN
    return vorschlaege


def rollen_fuer(elsets, gespeichert=None):
    """The roles of the offered sets.

    What is stored in the object stays valid.  Everything new - for example a set
    that only appeared after a model change - is **design space**:
    "ignore" is the exception that is set deliberately.
    """
    if not gespeichert:
        return vorschlag(elsets)
    return {name: gespeichert.get(name, DESIGN) for name in elsets}


def zeige_elsets(elsets):
    """Sets for the table: collector sets are hidden."""
    return {name: anzahl for name, anzahl in elsets.items() if name.lower() not in SAMMELSETS}
