# SPDX-License-Identifier: LGPL-3.0-or-later
"""Performance comparison: unmodified beso from GitHub against the bundled beso.

Measured on **the same model** are the preparation time (reading the mesh,
volume/centre of gravity, element sizes, neighbourhood grid) and the total time of a
run.  That shows that the addon's fixes neither change nor slow down the
computation.

Clone the original first::

    git clone --depth 1 https://github.com/calculix/beso.git
    set BESO_ORIGINAL=C:\\path\\to\\beso-original      (Windows)
    export BESO_ORIGINAL=/path/to/beso-original        (Linux/macOS)

Call (FreeCAD's Python or freecadcmd)::

    python tests/vergleich_varianten.py [modell.inp] [elset]

Without arguments the largest mesh from the FreeCAD working directories is used.
Writes ``vergleich_varianten.md`` next to the script.
"""
import glob
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(HERE, "vergleich_varianten.md")
# original beso: cloned upstream state (see the module docstring)
ORIGINAL = os.environ.get("BESO_ORIGINAL", os.path.join(tempfile.gettempdir(), "beso-original"))
# bundled copy of the addon (this repo)
ADDON = os.path.join(os.path.dirname(HERE), "freecad", "TopoOpt", "beso")

VARIANTS = (("beso (GitHub, unveraendert)", ORIGINAL), ("beso im Addon", ADDON))

def _python():
    """Interpreter without a FreeCAD start - beso needs only Python and numpy."""
    sibling = os.path.join(os.path.dirname(sys.executable), "python.exe")
    return sibling if os.path.isfile(sibling) else sys.executable


PYTHON = os.environ.get("BESO_PYTHON") or _python()


def largest_inp():
    candidates = glob.glob(os.path.join(tempfile.gettempdir(), "fcfem_*", "*.inp"))
    return sorted(candidates, key=os.path.getsize)[-1] if candidates else ""


def elset_from_inp(path):
    text = open(path, encoding="utf8", errors="ignore").read()
    names = re.findall(r"^\*ELSET,\s*ELSET=([^\s,]+)", text, re.M)
    names += re.findall(r"^\*ELEMENT,\s*TYPE=\w+,\s*ELSET=([^\s,]+)", text, re.M)
    without_collectors = [n for n in names if n.lower() not in ("eall", "efaces", "evolumes")]
    return sorted(without_collectors)[0] if without_collectors else ""


def measure(beso_folder, inp, elset):
    """Measure one beso copy in its own process (each brings its own modules)."""
    script = os.path.join(HERE, "messung_beso.py")
    start = time.time()
    process = subprocess.run([PYTHON, script, beso_folder, inp, elset],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=3600)
    text = process.stdout.decode("utf8", "replace")
    lines = [z for z in text.splitlines() if z.startswith("MESSUNG|")]
    if not lines:
        last = [z for z in text.splitlines() if z.strip()]
        return {"error": last[-1][:120] if last else "keine Ausgabe",
                "total": time.time() - start}
    values = lines[-1].split("|")[1:]
    return {"import": float(values[0]), "cg": float(values[1]), "size": float(values[2]),
            "prep": float(values[3]), "elements": int(values[4]), "pairs": int(values[5]),
            "mean_size": float(values[6]), "total": time.time() - start}


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else largest_inp()
    if not inp or not os.path.isfile(inp):
        print("kein Modell gefunden - bitte eine .inp angeben")
        return
    elset = sys.argv[2] if len(sys.argv) > 2 else elset_from_inp(inp)
    if not elset:
        print("im Modell ist kein Element-Set gefunden worden")
        return

    lines = ["# Leistungsvergleich der beso-Kopien", "",
              "Modell: `%s` (%.1f MB), Element-Set `%s`"
              % (os.path.basename(inp), os.path.getsize(inp) / 1e6, elset), "",
              "| Variante | Netz lesen | Volumen/CG | Elementgroessen | Nachbarschaftsgitter "
              "| Summe | Elemente | Nachbarpaare |",
              "|---|---|---|---|---|---|---|---|"]
    results = {}
    for name, folder in VARIANTS:
        if not os.path.isdir(folder):
            lines.append("| %s | - | - | - | - | - | - | nicht gefunden: `%s` |" % (name, folder))
            print("fehlt: %s" % folder, flush=True)
            continue
        e = measure(folder, inp, elset)
        results[name] = e
        if "error" in e:
            lines.append("| %s | - | - | - | - | - | - | Fehler: %s |" % (name, e["error"]))
            print("%-28s Fehler: %s" % (name, e["error"]), flush=True)
            continue
        line = ("| %s | %.2f s | %.2f s | %.2f s | **%.2f s** | %.2f s | %d | %d |"
                 % (name, e["import"], e["cg"], e["size"], e["prep"],
                    e["import"] + e["cg"] + e["size"] + e["prep"], e["elements"], e["pairs"]))
        lines.append(line)
        print(line, flush=True)
    lines.append("")

    valid = [e for e in results.values() if "error" not in e]
    if len(valid) == 2 and valid[0]["pairs"] == valid[1]["pairs"] \
            and abs(valid[0]["mean_size"] - valid[1]["mean_size"]) < 1e-9:
        lines.append("Beide Kopien finden dieselbe mittlere Elementgroesse (%.4f mm) und "
                      "dieselbe Zahl Nachbarpaare (%d) - das Ergebnis der Rechnung ist "
                      "identisch." % (valid[0]["mean_size"], valid[0]["pairs"]))
    with open(REPORT, "w", encoding="utf8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("Bericht: %s" % REPORT)


main()
