# SPDX-License-Identifier: LGPL-3.0-or-later
"""Read the allowable stress from the material of the model (if it has one).

FreeCAD material cards may carry a yield strength (``YieldStrength``); the metals in
the standard library do (Aluminium-6061-T6, Copper-…), the plain steel cards
("Steel", "CalculiX-Steel") do not.  When a value is there, the assistant suggests it
as the allowable stress - the user can still change or delete it.

The values in a material card come as text with a unit ("315 MPa",
"2.1e+08 kg/(mm*s^2)"), so they are parsed into MPa.
"""

import re

# factor to MPa
EINHEITEN = {
    "gpa": 1000.0,
    "mpa": 1.0,
    "n/mm^2": 1.0,
    "n/mm2": 1.0,
    "ksi": 6.894757293168361,
    "psi": 0.006894757293168361,
    "kpa": 0.001,
    "kg/(mm*s^2)": 0.001,      # 1 kg/(mm*s^2) = 1 kPa
    "kg/(mm*s²)": 0.001,
    "pa": 1e-6,
}

ZAHL = re.compile(r"^\s*([-+0-9.eE,]+)\s*([A-Za-z0-9/().^*² ]*)\s*$")

# keys that may contain a yield strength (order = priority)
SCHLUESSEL = ("YieldStrength", "UltimateTensileStrength", "CompressiveStrength")


def MPa(wert):
    """Convert a material value to MPa - or None when it is unusable."""
    if isinstance(wert, (int, float)):
        return float(wert) or None
    if not isinstance(wert, str):
        return None
    treffer = ZAHL.match(wert.replace(",", "."))
    if not treffer:
        return None
    try:
        zahl = float(treffer.group(1))
    except ValueError:
        return None
    einheit = treffer.group(2).strip().lower().replace(" ", "")
    faktor = EINHEITEN.get(einheit)
    if faktor is None:
        if not einheit:
            faktor = 1.0                 # no unit: read as MPa
        else:
            return None                  # unknown unit - better suggest nothing
    ergebnis = zahl * faktor
    return ergebnis if ergebnis > 0 else None


def streckgrenze(materialien, elsets, aus_inp=None):
    """What the material of the element sets yields.

    ``materialien`` is a list of ``(name, values dict)`` (see
    ``materialien_finden``), ``elsets`` the set of element sets.

    The mapping is made first through ``aus_inp`` - the assignment set -> material
    name that FreeCAD writes into the input file (``*SOLID SECTION, ELSET=...,
    MATERIAL=...``, see ``elsets.read_section_materials``).  That is the truth:
    CalculiX computes with exactly this material.  Only when the input file has
    no assignment (yet) is the mapping made through the name prefix
    ('MaterialSolid' belongs to 'MaterialSolidSolid'); if there is only one
    material, it applies to all sets without a material of their own.

    Returns {"<elset>": MPa}
    """
    ergebnis = {}
    eintraege = [(name, werte) for name, werte in materialien if isinstance(werte, dict)]
    for elset in elsets:
        passend = None
        name_in_inp = (aus_inp or {}).get(elset)
        if name_in_inp:
            for name, werte in eintraege:
                if name == name_in_inp:
                    passend = werte
                    break
        if passend is None:
            for name, werte in eintraege:
                if name and elset.lower().startswith(name.lower()):
                    passend = werte
                    break
        if passend is None and len(eintraege) == 1:
            passend = eintraege[0][1]
        if passend is None:
            continue
        for schluessel in SCHLUESSEL:
            if schluessel in passend:
                wert = MPa(passend[schluessel])
                if wert:
                    ergebnis[elset] = wert
                    break
    return ergebnis


def fehlende_werte(materialien):
    """Which material values that CalculiX needs for computing are missing.

    ``materialien`` is a list of ``(name, values dict)`` (see
    ``materialien_finden``).  FreeCAD's input file writer aborts without a
    Young's modulus with a bare ``KeyError: 'YoungsModulus'`` and leaves a
    half-finished ``.inp`` behind.  So that this stands out beforehand, this
    function reports per material what is missing.

    Returns ``{"<material name>": ["YoungsModulus", ...]}``
    """
    fehlt = {}
    for name, werte in materialien:
        if not isinstance(werte, dict):
            continue
        offen = [schluessel for schluessel in ("YoungsModulus", "PoissonRatio")
                 if schluessel not in werte]
        if offen:
            fehlt[name] = offen
    return fehlt


def materialien_finden(analyse):
    """The material objects of the model as [(name, values dict), ...].

    Searches in the analysis and - if necessary - in the whole document (FreeCAD
    places material objects next to the analysis).  Without an analysis the active
    document is taken, so the suggestion also works without a selected analysis.
    """
    ergebnis = []
    kandidaten = []
    if analyse is not None:
        for kind in getattr(analyse, "Group", []) or []:
            kandidaten.append(kind)
    try:
        import FreeCAD as App
        doc = getattr(analyse, "Document", None) or getattr(App, "ActiveDocument", None)
        if doc is not None:
            for obj in doc.Objects:
                if obj not in kandidaten:
                    kandidaten.append(obj)
    except Exception:
        pass
    for obj in kandidaten:
        if not str(getattr(obj, "TypeId", "")).startswith("App::MaterialObject"):
            continue
        werte = getattr(obj, "Material", None)
        if isinstance(werte, dict):
            ergebnis.append((obj.Name, werte))
    return ergebnis
