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
UNITS = {
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

NUMBER = re.compile(r"^\s*([-+0-9.eE,]+)\s*([A-Za-z0-9/().^*² ]*)\s*$")

# keys that may contain a yield strength (order = priority)
KEYS = ("YieldStrength", "UltimateTensileStrength", "CompressiveStrength")


def MPa(value):
    """Convert a material value to MPa - or None when it is unusable."""
    if isinstance(value, (int, float)):
        return float(value) or None
    if not isinstance(value, str):
        return None
    match = NUMBER.match(value.replace(",", "."))
    if not match:
        return None
    try:
        number = float(match.group(1))
    except ValueError:
        return None
    unit = match.group(2).strip().lower().replace(" ", "")
    factor = UNITS.get(unit)
    if factor is None:
        if not unit:
            factor = 1.0                 # no unit: read as MPa
        else:
            return None                  # unknown unit - better suggest nothing
    result = number * factor
    return result if result > 0 else None


def yield_strength(materials, elsets, from_inp=None):
    """What the material of the element sets yields.

    ``materials`` is a list of ``(name, values dict)`` (see
    ``find_materials``), ``elsets`` the set of element sets.

    The mapping is made first through ``from_inp`` - the assignment set -> material
    name that FreeCAD writes into the input file (``*SOLID SECTION, ELSET=...,
    MATERIAL=...``, see ``elsets.read_section_materials``).  That is the truth:
    CalculiX computes with exactly this material.  Only when the input file has
    no assignment (yet) is the mapping made through the name prefix
    ('MaterialSolid' belongs to 'MaterialSolidSolid'); if there is only one
    material, it applies to all sets without a material of their own.

    Returns {"<elset>": MPa}
    """
    result = {}
    entries = [(name, values) for name, values in materials if isinstance(values, dict)]
    for elset in elsets:
        matching = None
        name_in_inp = (from_inp or {}).get(elset)
        if name_in_inp:
            for name, values in entries:
                if name == name_in_inp:
                    matching = values
                    break
        if matching is None:
            for name, values in entries:
                if name and elset.lower().startswith(name.lower()):
                    matching = values
                    break
        if matching is None and len(entries) == 1:
            matching = entries[0][1]
        if matching is None:
            continue
        for key in KEYS:
            if key in matching:
                value = MPa(matching[key])
                if value:
                    result[elset] = value
                    break
    return result


def missing_values(materials):
    """Which material values that CalculiX needs for computing are missing.

    ``materials`` is a list of ``(name, values dict)`` (see
    ``find_materials``).  FreeCAD's input file writer aborts without a
    Young's modulus with a bare ``KeyError: 'YoungsModulus'`` and leaves a
    half-finished ``.inp`` behind.  So that this stands out beforehand, this
    function reports per material what is missing.

    Returns ``{"<material name>": ["YoungsModulus", ...]}``
    """
    missing = {}
    for name, values in materials:
        if not isinstance(values, dict):
            continue
        missing_keys = [key for key in ("YoungsModulus", "PoissonRatio")
                        if key not in values]
        if missing_keys:
            missing[name] = missing_keys
    return missing


def find_materials(analysis):
    """The material objects of the model as [(name, values dict), ...].

    Searches in the analysis and - if necessary - in the whole document (FreeCAD
    places material objects next to the analysis).  Without an analysis the active
    document is taken, so the suggestion also works without a selected analysis.
    """
    result = []
    candidates = []
    if analysis is not None:
        for member in getattr(analysis, "Group", []) or []:
            candidates.append(member)
    try:
        import FreeCAD as App
        doc = getattr(analysis, "Document", None) or getattr(App, "ActiveDocument", None)
        if doc is not None:
            for obj in doc.Objects:
                if obj not in candidates:
                    candidates.append(obj)
    except Exception:
        pass
    for obj in candidates:
        if not str(getattr(obj, "TypeId", "")).startswith("App::MaterialObject"):
            continue
        values = getattr(obj, "Material", None)
        if isinstance(values, dict):
            result.append((obj.Name, values))
    return result
