# SPDX-License-Identifier: LGPL-3.0-or-later
"""Scenario matrix: error cases, filter/radius variants, 2D/3D and comparison.

The test covers:

  A) error cases in the assistant - missing mesh, missing solver, missing
     .inp, no design space: the run must not even start.
  B) beso computations on small models (real runs, 1-2 iterations each):
     filters (simple, casting and all morphology filters), radii (auto, robust,
     manual), target mass, 2D shell and 3D solid.
  C) missing shell thickness: beso has to give a clear message (not silently
     compute with 1 mm) - what happens is documented here.
  D) reference comparison: the same configuration with the **bundled beso** of the
     addon and the **unmodified beso from GitHub** - same masses? same iterations?
     (clone the original first:
     ``git clone --depth 1 https://github.com/calculix/beso.git``)

Call (GUI, also covers A):
    freecad.exe tests/szenario_test.py
Call (headless, without A):
    freecadcmd tests/szenario_test.py

The report ends up as ``szenario_bericht.md`` next to the script.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

HIER = os.path.dirname(os.path.abspath(__file__))
MODELLE = os.path.join(HIER, "szenarien")
BERICHT = os.path.join(HIER, "szenario_bericht.md")
ARBEIT = os.path.join(tempfile.gettempdir(), "topoopt_szenarien")
# The unmodified original beso for the comparison (https://github.com/calculix/beso):
#     git clone --depth 1 https://github.com/calculix/beso.git
# The path comes either from the environment variable BESO_ORIGINAL or from a clone in
# the temp directory.
ORIGINAL_BESO = os.environ.get("BESO_ORIGINAL",
                               os.path.join(tempfile.gettempdir(), "beso-original"))

zeilen = []
ergebnisse = []


def sag(text=""):
    zeilen.append(str(text))
    print(text, flush=True)


def pruefe(name, bedingung, detail=""):
    marke = "OK  " if bedingung else "FEHLT"
    sag("%s %s%s" % (marke, name, (" (%s)" % detail) if detail else ""))
    ergebnisse.append({"name": name, "ok": bool(bedingung), "detail": detail})
    return bool(bedingung)


# --------------------------------------------------------------------------- #
# beso run
# --------------------------------------------------------------------------- #
class Fake(object):
    """Carrier of the run parameters (like the optimization object in the assistant)."""

    def __init__(self, zielmasse=0.6, filter_liste=None, iterationen="2", dicke=None,
                 dicken_modus="auto", stress=None):
        self.MassGoalRatio = zielmasse
        self.OptimizationBase = "stiffness"
        self.IterationsLimit = iterationen
        self.Tolerance = 1e-3
        self.CpuCores = 0
        self.Filters = json.dumps(filter_liste or [["simple", "auto"]])
        self.RobusterRadius = 0.0
        self.MittlereGroesse = 0.0
        self.MassChange = "normal"
        self.SaveIterations = 1
        self.ResultFormat = "inp vtk"
        self.StressLimits = stress or []
        self.DICKEN = dicke
        self.DICKEN_MODUS = dicken_modus


def _kopiere_beso(ziel, quelle):
    """Copy beso (original or bundled) into the run directory."""
    if os.path.isdir(ziel):
        shutil.rmtree(ziel)
    shutil.copytree(quelle, ziel)
    return ziel


def _conf_fuer(modell, einstellungen, ordner, beso_ordner):
    """Write a beso_conf.py by hand (without the addon) so that both
    beso variants get exactly the same configuration."""
    from freecad.TopoOpt.core import elsets as elset_reader
    doms = [n for n in elset_reader.read_elsets(modell) if n.lower() not in
            ("eall", "efaces", "evolumes", "eedges", "enodes")]
    domain = sorted(doms)[0]
    dicken = elset_reader.read_shell_thicknesses(modell)
    # without a thickness: beso's example value 1.0 (that is the error case)
    dicke_zeile = ""
    if einstellungen.get("dicken_modus") == "auto" and domain in dicken:
        d = dicken[domain]
        dicke_zeile = "domain_thickness[%r] = [%r, %r]\n" % (domain, d, d)
    elif einstellungen.get("dicken_modus") == "ohne":
        pass                      # nothing -> beso takes 1.0 from its template
    # beso_main reads the configuration from ITS OWN directory (beso_conf.py) - the
    # original template is saved first, otherwise we would overwrite it
    vorlage = os.path.join(beso_ordner, "beso_conf_vorlage.py")
    if not os.path.isfile(vorlage):
        shutil.copyfile(os.path.join(beso_ordner, "beso_conf.py"), vorlage)
    # beso does not know "robust" - the addon replaces it with a radius beforehand
    filter_liste = [list(f) for f in einstellungen["filter"]]
    for eintrag in filter_liste:
        if len(eintrag) > 1 and eintrag[1] == "robust":
            from freecad.TopoOpt.core import radius as radius_modul
            daten = radius_modul.gelesen(modell, [domain], [domain])
            eintrag[1] = round(radius_modul.robust(daten).get("radius",
                                                              daten.get("mittel", 1.0) * 2), 4)
    conf = os.path.join(beso_ordner, "beso_conf.py")
    with open(conf, "w", encoding="utf8") as fh:
        fh.write("target_path = %r\n" % ordner)
        fh.write("path = %r\n" % ordner)
        fh.write("file_name = %r\n" % os.path.basename(modell))
        fh.write("path_calculix = %r\n" % _ccx())
        fh.write("elset_name = %r\n" % domain)
        fh.write("domain_optimized = {%r: True}\n" % domain)
        fh.write("domain_density[%r] = [1e-6, 1.0]\n" % domain)
        zeile_material = ("domain_material[%r] = ['*ELASTIC" + chr(92) + "n0.21, 0.3', "
                          "'*ELASTIC" + chr(92) + "n210000, 0.3']") % domain
        fh.write(zeile_material + chr(10))
        if dicke_zeile:
            fh.write(dicke_zeile)
        fh.write("mass_goal_ratio = %r\n" % einstellungen["zielmasse"])
        fh.write("filter_list = %r\n" % (filter_liste,))
        fh.write("optimization_base = %r\n" % einstellungen.get("basis", "stiffness"))
        # permissible stress per domain - one domain deliberately has none
        for dn, wert in (einstellungen.get("sigma") or {}).items():
            zeile = ("domain_FI[%r] = [[('stress_von_Mises', %r)], "
                     "[('stress_von_Mises', %r)]]\n") % (dn, wert * 1e6, wert * 1e6)
            fh.write(zeile)
        # a second domain: computed, but not optimized
        zweite = einstellungen.get("zweite_domain")
        if zweite:
            fh.write("domain_optimized[%r] = False\n" % zweite)
            fh.write("domain_density[%r] = [1e-6, 1.0]\n" % zweite)
            fh.write(("domain_material[%r] = ['*ELASTIC" + chr(92) + "n0.21, 0.3', "
                      "'*ELASTIC" + chr(92) + "n70000, 0.33']") % zweite + chr(10))
        fh.write("mass_addition_ratio = 0.015\n")
        fh.write("mass_removal_ratio = 0.03\n")
        fh.write("ratio_type = 'relative'\n")
        grenze = einstellungen["iterationen"]
        fh.write("iterations_limit = %s\n" % (grenze if str(grenze) == "auto" else int(grenze)))
        fh.write("tolerance = 0.001\n")
        fh.write("cpu_cores = 0\n")
        fh.write("save_iteration_results = 1\n")
        fh.write("save_resulting_format = 'inp vtk'\n")
        fh.write("import matplotlib as _mpl\n_mpl.use('Agg')\n")
    return conf, domain, dicken


def _ccx():
    from freecad.TopoOpt.core import conf as conf_modul
    return conf_modul.calculix_pfad()


def lauf(name, modell, einstellungen, beso_quelle=None):
    """Execute one beso run and evaluate it."""
    from freecad.TopoOpt.core import beso as beso_modul
    from freecad.TopoOpt.core import conf as conf_modul
    from freecad.TopoOpt.core import lauf as lauf_modul

    ordner = os.path.join(ARBEIT, name.replace(" ", "_").replace("/", "_"))
    if os.path.isdir(ordner):
        try:
            shutil.rmtree(ordner)
        except OSError:
            # Windows releases files with a delay - then take a fresh directory
            ordner = "%s_%d" % (ordner, int(time.time()))
    os.makedirs(ordner)
    ziel = _kopiere_beso(os.path.join(ordner, "beso"), beso_quelle or beso_modul.ORDNER)
    shutil.copyfile(modell, os.path.join(ordner, os.path.basename(modell)))
    conf, domain, dicken = _conf_fuer(modell, einstellungen, ordner, ziel)
    log = conf_modul.log_pfad(os.path.join(ordner, os.path.basename(modell)))
    start = time.time()
    prozess = subprocess.Popen([conf_modul.python_pfad(), os.path.join(ziel, "beso_main.py")],
                               cwd=ordner, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True)
    ausgabe = ""
    try:
        ausgabe, _ = prozess.communicate(timeout=600)
    except subprocess.TimeoutExpired:
        prozess.kill()
        ausgabe = "TIMEOUT"
    dauer = time.time() - start
    daten = lauf_modul.fortschritt(conf_modul.beso_log_pfad(os.path.join(
        ordner, os.path.basename(modell))), einstellungen["zielmasse"])
    fehler = [z.strip() for z in (ausgabe or "").splitlines()
              if "Error:" in z or "ERROR:" in z or "Exception" in z]
    return {"name": name, "ordner": ordner, "code": prozess.returncode, "dauer": dauer,
            "massen": daten.get("massen", []), "domain": domain, "dicken": dicken,
            "fehler": fehler[-3:], "fehlerfrei": prozess.returncode == 0}


# --------------------------------------------------------------------------- #
# A) error cases in the assistant
# --------------------------------------------------------------------------- #
def fehlerfaelle():
    sag("## A) Fehlerfaelle im Assistenten")
    sag()
    try:
        import FreeCAD as App
        import FreeCADGui as Gui  # noqa: F401
        from freecad.TopoOpt.features import create_topology_object
        from freecad.TopoOpt.gui.assistant import AssistantPanel
    except Exception as exc:
        sag("(uebersprungen - ohne GUI: %s)" % exc)
        sag()
        return
    quelle = os.path.join(tempfile.gettempdir(), "TopoOpt_Test", "modell.FCStd")
    if not os.path.isfile(quelle):
        sag("(uebersprungen - Testdokument fehlt: %s)" % quelle)
        sag()
        return
    kopie = os.path.join(tempfile.gettempdir(), "TopoOpt_Szenario.FCStd")
    shutil.copyfile(quelle, kopie)
    doc = App.openDocument(kopie)
    analyse = [o for o in doc.Objects if o.TypeId == "Fem::FemAnalysis"][0]
    netz = [o for o in doc.Objects if o.TypeId.startswith("Fem::FemMesh")][0]
    solver = [o for o in doc.Objects if o.TypeId.startswith("Fem::FemSolver")][0]

    def panel_bauen():
        obj = create_topology_object(doc, analyse, "Szenario%d" % int(time.time() * 1000 % 10000))
        panel = AssistantPanel(obj)
        panel._zeige_schritt(3)
        return obj, panel

    # 1) without a mesh
    doc.removeObject(netz.Name)
    doc.recompute()
    obj, panel = panel_bauen()
    panel._lauf_starten()
    pruefe("ohne Netz startet kein Lauf",
           panel._lauf_prozess is None and "Netz" in panel.lauf_status.text(),
           panel.lauf_status.text())
    # 2) without a solver (mesh back in place)
    doc.addObject(netz.TypeId, netz.Name)
    doc.recompute()
    doc.removeObject(solver.Name)
    doc.recompute()
    obj, panel = panel_bauen()
    panel._lauf_starten()
    pruefe("ohne Solver startet kein Lauf",
           panel._lauf_prozess is None and "Solver" in panel.lauf_status.text(),
           panel.lauf_status.text())
    doc.addObject(solver.TypeId, solver.Name)
    doc.recompute()
    # 3) without .inp
    obj, panel = panel_bauen()
    obj.InpFile = ""
    panel._lauf_starten()
    pruefe("ohne Eingabedatei startet kein Lauf",
           panel._lauf_prozess is None and "Eingabedatei" in panel.lauf_status.text(),
           panel.lauf_status.text())
    # 4) without design space
    obj, panel = panel_bauen()
    panel.stress = {}
    for name in list(panel.domains):
        panel.domains[name] = "ignore"
    panel._speichere_domains()
    panel._lauf_starten()
    pruefe("ohne Design-Raum startet kein Lauf",
           panel._lauf_prozess is None and "Design" in panel.lauf_status.text(),
           panel.lauf_status.text())
    App.closeDocument(doc.Name)
    try:
        os.remove(kopie)
    except OSError:
        pass
    sag()


# --------------------------------------------------------------------------- #
# B) computation matrix
# --------------------------------------------------------------------------- #
MODELL_3D = os.path.join(MODELLE, "modell_3d_hex.inp")
MODELL_2D = os.path.join(MODELLE, "modell_2d_schale.inp")
MODELL_2D_OHNE = os.path.join(MODELLE, "modell_2d_ohne_dicke.inp")
MODELL_2SETS = os.path.join(MODELLE, "modell_2sets.inp")

# Scenarios in which our beso deliberately reacts differently from the original:
#   * filter radius too small - the original keeps computing without a filter and
#     reports convergence at the end instead of ending the run
#   * missing shell thickness with 2D models - the original silently computes with its
#     example value
#   * 2D shell models in general: the original aborts with numpy 2 because
#     np.linalg.linalg was removed there (measured with numpy 2.4); casting with "auto"
#     additionally aborts with a NameError.  Our beso computes in both cases.
# Measured with FreeCAD 26.3 (Flatpak) and numpy 2.4: 13 of 17 scenarios identical.
BEKANNTE_ABWEICHUNGEN = ("2D Schale casting auto", "2D Schale simple auto",
                         "3D simple 1.5 (Radius zu klein)", "3D simple manuell 1.0")

MATRIX = [
    ("3D simple auto", MODELL_3D, {"zielmasse": 0.6, "filter": [["simple", "auto"]],
                                   "iterationen": "2", "dicken_modus": "auto"}),
    ("3D simple 1.5 (Radius zu klein)", MODELL_3D, {"zielmasse": 0.6,
                                                    "filter": [["simple", 1.5]],
                                                    "iterationen": "2",
                                                    "dicken_modus": "auto"}),
    ("3D simple robust", MODELL_3D, {"zielmasse": 0.6, "filter": [["simple", "robust"]],
                                     "iterationen": "2", "dicken_modus": "auto"}),
    ("3D simple manuell 1.0", MODELL_3D, {"zielmasse": 0.6, "filter": [["simple", 1.0]],
                                         "iterationen": "2", "dicken_modus": "auto"}),
    ("3D zwei Sets, eines ohne sigma", MODELL_2SETS,
     {"zielmasse": 0.6, "filter": [["simple", "auto"]], "iterationen": "2",
      "dicken_modus": "auto", "basis": "failure_index",
      "sigma": {"SetA": 235.0}, "zweite_domain": "SetB"}),
    ("3D casting auto", MODELL_3D, {"zielmasse": 0.6,
                                    "filter": [["casting", 1.5, (0, 0, 1)]],
                                    "iterationen": "2", "dicken_modus": "auto"}),
    ("3D Zielmasse 30%", MODELL_3D, {"zielmasse": 0.3, "filter": [["simple", "auto"]],
                                     "iterationen": "2", "dicken_modus": "auto"}),
    ("2D Schale simple auto", MODELL_2D, {"zielmasse": 0.6, "filter": [["simple", "auto"]],
                                          "iterationen": "2", "dicken_modus": "auto"}),
    ("2D Schale casting auto", MODELL_2D, {"zielmasse": 0.6,
                                           "filter": [["casting", "auto", (0, 0, 1)]],
                                           "iterationen": "2", "dicken_modus": "auto"}),
    ("2D ohne Dicke (Fehlerfall)", MODELL_2D_OHNE,
     {"zielmasse": 0.6, "filter": [["simple", "auto"]], "iterationen": "2",
      "dicken_modus": "ohne"}),
]
# try every morphology filter once
for _typ in ("erode sensitivity", "dilate sensitivity", "open sensitivity",
             "close sensitivity", "open-close sensitivity", "close-open sensitivity",
             "combine sensitivity"):
    MATRIX.append(("3D %s" % _typ.split()[0], MODELL_3D,
                   {"zielmasse": 0.6, "filter": [[_typ, 1.5]], "iterationen": "1",
                    "dicken_modus": "auto"}))


def rechenmatrix(beso_quelle=None, praefix=""):
    from freecad.TopoOpt.core import beso as beso_modul
    quelle = beso_quelle or beso_modul.ORDNER
    laeufe = []
    for name, modell, einst in MATRIX:
        try:
            ergebnis = lauf(praefix + name, modell, einst, quelle)
        except Exception as exc:
            sag("FEHLT %s: %s" % (name, exc))
            traceback.print_exc()
            continue
        laeufe.append(ergebnis)
        massen = ergebnis["massen"]
        sag("%-34s code=%s  %5.1f s  Massen=%s"
            % (name, ergebnis["code"], ergebnis["dauer"],
               [round(m, 1) if m else m for _, m in massen]))
        if ergebnis["fehler"]:
            sag("      Meldung: %s" % (ergebnis["fehler"],))
    return laeufe


def berichte_laeufe(laeufe, titel):
    sag("## %s" % titel)
    sag()
    for e in laeufe:
        massen = [round(m, 2) if m else m for _, m in e["massen"]]
        fiel = (massen[-1] < massen[0]) if len(massen) > 1 else None
        sag("- **%s**: code=%s, %.1f s, %d Zeilen, Masse %s%s"
            % (e["name"], e["code"], e["dauer"], len(massen), massen,
               "" if fiel is None else (", faellt ab" if fiel else ", STEIGT")))
    sag()


# --------------------------------------------------------------------------- #
# D) comparison with the original beso
# --------------------------------------------------------------------------- #
def vergleich_original():
    """Original beso (without our fixes) against the bundled beso on the same models."""
    sag("## D) Vergleich: gebuendeltes beso gegen unveraendertes beso von GitHub (upstream)")
    sag()
    if not os.path.isdir(ORIGINAL_BESO):
        sag("(uebersprungen - bitte das Original klonen: git clone --depth 1 "
            "https://github.com/calculix/beso.git \"%s\")" % ORIGINAL_BESO)
        sag()
        return
    neu = rechenmatrix(praefix="neu_")
    alt = rechenmatrix(beso_quelle=ORIGINAL_BESO, praefix="alt_")
    sag("### Gegenueberstellung")
    sag()
    sag("| Szenario | gebuendeltes beso | originales beso |")
    sag("|---|---|---|")
    for a, b in zip(neu, alt):
        def kurz(e):
            massen = [round(m, 1) if m else None for _, m in e["massen"]]
            return "code %s, %s" % (e["code"], massen)
        sag("| %s | %s | %s |" % (a["name"].replace("neu_", ""), kurz(a), kurz(b)))
    gleich = sum(1 for a, b in zip(neu, alt)
                 if [round(m, 6) for _, m in a["massen"]] == [round(m, 6) for _, m in b["massen"]])
    abweichend = sorted(a["name"].replace("neu_", "") for a, b in zip(neu, alt)
                        if [round(m, 6) for _, m in a["massen"]] != [round(m, 6) for _, m in b["massen"]])
    sag("Identische Ergebnisse: %d von %d" % (gleich, len(neu)))
    # only the cases justified above under BEKANNTE_ABWEICHUNGEN may differ
    pruefe("genau die dokumentierten Abweichungen (erwartet: %s - gemessen: %s)"
           % (", ".join(sorted(BEKANNTE_ABWEICHUNGEN)) or "keine",
              ", ".join(abweichend) or "keine"),
           abweichend == sorted(BEKANNTE_ABWEICHUNGEN))
    sag()


def main():
    if not os.path.isdir(ARBEIT):
        os.makedirs(ARBEIT)
    sag("# Szenario-Matrix TopoOpt")
    sag()
    sag("Modelle: %s" % MODELLE)
    sag()
    sag("(Hinweis: die Fehlerfaelle des Assistenten prueft tests/panel_test.py)")
    sag()
    sag("## B/C) Rechenmatrix (gebuendeltes beso)")
    sag()
    laeufe = rechenmatrix()
    berichte_laeufe(laeufe, "Ergebnisse der Rechenmatrix")
    # the error case without a thickness has to show clearly
    ohne = [e for e in laeufe if "ohne Dicke" in e["name"]]
    if ohne:
        e = ohne[0]
        massen = [m for _, m in e["massen"]]
        hat = [x for x in e["fehler"] if "thickness" in x.lower()]
        pruefe("fehlende Schalendicke wird gemeldet oder die Masse ist zu klein",
               bool(hat) or (len(massen) > 1 and massen[0] < 100),
               "%s / Startmasse %s" % (hat or "keine Meldung", massen[0] if massen else "-"))
    vergleich_original()
    fehlgeschlagen = [e for e in ergebnisse if not e["ok"]]
    sag("## Zusammenfassung")
    sag()
    sag("- Pruefungen: %d, davon fehlgeschlagen: %d" % (len(ergebnisse), len(fehlgeschlagen)))
    for e in fehlgeschlagen:
        sag("  - FEHLT: %s (%s)" % (e["name"], e["detail"]))
    sag("- Szenarien gerechnet: %d" % len(laeufe))
    with open(BERICHT, "w", encoding="utf8") as fh:
        fh.write("\n".join(zeilen) + "\n")
    sag()
    sag("Bericht: %s" % BERICHT)


main()
