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
COLLECTOR_SETS = ("eall", "all_available", "evolumes", "efaces", "eedges", "enodes")


def active(domains):
    """The domains that take part in the optimization.

    "ignore" means: these elements play no role for the optimization.
    Such sets do not go into the beso configuration - then they need no
    allowable stress either and are not evaluated.
    """
    return {name: role for name, role in (domains or {}).items() if role != IGNORE}


def parse_domains(values):
    """["set|design", ...] -> {"set": "design"}."""
    result = {}
    for entry in values or []:
        if "|" not in entry:
            continue
        name, role = entry.split("|", 1)
        name = name.strip()
        if name:
            result[name] = role.strip()
    return result


def format_domains(domains):
    """{"set": "design"} -> ["set|design", ...] (stable order)."""
    return ["%s|%s" % (name, domains[name]) for name in sorted(domains)]


def parse_stress(values):
    """["set|235.0", ...] -> {"set": 235.0} (allowable stress in MPa)."""
    result = {}
    for entry in values or []:
        if "|" not in entry:
            continue
        name, value = entry.split("|", 1)
        name = name.strip()
        try:
            number = float(value.strip().replace(",", "."))
        except ValueError:
            continue
        if name and number > 0:
            result[name] = number
    return result


def format_stress(limits, blank=None):
    """{"set": 235.0} -> ["set|235.0", ...] (stable order).

    ``blank`` are the sets with a **deliberately** empty field: they are stored as
    "<set>|0" so that the suggestion from the material does not reappear.
    """
    result = ["%s|%r" % (name, limits[name]) for name in sorted(limits)]
    result += ["%s|0" % name for name in sorted(set(blank or ()) - set(limits))]
    return result


def blank_stress(values):
    """The sets stored as "<set>|0" (deliberately without stress)."""
    result = set()
    for entry in values or []:
        if "|" not in entry:
            continue
        name, value = entry.split("|", 1)
        try:
            number = float(value.strip().replace(",", "."))
        except ValueError:
            continue
        if name.strip() and number <= 0:
            result.add(name.strip())
    return result


def suggestion(elsets):
    """A first suggestion for the incoming sets.

    Every set starts as design space - that is what a user means when a model is
    built and nothing has been decided yet.  Areas that must be kept (bearings,
    screws, ...) are set to "non-design", areas that should not take part at all to
    "ignore".  Sets that only collect everything (Eall) are not offered at all.
    """
    suggestions = {}
    for name in elsets:
        if name.lower() in COLLECTOR_SETS:
            continue
        suggestions[name] = DESIGN
    return suggestions


def roles_for(elsets, stored=None):
    """The roles of the offered sets.

    What is stored in the object stays valid.  Everything new - for example a set
    that only appeared after a model change - is **design space**:
    "ignore" is the exception that is set deliberately.
    """
    if not stored:
        return suggestion(elsets)
    return {name: stored.get(name, DESIGN) for name in elsets}


def visible_elsets(elsets):
    """Sets for the table: collector sets are hidden."""
    return {name: count for name, count in elsets.items() if name.lower() not in COLLECTOR_SETS}
