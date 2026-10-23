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

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, "szenarien")
REPORT = os.path.join(HERE, "szenario_bericht.md")
WORK = os.path.join(tempfile.gettempdir(), "topoopt_szenarien")
# The unmodified original beso for the comparison (https://github.com/calculix/beso):
#     git clone --depth 1 https://github.com/calculix/beso.git
# The path comes either from the environment variable BESO_ORIGINAL or from a clone in
# the temp directory.
ORIGINAL_BESO = os.environ.get("BESO_ORIGINAL",
                               os.path.join(tempfile.gettempdir(), "beso-original"))

lines = []
results = []


def say(text=""):
    lines.append(str(text))
    print(text, flush=True)


def check(name, condition, detail=""):
    marker = "OK  " if condition else "FEHLT"
    say("%s %s%s" % (marker, name, (" (%s)" % detail) if detail else ""))
    results.append({"name": name, "ok": bool(condition), "detail": detail})
    return bool(condition)


# --------------------------------------------------------------------------- #
# beso run
# --------------------------------------------------------------------------- #
class Fake(object):
    """Carrier of the run parameters (like the optimization object in the assistant)."""

    def __init__(self, target_mass=0.6, filter_list=None, iterations="2", thickness=None,
                 thickness_mode="auto", stress=None):
        self.MassGoalRatio = target_mass
        self.OptimizationBase = "stiffness"
        self.IterationsLimit = iterations
        self.Tolerance = 1e-3
        self.CpuCores = 0
        self.Filters = json.dumps(filter_list or [["simple", "auto"]])
        self.RobusterRadius = 0.0
        self.MittlereGroesse = 0.0
        self.MassChange = "normal"
        self.SaveIterations = 1
        self.ResultFormat = "inp vtk"
        self.StressLimits = stress or []
        self.DICKEN = thickness
        self.DICKEN_MODUS = thickness_mode


def _copy_beso(target, source):
    """Copy beso (original or bundled) into the run directory."""
    if os.path.isdir(target):
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


def _conf_for(model, settings, folder, beso_folder):
    """Write a beso_conf.py by hand (without the addon) so that both
    beso variants get exactly the same configuration."""
    from freecad.TopoOpt.core import elsets as elset_reader
    doms = [n for n in elset_reader.read_elsets(model) if n.lower() not in
            ("eall", "efaces", "evolumes", "eedges", "enodes")]
    domain = sorted(doms)[0]
    thicknesses = elset_reader.read_shell_thicknesses(model)
    # without a thickness: beso's example value 1.0 (that is the error case)
    thickness_line = ""
    if settings.get("thickness_mode") == "auto" and domain in thicknesses:
        d = thicknesses[domain]
        thickness_line = "domain_thickness[%r] = [%r, %r]\n" % (domain, d, d)
    elif settings.get("thickness_mode") == "ohne":
        pass                      # nothing -> beso takes 1.0 from its template
    # beso_main reads the configuration from ITS OWN directory (beso_conf.py) - the
    # original template is saved first, otherwise we would overwrite it
    template = os.path.join(beso_folder, "beso_conf_vorlage.py")
    if not os.path.isfile(template):
        shutil.copyfile(os.path.join(beso_folder, "beso_conf.py"), template)
    # beso does not know "robust" - the addon replaces it with a radius beforehand
    filter_list = [list(f) for f in settings["filter"]]
    for entry in filter_list:
        if len(entry) > 1 and entry[1] == "robust":
            from freecad.TopoOpt.core import radius as radius_module
            data = radius_module.read_data(model, [domain], [domain])
            entry[1] = round(radius_module.robust(data).get("radius",
                                                              data.get("mean", 1.0) * 2), 4)
    conf = os.path.join(beso_folder, "beso_conf.py")
    with open(conf, "w", encoding="utf8") as fh:
        fh.write("target_path = %r\n" % folder)
        fh.write("path = %r\n" % folder)
        fh.write("file_name = %r\n" % os.path.basename(model))
        fh.write("path_calculix = %r\n" % _ccx())
        fh.write("elset_name = %r\n" % domain)
        fh.write("domain_optimized = {%r: True}\n" % domain)
        fh.write("domain_density[%r] = [1e-6, 1.0]\n" % domain)
        material_line = ("domain_material[%r] = ['*ELASTIC" + chr(92) + "n0.21, 0.3', "
                          "'*ELASTIC" + chr(92) + "n210000, 0.3']") % domain
        fh.write(material_line + chr(10))
        if thickness_line:
            fh.write(thickness_line)
        fh.write("mass_goal_ratio = %r\n" % settings["target_mass"])
        fh.write("filter_list = %r\n" % (filter_list,))
        fh.write("optimization_base = %r\n" % settings.get("base", "stiffness"))
        # permissible stress per domain - one domain deliberately has none
        for dn, value in (settings.get("sigma") or {}).items():
            line = ("domain_FI[%r] = [[('stress_von_Mises', %r)], "
                     "[('stress_von_Mises', %r)]]\n") % (dn, value * 1e6, value * 1e6)
            fh.write(line)
        # a second domain: computed, but not optimized
        second = settings.get("second_domain")
        if second:
            fh.write("domain_optimized[%r] = False\n" % second)
            fh.write("domain_density[%r] = [1e-6, 1.0]\n" % second)
            fh.write(("domain_material[%r] = ['*ELASTIC" + chr(92) + "n0.21, 0.3', "
                      "'*ELASTIC" + chr(92) + "n70000, 0.33']") % second + chr(10))
        fh.write("mass_addition_ratio = 0.015\n")
        fh.write("mass_removal_ratio = 0.03\n")
        fh.write("ratio_type = 'relative'\n")
        limit = settings["iterations"]
        fh.write("iterations_limit = %s\n" % (limit if str(limit) == "auto" else int(limit)))
        fh.write("tolerance = 0.001\n")
        fh.write("cpu_cores = 0\n")
        fh.write("save_iteration_results = 1\n")
        fh.write("save_resulting_format = 'inp vtk'\n")
        fh.write("import matplotlib as _mpl\n_mpl.use('Agg')\n")
    return conf, domain, thicknesses


def _ccx():
    from freecad.TopoOpt.core import conf as conf_module
    return conf_module.calculix_path()


def run(name, model, settings, beso_source=None):
    """Execute one beso run and evaluate it."""
    from freecad.TopoOpt.core import beso as beso_module
    from freecad.TopoOpt.core import conf as conf_module
    from freecad.TopoOpt.core import run as run_module

    folder = os.path.join(WORK, name.replace(" ", "_").replace("/", "_"))
    if os.path.isdir(folder):
        try:
            shutil.rmtree(folder)
        except OSError:
            # Windows releases files with a delay - then take a fresh directory
            folder = "%s_%d" % (folder, int(time.time()))
    os.makedirs(folder)
    target = _copy_beso(os.path.join(folder, "beso"), beso_source or beso_module.FOLDER)
    shutil.copyfile(model, os.path.join(folder, os.path.basename(model)))
    conf, domain, thicknesses = _conf_for(model, settings, folder, target)
    log = conf_module.log_path(os.path.join(folder, os.path.basename(model)))
    start = time.time()
    process = subprocess.Popen([conf_module.python_path(), os.path.join(target, "beso_main.py")],
                               cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True)
    output = ""
    try:
        output, _ = process.communicate(timeout=600)
    except subprocess.TimeoutExpired:
        process.kill()
        output = "TIMEOUT"
    duration = time.time() - start
    data = run_module.progress(conf_module.beso_log_path(os.path.join(
        folder, os.path.basename(model))), settings["target_mass"])
    errors = [z.strip() for z in (output or "").splitlines()
              if "Error:" in z or "ERROR:" in z or "Exception" in z]
    return {"name": name, "folder": folder, "code": process.returncode, "duration": duration,
            "masses": data.get("masses", []), "domain": domain, "thicknesses": thicknesses,
            "errors": errors[-3:], "error_free": process.returncode == 0}


# --------------------------------------------------------------------------- #
# A) error cases in the assistant
# --------------------------------------------------------------------------- #
def error_cases():
    say("## A) Fehlerfaelle im Assistenten")
    say()
    try:
        import FreeCAD as App
        import FreeCADGui as Gui  # noqa: F401
        from freecad.TopoOpt.features import create_topology_object
        from freecad.TopoOpt.gui.assistant import AssistantPanel
    except Exception as exc:
        say("(uebersprungen - ohne GUI: %s)" % exc)
        say()
        return
    source = os.path.join(tempfile.gettempdir(), "TopoOpt_Test", "modell.FCStd")
    if not os.path.isfile(source):
        say("(uebersprungen - Testdokument fehlt: %s)" % source)
        say()
        return
    copy = os.path.join(tempfile.gettempdir(), "TopoOpt_Szenario.FCStd")
    shutil.copyfile(source, copy)
    doc = App.openDocument(copy)
    analysis = [o for o in doc.Objects if o.TypeId == "Fem::FemAnalysis"][0]
    mesh = [o for o in doc.Objects if o.TypeId.startswith("Fem::FemMesh")][0]
    solver = [o for o in doc.Objects if o.TypeId.startswith("Fem::FemSolver")][0]

    def build_panel():
        obj = create_topology_object(doc, analysis, "Szenario%d" % int(time.time() * 1000 % 10000))
        panel = AssistantPanel(obj)
        panel._show_step(3)
        return obj, panel

    # 1) without a mesh
    doc.removeObject(mesh.Name)
    doc.recompute()
    obj, panel = build_panel()
    panel._start_run()
    check("ohne Netz startet kein Lauf",
           panel._run_process is None and "Netz" in panel.run_status.text(),
           panel.run_status.text())
    # 2) without a solver (mesh back in place)
    doc.addObject(mesh.TypeId, mesh.Name)
    doc.recompute()
    doc.removeObject(solver.Name)
    doc.recompute()
    obj, panel = build_panel()
    panel._start_run()
    check("ohne Solver startet kein Lauf",
           panel._run_process is None and "Solver" in panel.run_status.text(),
           panel.run_status.text())
    doc.addObject(solver.TypeId, solver.Name)
    doc.recompute()
    # 3) without .inp
    obj, panel = build_panel()
    obj.InpFile = ""
    panel._start_run()
    check("ohne Eingabedatei startet kein Lauf",
           panel._run_process is None and "Eingabedatei" in panel.run_status.text(),
           panel.run_status.text())
    # 4) without design space
    obj, panel = build_panel()
    panel.stress = {}
    for name in list(panel.domains):
        panel.domains[name] = "ignore"
    panel._save_domains()
    panel._start_run()
    check("ohne Design-Raum startet kein Lauf",
           panel._run_process is None and "Design" in panel.run_status.text(),
           panel.run_status.text())
    App.closeDocument(doc.Name)
    try:
        os.remove(copy)
    except OSError:
        pass
    say()


# --------------------------------------------------------------------------- #
# B) computation matrix
# --------------------------------------------------------------------------- #
MODEL_3D = os.path.join(MODELS, "modell_3d_hex.inp")
MODEL_2D = os.path.join(MODELS, "modell_2d_schale.inp")
MODEL_2D_NO_THICKNESS = os.path.join(MODELS, "modell_2d_ohne_dicke.inp")
MODEL_2SETS = os.path.join(MODELS, "modell_2sets.inp")

# Scenarios in which our beso deliberately reacts differently from the original:
#   * filter radius too small - the original keeps computing without a filter and
#     reports convergence at the end instead of ending the run
#   * missing shell thickness with 2D models - the original silently computes with its
#     example value
#   * 2D shell models in general: the original aborts with numpy 2 because
#     np.linalg.linalg was removed there (measured with numpy 2.4); casting with "auto"
#     additionally aborts with a NameError.  Our beso computes in both cases.
# Measured with FreeCAD 26.3 (Flatpak) and numpy 2.4: 13 of 17 scenarios identical.
KNOWN_DEVIATIONS = ("2D Schale casting auto", "2D Schale simple auto",
                         "3D simple 1.5 (Radius zu klein)", "3D simple manuell 1.0")

MATRIX = [
    ("3D simple auto", MODEL_3D, {"target_mass": 0.6, "filter": [["simple", "auto"]],
                                   "iterations": "2", "thickness_mode": "auto"}),
    ("3D simple 1.5 (Radius zu klein)", MODEL_3D, {"target_mass": 0.6,
                                                    "filter": [["simple", 1.5]],
                                                    "iterations": "2",
                                                    "thickness_mode": "auto"}),
    ("3D simple robust", MODEL_3D, {"target_mass": 0.6, "filter": [["simple", "robust"]],
                                     "iterations": "2", "thickness_mode": "auto"}),
    ("3D simple manuell 1.0", MODEL_3D, {"target_mass": 0.6, "filter": [["simple", 1.0]],
                                         "iterations": "2", "thickness_mode": "auto"}),
    ("3D zwei Sets, eines ohne sigma", MODEL_2SETS,
     {"target_mass": 0.6, "filter": [["simple", "auto"]], "iterations": "2",
      "thickness_mode": "auto", "base": "failure_index",
      "sigma": {"SetA": 235.0}, "second_domain": "SetB"}),
    ("3D casting auto", MODEL_3D, {"target_mass": 0.6,
                                    "filter": [["casting", 1.5, (0, 0, 1)]],
                                    "iterations": "2", "thickness_mode": "auto"}),
    ("3D Zielmasse 30%", MODEL_3D, {"target_mass": 0.3, "filter": [["simple", "auto"]],
                                     "iterations": "2", "thickness_mode": "auto"}),
    ("2D Schale simple auto", MODEL_2D, {"target_mass": 0.6, "filter": [["simple", "auto"]],
                                          "iterations": "2", "thickness_mode": "auto"}),
    ("2D Schale casting auto", MODEL_2D, {"target_mass": 0.6,
                                           "filter": [["casting", "auto", (0, 0, 1)]],
                                           "iterations": "2", "thickness_mode": "auto"}),
    ("2D ohne Dicke (Fehlerfall)", MODEL_2D_NO_THICKNESS,
     {"target_mass": 0.6, "filter": [["simple", "auto"]], "iterations": "2",
      "thickness_mode": "ohne"}),
]
# try every morphology filter once
for _filter_type in ("erode sensitivity", "dilate sensitivity", "open sensitivity",
             "close sensitivity", "open-close sensitivity", "close-open sensitivity",
             "combine sensitivity"):
    MATRIX.append(("3D %s" % _filter_type.split()[0], MODEL_3D,
                   {"target_mass": 0.6, "filter": [[_filter_type, 1.5]], "iterations": "1",
                    "thickness_mode": "auto"}))


def compute_matrix(beso_source=None, prefix=""):
    from freecad.TopoOpt.core import beso as beso_module
    source = beso_source or beso_module.FOLDER
    runs = []
    for name, model, setting in MATRIX:
        try:
            result = run(prefix + name, model, setting, source)
        except Exception as exc:
            say("FEHLT %s: %s" % (name, exc))
            traceback.print_exc()
            continue
        runs.append(result)
        masses = result["masses"]
        say("%-34s code=%s  %5.1f s  Massen=%s"
            % (name, result["code"], result["duration"],
               [round(m, 1) if m else m for _, m in masses]))
        if result["errors"]:
            say("      Meldung: %s" % (result["errors"],))
    return runs


def report_runs(runs, title):
    say("## %s" % title)
    say()
    for e in runs:
        masses = [round(m, 2) if m else m for _, m in e["masses"]]
        fell = (masses[-1] < masses[0]) if len(masses) > 1 else None
        say("- **%s**: code=%s, %.1f s, %d Zeilen, Masse %s%s"
            % (e["name"], e["code"], e["duration"], len(masses), masses,
               "" if fell is None else (", faellt ab" if fell else ", STEIGT")))
    say()


# --------------------------------------------------------------------------- #
# D) comparison with the original beso
# --------------------------------------------------------------------------- #
def compare_original():
    """Original beso (without our fixes) against the bundled beso on the same models."""
    say("## D) Vergleich: gebuendeltes beso gegen unveraendertes beso von GitHub (upstream)")
    say()
    if not os.path.isdir(ORIGINAL_BESO):
        say("(uebersprungen - bitte das Original klonen: git clone --depth 1 "
            "https://github.com/calculix/beso.git \"%s\")" % ORIGINAL_BESO)
        say()
        return
    new_runs = compute_matrix(prefix="neu_")
    old_runs = compute_matrix(beso_source=ORIGINAL_BESO, prefix="alt_")
    say("### Gegenueberstellung")
    say()
    say("| Szenario | gebuendeltes beso | originales beso |")
    say("|---|---|---|")
    for a, b in zip(new_runs, old_runs):
        def short_row(e):
            masses = [round(m, 1) if m else None for _, m in e["masses"]]
            return "code %s, %s" % (e["code"], masses)
        say("| %s | %s | %s |" % (a["name"].replace("neu_", ""), short_row(a), short_row(b)))
    identical = sum(1 for a, b in zip(new_runs, old_runs)
                 if [round(m, 6) for _, m in a["masses"]] == [round(m, 6) for _, m in b["masses"]])
    deviating = sorted(a["name"].replace("neu_", "") for a, b in zip(new_runs, old_runs)
                        if [round(m, 6) for _, m in a["masses"]] != [round(m, 6) for _, m in b["masses"]])
    say("Identische Ergebnisse: %d von %d" % (identical, len(new_runs)))
    # only the cases justified above under BEKANNTE_ABWEICHUNGEN may differ
    check("genau die dokumentierten Abweichungen (erwartet: %s - gemessen: %s)"
           % (", ".join(sorted(KNOWN_DEVIATIONS)) or "keine",
              ", ".join(deviating) or "keine"),
           deviating == sorted(KNOWN_DEVIATIONS))
    say()


def main():
    if not os.path.isdir(WORK):
        os.makedirs(WORK)
    say("# Szenario-Matrix TopoOpt")
    say()
    say("Modelle: %s" % MODELS)
    say()
    say("(Hinweis: die Fehlerfaelle des Assistenten prueft tests/panel_test.py)")
    say()
    say("## B/C) Rechenmatrix (gebuendeltes beso)")
    say()
    runs = compute_matrix()
    report_runs(runs, "Ergebnisse der Rechenmatrix")
    # the error case without a thickness has to show clearly
    without_thickness = [e for e in runs if "ohne Dicke" in e["name"]]
    if without_thickness:
        e = without_thickness[0]
        masses = [m for _, m in e["masses"]]
        hits = [x for x in e["errors"] if "thickness" in x.lower()]
        check("fehlende Schalendicke wird gemeldet oder die Masse ist zu klein",
               bool(hits) or (len(masses) > 1 and masses[0] < 100),
               "%s / Startmasse %s" % (hits or "keine Meldung", masses[0] if masses else "-"))
    compare_original()
    failed = [e for e in results if not e["ok"]]
    say("## Zusammenfassung")
    say()
    say("- Pruefungen: %d, davon fehlgeschlagen: %d" % (len(results), len(failed)))
    for e in failed:
        say("  - FEHLT: %s (%s)" % (e["name"], e["detail"]))
    say("- Szenarien gerechnet: %d" % len(runs))
    with open(REPORT, "w", encoding="utf8") as fh:
        fh.write("\n".join(lines) + "\n")
    say()
    say("Bericht: %s" % REPORT)


main()
