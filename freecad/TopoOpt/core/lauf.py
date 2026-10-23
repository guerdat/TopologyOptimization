# SPDX-License-Identifier: LGPL-3.0-or-later
"""Read the progress of a beso run from its log files.

beso writes two files next to the input file:

* ``<mesh>.log`` - beso's own protocol.  It contains the **table of iterations**,
  which is the source for the charts::

       i              mass    ener_dens_mean
       0 19999.99999999998                0.0
       1 19369.413573798036                0.0

  With a failure index (``domain_FI``) the table has four more columns
  (``FI_violated``, ``FI_mean``, ``FI_mean_without_state0``, ``FI_max``).
* ``<mesh>_topoopt.log`` - what the run prints (CalculiX output); this addon writes it
  and shows the last lines in the "Details" field.

Nothing here blocks: the files are simply read while the run goes on.
"""

import os
import re

START = re.compile(r"initial optimization domains mass\s+([0-9.eE+-]+)")
ITERATION = re.compile(r"new iteration number\s+(\d+)")
MASSE = re.compile(r"^mass\s*=\s*([0-9.eE+-]+)", re.MULTILINE)

# The iteration table has a different number of columns depending on the model: the
# header starts with "i  mass  ener_dens_mean" (or heat_flux_mean) and gets more with
# a failure index: FI_violated per domain (plus "all" when there is more than one
# domain), FI_mean, FI_mean_without_state0 and FI_max per domain (also with "all").
# Measured: 3 columns, 4 with a failure index and one domain, 8 with two domains -
# which is why the columns are assigned through the header.
KOPF_MERKMALE = {"mass": "mass", "ener_dens_mean": "ener", "heat_flux_mean": "ener",
                 "FI_mean": "fi_mean", "_without_state0": "fi_mean_ohne"}


def _kopf_positionen(zeile):
    """Positions of the known columns, taken from the header row of the iteration table."""
    tokens = zeile.split()
    positionen = {}
    for nummer, token in enumerate(tokens):
        for merkmal, name in KOPF_MERKMALE.items():
            if token == merkmal or (merkmal.startswith("FI_") and token.startswith(merkmal)):
                positionen[name] = nummer
    if "fi_mean" in positionen:
        # the combined "all" column sits directly before FI_mean, otherwise it is the only domain
        positionen["fi_violated"] = positionen["fi_mean"] - 1
    if positionen.get("fi_mean"):
        # FI_max: the last column of the table is "all" (or the only domain)
        positionen["fi_max"] = len(tokens) - 1
    return positionen


def tabelle_lesen(beso_log):
    """The iteration table from beso's log file.

    Returns [(iteration, {"mass":…, "ener":…, "fi_violated":…, "fi_mean":…, "fi_max":…}), …]
    in the order of the file; an empty list when the file does not exist.
    """
    ergebnis = []
    if not beso_log or not os.path.isfile(beso_log):
        return ergebnis
    positionen = {}
    try:
        with open(beso_log, encoding="utf8", errors="replace") as fh:
            for zeile in fh:
                if "mass" in zeile and ("ener_dens_mean" in zeile or "heat_flux_mean" in zeile):
                    positionen = _kopf_positionen(zeile)
                    continue
                if not positionen:
                    continue
                felder = zeile.split()
                if len(felder) <= max(positionen.values()):
                    continue
                if not felder[0].isdigit():
                    continue
                try:
                    werte = {"mass": float(felder[positionen["mass"]]),
                             "ener": float(felder[positionen["ener"]])}
                    for name in ("fi_violated", "fi_mean", "fi_mean_ohne", "fi_max"):
                        if name in positionen:
                            werte[name] = float(felder[positionen[name]])
                    if "fi_violated" in werte:
                        werte["fi_violated"] = int(werte["fi_violated"])
                except (TypeError, ValueError, IndexError):
                    continue
                ergebnis.append((int(felder[0]), werte))
    except OSError:
        return []
    return ergebnis


def fortschritt(beso_log, ziel_anteil=None):
    """What the table says about the run.

    Returns a dict with ``start`` (mass of iteration 0), ``ziel`` (when
    ``ziel_anteil`` is given), ``iteration``, ``masse``, ``massen`` [(i, mass), …] and
    ``werte`` (the whole table for the charts).
    """
    tabelle = tabelle_lesen(beso_log)
    ergebnis = {"start": None, "ziel": None, "iteration": 0, "masse": None, "massen": [],
                "werte": tabelle}
    if not tabelle:
        return ergebnis
    ergebnis["start"] = tabelle[0][1].get("mass")
    ergebnis["iteration"] = tabelle[-1][0]
    ergebnis["masse"] = tabelle[-1][1].get("mass")
    ergebnis["massen"] = [(i, werte.get("mass")) for i, werte in tabelle]
    if ergebnis["start"] and ziel_anteil:
        ergebnis["ziel"] = ergebnis["start"] * float(ziel_anteil)
    return ergebnis


def anteil(start, masse, ziel_anteil):
    """How far the run has come, in percent (0 = start mass, 100 = target mass)."""
    if not start or not masse:
        return 0.0
    ziel = min(max(float(ziel_anteil or 0.0), 0.01), 0.99)
    return max(0.0, min(100.0, (start - masse) / (start * (1.0 - ziel)) * 100.0))


def verlauf_lesen(log_pfad, ziel_anteil=None):
    """Our own protocol (<mesh>_topoopt.log) for the details field.

    Returns a dict with ``text`` (whole file), ``iteration``, ``massen`` and ``fertig``.
    """
    ergebnis = {"text": "", "iteration": 0, "massen": [], "fertig": False,
                "start": None, "ziel": None}
    if not log_pfad or not os.path.isfile(log_pfad):
        return ergebnis
    try:
        with open(log_pfad, encoding="utf8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ergebnis
    ergebnis["text"] = text
    start = START.search(text)
    if start:
        try:
            ergebnis["start"] = float(start.group(1))
            if ziel_anteil:
                ergebnis["ziel"] = ergebnis["start"] * float(ziel_anteil)
        except ValueError:
            pass
    laufende = 0
    for zeile in text.splitlines():
        nummer = ITERATION.search(zeile)
        if nummer:
            laufende = int(nummer.group(1))
            ergebnis["iteration"] = max(ergebnis["iteration"], laufende)
            continue
        masse = MASSE.match(zeile.strip())
        if masse and laufende:
            try:
                ergebnis["massen"].append((laufende, float(masse.group(1))))
            except ValueError:
                continue
    if "Job finished" in text:
        ergebnis["fertig"] = True
    return ergebnis
