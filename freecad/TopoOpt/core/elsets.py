# SPDX-License-Identifier: LGPL-3.0-or-later
"""Read element sets (ELSET) out of a CalculiX .inp file.

The names of the element sets are written by FreeCAD's writer and must not be
guessed (a 3D analysis uses `<material>Solid`, a 2D analysis uses
`<material><thickness>`, and numeric suffixes appear when a document holds more
than one body).  Reading them from the .inp is fast - measured 0.5 s for 41,666
TETRA10 elements - while the FemMesh Python API is unusable for mass queries
(96 ms per `getElementNodes()` call).

FreeCAD writes material sets as an attribute of the element cards
(`*Element, TYPE=C3D10, ELSET=Evolumes`) and the collector sets as separate cards
(`*ELSET, ELSET=Eall` with the single line `Evolumes`).  A card can therefore
contain element numbers *or* the name of another set, and the references have to
be resolved - otherwise `MaterialSolidSolid` looks like a one-element set.
"""

import os
import re

KURZFORM = re.compile(r"^\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*$")
ATTRIBUT = re.compile(r"([A-Za-z_]+)\s*=\s*\"?([^,\"]+)\"?")


def _attribute(zeile):
    """All KEY=VALUE attributes of a card line, keys in upper case."""
    ergebnis = {}
    for schluessel, wert in ATTRIBUT.findall(zeile):
        ergebnis[schluessel.strip().upper()] = wert.strip()
    return ergebnis


def _ist_zahl(text):
    return text.lstrip("-").isdigit()


def _rohdaten(inp_path):
    """{set name: (number of own elements, [referenced set names])}."""
    roh = {}
    if not inp_path or not os.path.isfile(inp_path):
        return roh

    aktuell = None
    modus = None          # "elemente" (from *ELEMENT) or "elset" (from *ELSET)
    generate = False
    try:
        with open(inp_path, "r", encoding="utf8", errors="ignore") as fh:
            for zeile in fh:
                zu = zeile.strip()
                if zu.startswith("*"):
                    art = zu.upper()
                    attrs = _attribute(zu)
                    if art.startswith("*ELEMENT"):
                        aktuell, modus, generate = attrs.get("ELSET"), "elemente", False
                    elif art.startswith("*ELSET"):
                        aktuell, modus = attrs.get("ELSET"), "elset"
                        generate = "GENERATE" in art
                    else:
                        aktuell, modus, generate = None, None, False
                    if aktuell:
                        roh.setdefault(aktuell, [0, []])
                    continue
                if not aktuell or not zu:
                    continue
                if modus == "elemente":
                    if _ist_zahl(zu.split(",")[0].strip()):
                        roh[aktuell][0] += 1
                    continue
                if generate:
                    treffer = KURZFORM.match(zu)
                    if treffer:
                        start, ende, schritt = (int(g) for g in treffer.groups())
                        if schritt:
                            roh[aktuell][0] += max(0, (ende - start) // schritt + 1)
                    continue
                # normal notation: element numbers (up to 16 per line) or
                # a reference to another set name
                for teil in (t.strip() for t in zu.split(",")):
                    if not teil:
                        continue
                    if _ist_zahl(teil):
                        roh[aktuell][0] += 1
                    elif teil not in roh[aktuell][1]:
                        roh[aktuell][1].append(teil)
    except OSError:
        return {}
    return {name: (anzahl, verweise) for name, (anzahl, verweise) in roh.items()}


def read_elsets(inp_path):
    """Element sets of an .inp as {name: number of elements} (references resolved)."""
    roh = _rohdaten(inp_path)
    ergebnis = {}

    def aufloesen(name, gesehen):
        if name in ergebnis:
            return ergebnis[name]
        if name not in roh or name in gesehen:      # cycle or unknown
            return 0
        gesehen = gesehen | {name}
        anzahl, verweise = roh[name]
        for ziel in verweise:
            anzahl += aufloesen(ziel, gesehen)
        ergebnis[name] = anzahl
        return anzahl

    for name in roh:
        aufloesen(name, set())
    return ergebnis


def read_shell_thicknesses(inp_path):
    """Shell thicknesses from the ``*SHELL SECTION`` cards: ``{elset: thickness_mm}``.

    FreeCAD writes a separate card for every surface elset::

        *SHELL SECTION, ELSET=MaterialSolidElementGeometry2D, MATERIAL=MaterialSolid, OFFSET=0
        10

    This makes the assignment element set -> thickness **unambiguous**, even when a
    model has several thicknesses (then there are several cards) - nothing has to be
    guessed.  A volume model has no such card; the result is empty then.
    """
    dicken = {}
    if not inp_path or not os.path.isfile(inp_path):
        return dicken
    aktuell = None
    fehlt_noch = False
    try:
        with open(inp_path, "r", encoding="utf8", errors="ignore") as fh:
            for zeile in fh:
                zu = zeile.strip()
                if zu.startswith("*"):
                    attrs = _attribute(zu)
                    if zu.upper().startswith("*SHELL SECTION") and attrs.get("ELSET"):
                        aktuell = attrs["ELSET"]
                        fehlt_noch = True
                        continue
                    aktuell, fehlt_noch = None, False
                    continue
                if not zu or not fehlt_noch or aktuell is None:
                    continue
                # the first number on the card is the thickness
                try:
                    dicken[aktuell] = float(zu.split(",")[0].strip())
                except ValueError:
                    pass
                fehlt_noch = False
    except OSError:
        return {}
    return dicken


def read_section_materials(inp_path):
    """Material per element set from the section cards: ``{elset: material name}``.

    FreeCAD writes the finished assignment into the input file::

        *SOLID SECTION, ELSET=MaterialSolidSolid, MATERIAL=MaterialSolid

    This makes it unambiguous which material CalculiX uses for this set - even
    when a model contains several materials.  It is therefore the truth and not
    the name of the set (which only *looks* like the material).
    """
    zuordnung = {}
    if not inp_path or not os.path.isfile(inp_path):
        return zuordnung
    try:
        with open(inp_path, "r", encoding="utf8", errors="ignore") as fh:
            for zeile in fh:
                zu = zeile.strip()
                if not zu.startswith("*"):
                    continue
                hoch = zu.upper()
                if not (hoch.startswith("*SOLID SECTION") or hoch.startswith("*SHELL SECTION")):
                    continue
                attrs = _attribute(zu)
                if attrs.get("ELSET") and attrs.get("MATERIAL"):
                    zuordnung[attrs["ELSET"]] = attrs["MATERIAL"]
    except OSError:
        return {}
    return zuordnung


def pruefe_inp(inp_path, sets=None):
    """Is the input file complete - and does every element set have a material?

    A file that was interrupted in the middle of writing does not always stand
    out: FreeCAD writes nodes, elements and materials and only then the
    section cards, the ``*STEP`` and the boundary conditions.  CalculiX then
    computes nothing, the result file stays empty, and beso only reports
    "CalculiX results not found" - without saying what the cause is.

    In addition every element set the optimization knows about needs a
    section card (``*SOLID SECTION``/``*SHELL SECTION``).  If it is missing, the
    set belongs to no body-material assignment (typical: a material was placed
    on surfaces) and CalculiX leaves the elements out.

    Returns ``{"vorhanden": bool, "fehlende_karten": [card, ...],
    "ohne_material": [set, ...]}``
    """
    ergebnis = {"vorhanden": False, "fehlende_karten": [], "ohne_material": []}
    if not inp_path or not os.path.isfile(inp_path):
        return ergebnis
    ergebnis["vorhanden"] = True
    karten = {"*STEP": False, "*MATERIAL": False}
    section_sets = set()
    try:
        with open(inp_path, "r", encoding="utf8", errors="ignore") as fh:
            for zeile in fh:
                if not zeile.startswith("*"):
                    continue
                hoch = zeile.strip().upper()
                for name in karten:
                    if hoch.startswith(name):
                        karten[name] = True
                if hoch.startswith("*SOLID SECTION") or hoch.startswith("*SHELL SECTION"):
                    elset = _attribute(zeile).get("ELSET")
                    if elset:
                        section_sets.add(elset)
    except OSError:
        return ergebnis
    # *MATERIAL and *STEP stand in the second half: if one is missing, the file was
    # interrupted while writing (boundary conditions are deliberately NOT checked -
    # a model can also be written without them)
    ergebnis["fehlende_karten"] = [name for name in ("*MATERIAL", "*STEP")
                                   if not karten[name]]
    if sets:
        ergebnis["ohne_material"] = sorted(name for name in sets if name not in section_sets)
    return ergebnis


def gesamt_elemente(inp_path):
    """Number of elements in the mesh (from the *ELEMENT cards)."""
    roh = _rohdaten(inp_path)
    return max([anzahl for anzahl, _ in roh.values()] or [0])


def element_types(inp_path):
    """Set of element types from the *ELEMENT cards, e. g. ["C3D10"]."""
    typen = []
    if not inp_path or not os.path.isfile(inp_path):
        return typen
    try:
        with open(inp_path, "r", encoding="utf8", errors="ignore") as fh:
            for zeile in fh:
                if not zeile.lstrip().upper().startswith("*ELEMENT"):
                    continue
                typ = _attribute(zeile).get("TYPE", "").upper()
                if typ and typ not in typen:
                    typen.append(typ)
    except OSError:
        pass
    return typen
