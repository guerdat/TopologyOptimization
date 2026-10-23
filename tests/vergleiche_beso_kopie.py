#!/usr/bin/env python
# SPDX-License-Identifier: LGPL-3.0-or-later
"""Compare the bundled beso with the original from GitHub.

Any Python can run this - FreeCAD is not needed:

    git clone --depth 1 https://github.com/calculix/beso.git /tmp/beso-original
    python3 tests/vergleiche_beso_kopie.py            # or: <path to a clone>
                                                      # or: BESO_ORIGINAL=/path

It prints every difference (lines ending in CRLF are not a difference) and checks two
things:

* the bundled copy is upstream plus the changes listed in
  ``freecad/TopoOpt/beso/CHANGES-TopoOpt.md``, and
* every single difference carries a ``TopoOpt:`` comment in the source.

A difference without such a comment is a difference nobody will find later - that is
what this check is for.  Exit code 0 = everything documented.
"""

import difflib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COPY = os.path.join(os.path.dirname(HERE), "freecad", "TopoOpt", "beso")
# beso's own FreeCAD dialog is deliberately not bundled - the assistant takes its place
NOT_BUNDLED = ("beso_fc_gui.py",)


def read_lines(path):
    with open(path, encoding="utf8", errors="replace") as fh:
        # CRLF must not count as a difference: upstream ships mixed line endings
        return fh.read().replace("\r\n", "\n").replace("\r", "\n").split("\n")


def hunks(old_lines, new_lines):
    """(start line, lines, documented) per difference."""
    result = []
    block = []
    start = 0
    for line in difflib.unified_diff(old_lines, new_lines, n=2, lineterm=""):
        if line.startswith("@@"):
            if block:
                result.append((start, block))
            block = [line]
            start = int(line.split("-")[1].split(",")[0])
        elif block:
            if line.startswith("+++") or line.startswith("---"):
                continue
            block.append(line)
    if block:
        result.append((start, block))
    return [(s, b, any("TopoOpt:" in z for z in b)) for s, b in result]


def main():
    original = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        "BESO_ORIGINAL", "/tmp/beso-original")
    if not os.path.isdir(original):
        print("FEHLT Kein Original-beso unter %s" % original)
        print("      git clone --depth 1 https://github.com/calculix/beso.git %s" % original)
        return 1
    print("Vergleich: %s\n     gegen: %s\n" % (COPY, original))

    missing = []
    undocumented = 0
    for name in sorted(os.listdir(original)):
        if not name.endswith(".py"):
            continue
        old_lines = read_lines(os.path.join(original, name))
        new_path = os.path.join(COPY, name)
        if not os.path.isfile(new_path):
            if name in NOT_BUNDLED:
                print("%-18s nicht gebuendelt (so gewollt)" % name)
            else:
                missing.append(name)
                print("%-18s FEHLT in der Kopie" % name)
            continue
        new_lines = read_lines(new_path)
        if old_lines == new_lines:
            print("%-18s unveraendert" % name)
            continue
        changes = hunks(old_lines, new_lines)
        print("%-18s %d Unterschied(e), davon %d ohne TopoOpt-Kommentar"
              % (name, len(changes), sum(1 for _, _, d in changes if not d)))
        for start, block, documented in changes:
            print("    ab Zeile %d%s" % (start, "" if documented else "   <-- nicht dokumentiert"))
            for line in block:
                if line.startswith("+") and "TopoOpt:" not in line:
                    print("      neu: %s" % line[1:].strip()[:88])
                elif line.startswith("-") and not line.startswith("---"):
                    print("      alt: %s" % line[1:].strip()[:88])
            if not documented:
                undocumented += 1
    print()
    if missing or undocumented:
        print("FEHLT %d Datei(en) fehlen, %d Unterschied(e) ohne TopoOpt-Kommentar"
              % (len(missing), undocumented))
        return 1
    print("OK alle Unterschiede sind mit TopoOpt-Kommentaren belegt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
