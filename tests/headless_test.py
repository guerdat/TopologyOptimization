#!/usr/bin/env python
# SPDX-License-Identifier: LGPL-3.0-or-later
"""Headless test of the addon - run it with the FreeCAD console interpreter:

    "<FreeCAD>/bin/freecadcmd.exe" tests/headless_test.py

Exit code 0 = all checks passed.  The addon has to be installed in FreeCAD's Mod
directory (see Documentation/development.md).

A script that stops with an exception also leaves FreeCADCmd with exit code 0 (measured), so the
closing line matters as much as the exit code - the CI checks both."""

import os
import sys
import tempfile

import FreeCAD as App

# The messages are German.  Without a UTF-8 locale (LANG=C) sys.stdout would be ASCII
# and a print() with an umlaut would abort the run - the remaining checks would then
# never run.  That is why the output is pinned to UTF-8, with "replace" as the fallback.
for _strom in (sys.stdout, sys.stderr):
    _umstellen = getattr(_strom, "reconfigure", None)
    if _umstellen is not None:
        try:
            _umstellen(encoding="utf8", errors="replace")
        except (AttributeError, ValueError):
            pass

fehler = []


def pruefe(bedingung, text):
    # flush=True: FreeCAD quits the process at sys.exit() without flushing the
    # buffers, so print() output would be lost when stdout is redirected
    print("%-5s %s" % ("OK" if bedingung else "FEHLT", text), flush=True)
    if not bedingung:
        fehler.append(text)


def beenden(code):
    """Leave the process with a status code.

    os._exit() and not sys.exit(): FreeCAD catches SystemExit from a script and
    runs the script a second time (measured - the output appeared twice), which
    makes a test unrepeatable.  The output buffers are flushed first because
    os._exit() does not do that.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


try:
    import freecad.TopoOpt as modul
except ImportError as exc:
    print("FEHLT Modul freecad.TopoOpt ist nicht importierbar (%s)" % exc)
    print("      Liegt das Addon im Mod-Ordner von FreeCAD? "
          "Siehe Documentation/development.md")
    beenden(1)

from freecad.TopoOpt.features import create_topology_object, find_analysis  # noqa: E402

print("FreeCAD %s, Addon %s" % (".".join(App.Version()[:3]), modul.__version__))
print()

doc = App.newDocument("TopoOptTest")
analysis = doc.addObject("Fem::FemAnalysis", "Analysis")
obj = create_topology_object(doc, analysis)
doc.recompute()

pruefe(obj.TypeId == "App::FeaturePython", "Objekt ist ein FeaturePython-Objekt")
pruefe(obj.Name in [o.Name for o in analysis.Group], "Objekt liegt als Kind in der Analyse")
pruefe(obj.AnalysisName == analysis.Name, "AnalysisName ist gespeichert")
pruefe(find_analysis(obj) is analysis, "find_analysis findet die Analyse ueber die Gruppe")

analysis.removeObject(obj)
pruefe(find_analysis(obj) is analysis, "find_analysis findet sie auch auszerhalb ueber den Namen")
analysis.addObject(obj)

# Persistence: save the document and check the saved file.
# App.openDocument() is deliberately NOT used here: FreeCAD then runs a start
# script a second time (same process, measured) - that makes a test
# unpredictable.  See Documentation/development.md.
pfad = os.path.join(tempfile.gettempdir(), "topoopt_headless_test.FCStd")
if os.path.exists(pfad):
    os.remove(pfad)
obj.Domains = ["TestSet|design"]
doc.saveAs(pfad)
App.closeDocument(doc.Name)

import zipfile  # noqa: E402

with zipfile.ZipFile(pfad) as archiv:
    xml = archiv.read("Document.xml").decode("utf8", "ignore")
pruefe('name="TopologieOptimierung"' in xml, "Objekt steht in der gespeicherten Datei")
pruefe("AnalysisName" in xml and 'Analysis"' in xml, "Analyse-Name ist gespeichert")
pruefe("Domains" in xml and "TestSet|design" in xml, "Rollen sind gespeichert")
pruefe("TopologyObject" in xml, "Proxy-Klasse (TopologyObject) ist gespeichert")
os.remove(pfad)

# --- element sets and roles (pure logic, no document) -----------------------
from freecad.TopoOpt.core import domains as dom        # noqa: E402
from freecad.TopoOpt.core import elsets as elset_reader  # noqa: E402

beispiel = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "beispiel.inp")
gelesen = elset_reader.read_elsets(beispiel)
pruefe(gelesen.get("MaterialSolidSolid") == 4, "Elemente aus *ELEMENT-ELSET gelesen (4)")
pruefe(gelesen.get("NichtDesignSolid") == 2, "zweites Set gelesen (2)")
pruefe(gelesen.get("Eall") == 6, "Sammelset Eall gelesen (6)")
pruefe(gelesen.get("Reihe") == 6, "GENERATE-Set gelesen (10..20 Schritt 2 = 6)")
pruefe(gelesen.get("VerweisSet") == 4, "Set-Verweis wird aufgeloest (VerweisSet -> 4)")
pruefe(elset_reader.element_types(beispiel) == ["C3D4"], "Elementtyp erkannt (C3D4)")
pruefe(elset_reader.total_elements(beispiel) == 6, "Gesamtzahl der Elemente (6)")

sichtbar = dom.visible_elsets(gelesen)
pruefe("Eall" not in sichtbar, "Sammelset wird nicht angeboten")
pruefe(len(sichtbar) == 4, "vier Sets werden angeboten")

vorschlag = dom.suggestion(gelesen)
pruefe(vorschlag.get("Eall") is None, "Sammelset bekommt keine Rolle")
pruefe(set(vorschlag.values()) == {dom.DESIGN},
       "ohne Vorbelegung ist jedes Set Design-Raum (nicht 'ignorieren')")

vorschlag_eins = dom.suggestion({"MaterialSolidSolid": 4, "Eall": 4})
pruefe(vorschlag_eins.get("MaterialSolidSolid") == dom.DESIGN,
       "auch ein einzelnes Set ist Design-Raum")

gespeichert = dom.format_domains({"B": dom.NON_DESIGN, "A": dom.DESIGN})
pruefe(gespeichert == ["A|design", "B|non_design"], "Rollen werden stabil formatiert")
zurueck = dom.parse_domains(gespeichert)
pruefe(zurueck == {"A": dom.DESIGN, "B": dom.NON_DESIGN}, "Rollen werden wieder eingelesen")

rollen = dom.roles_for({"A": 10, "B": 10, "Neu": 10}, zurueck)
pruefe(rollen == {"A": dom.DESIGN, "B": dom.NON_DESIGN, "Neu": dom.DESIGN},
       "Gespeichertes gilt weiter, ein neues Set ist Design-Raum (%s)" % rollen)
rollen_leer = dom.roles_for({"A": 10, "B": 10})
pruefe(set(rollen_leer.values()) == {dom.DESIGN},
       "ohne Vorbelegung ist alles Design-Raum")

# --- find the input file (search order) -------------------------------------
import shutil as _shutil  # noqa: E402
import tempfile as _tempfile  # noqa: E402
import uuid as _uuid  # noqa: E402
from freecad.TopoOpt.core import fem as fem_core  # noqa: E402

doc3 = App.newDocument("TopoOptSuchTest")
# a name per run: FreeCAD may run the script twice (see the note about
# App.openDocument() in Documentation/development.md), so nothing may collide
dummy_mesh = doc3.addObject("App::FeaturePython",
                            "SuchMesh_%s" % _uuid.uuid4().hex[:8])
dummy_solver = doc3.addObject("App::FeaturePython", "SuchSolver")
dummy_solver.addProperty("App::PropertyString", "WorkingDirectory", "Test", "test")
dummy_solver.addProperty("App::PropertyString", "WorkingDir", "Test", "test")
dateiname = "%s.inp" % dummy_mesh.Name
ordner = _tempfile.mkdtemp(prefix="fcfem_topoopt_test_")
ordner2 = _tempfile.mkdtemp(prefix="fcfem_topoopt_other_")

pruefe(fem_core.find_inp(dummy_solver, dummy_mesh, "TopoOptTest", remembered=ordner)[0] is None,
       "ohne Datei wird nichts gefunden")

# 1. the (remembered) FEM working directory is used
pruefe(fem_core.working_dir(dummy_solver, "TopoOptTest", dummy_mesh, remembered=ordner) == ordner,
       "gemerkter FEM-Arbeitsordner wird verwendet")

with open(os.path.join(ordner, dateiname), "w") as fh:
    fh.write("*ELSET, ELSET=SuchSet\n1, 2, 3\n")
pfad, quelle = fem_core.find_inp(dummy_solver, dummy_mesh, "TopoOptTest", remembered=ordner)
pruefe(quelle == "fem", "Datei im FEM-Arbeitsordner wird gefunden")
pruefe(os.path.dirname(pfad) == ordner, "der FEM-Arbeitsordner wird verwendet")

# 2. file only in another FEM working directory
os.remove(os.path.join(ordner, dateiname))
with open(os.path.join(ordner2, dateiname), "w") as fh:
    fh.write("*ELSET, ELSET=SuchSet\n1, 2, 3\n")
pfad, quelle = fem_core.find_inp(dummy_solver, dummy_mesh, "TopoOptTest", remembered=ordner)
pruefe(quelle == "other", "anderer FEM-Arbeitsordner wird gefunden")
kopie = fem_core.adopt_inp(pfad, dummy_solver, "TopoOptTest", dummy_mesh, remembered=ordner)
pruefe(os.path.dirname(kopie) == ordner and os.path.isfile(kopie),
       "gefundene Datei wird in den FEM-Arbeitsordner kopiert")
pruefe(fem_core.file_info(kopie).startswith("0.0 kB"), "Dateiinfo nennt Groesse (%s)"
       % fem_core.file_info(kopie))

# 3. only our own (old) working directory
os.remove(os.path.join(ordner, dateiname))
os.remove(os.path.join(ordner2, dateiname))
eigener = fem_core.run_dir("TopoOptTest", dummy_mesh.Name)
with open(os.path.join(eigener, dateiname), "w") as fh:
    fh.write("*ELSET, ELSET=SuchSet\n1, 2, 3\n")
pfad, quelle = fem_core.find_inp(dummy_solver, dummy_mesh, "TopoOptTest", remembered=ordner)
pruefe(quelle == "own", "eigener Arbeitsordner wird als letztes gefunden")
_shutil.rmtree(ordner, ignore_errors=True)
_shutil.rmtree(ordner2, ignore_errors=True)
_shutil.rmtree(eigener, ignore_errors=True)
App.closeDocument(doc3.Name)

# --- translation (English source, German translation) -----------------------
from freecad.TopoOpt.core import i18n  # noqa: E402

unbekannt = "a text that is not in the dictionary"
pruefe(i18n.translate(unbekannt) == unbekannt, "unbekannte Texte bleiben unveraendert")
pruefe(i18n.translate("Initialize") in ("Initialize", "Initialisieren"),
       "bekannter Text wird uebersetzt oder bleibt englisch: %r" % i18n.translate("Initialize"))
# The language comes from FreeCAD's settings or from the system - which language that
# is depends on the machine (in a CI without a locale it is "C").  The check therefore
# covers only what the function promises: an empty result or a code made of letters.
erkannt = i18n.language()
pruefe(erkannt == "" or erkannt.isalpha(),
       "die Sprache wird als Kuerzel erkannt (%r)" % erkannt)

# --- parameters (step 2) ----------------------------------------------------
from freecad.TopoOpt.core import params as prm  # noqa: E402

pruefe(prm.mass_ratios("gentle") == (0.01, 0.02), "Massenraten 'sanft' wie in der beso-GUI")
pruefe(prm.mass_ratios("fast") == (0.03, 0.06), "Massenraten 'schnell' wie in der beso-GUI")
pruefe(prm.mass_ratios("unbekannt") == (0.015, 0.03), "unbekannte Stufe faellt auf 'normal'")
pruefe(prm.parse_filters(prm.format_filters([["casting", 2.0, "(0, 0, 1)"]]))
       == [["casting", 2.0, "(0, 0, 1)"]], "Filter werden geschrieben und gelesen")
pruefe(prm.parse_filters(prm.format_filters([["erode sensitivity", "auto"],
                                             ["simple", 3.0]]))
       == [["erode sensitivity", "auto"], ["simple", 3.0]],
       "Morphologie-Filter werden geschrieben und gelesen")
pruefe(len(prm.FILTER_TYPES) == 9 and "combined" not in prm.FILTER_TYPES,
       "beso kennt 9 Filtertypen (%s)" % (prm.FILTER_TYPES,))
pruefe("open-close sensitivity" in prm.FILTER_TYPES and "casting" in prm.FILTER_TYPES,
       "die beso-Typen sind vollstaendig")
pruefe(prm.parse_filters("kein Python") == [["simple", "robust"]],
       "unbrauchbarer Filtertext faellt auf beso-Standard zurueck")
pruefe(prm.parse_filters(prm.format_filters([["quatsch", 1]])) == [["simple", "robust"]],
       "unbekannter Filtertyp wird verworfen")

doc4 = App.newDocument("TopoOptParameterTest")
analyse4 = doc4.addObject("Fem::FemAnalysis", "Analyse")
obj4 = create_topology_object(doc4, analyse4, "TopoOpt4")
pruefe(abs(obj4.MassGoalRatio - 0.6) < 1e-9, "Zielmasse startet bei 0,6 (60 %)")
pruefe(obj4.OptimizationBase == "stiffness", "Optimierungsziel startet mit 'stiffness'")
pruefe(obj4.IterationsLimit == "auto", "Iterationen starten mit 'auto'")
pruefe(abs(obj4.Tolerance - 1e-3) < 1e-12, "Toleranz startet mit 1e-3 (beso-Standard)")
pruefe(obj4.FIViolatedTolerance == 1, "FI-Toleranz startet bei 1 (beso-Standard)")
pruefe(obj4.CpuCores == 0, "Kerne starten bei 0 (alle)")
pruefe(obj4.MassChange == "normal", "Massenänderung startet mit 'normal'")
pruefe(obj4.SaveIterations == 10, "jede 10. Iteration wird gespeichert (spart Platz)")
pruefe(obj4.ResultFormat == "inp vtk", "Ergebnisformat startet mit 'inp vtk'")

obj4.MassGoalRatio = 0.3
obj4.OptimizationBase = "buckling"
obj4.IterationsLimit = "25"
obj4.CpuCores = 4
obj4.FIViolatedTolerance = 5
obj4.Filters = prm.format_filters([["simple", 7.5], ["casting", 2.0, "(0, 0, 1)"]])
pfad4 = os.path.join(tempfile.gettempdir(), "topoopt_params_test.FCStd")
doc4.saveAs(pfad4)
App.closeDocument(doc4.Name)
import zipfile as _zipfile  # noqa: E402
with _zipfile.ZipFile(pfad4) as _z:
    _xml = _z.read("Document.xml").decode("utf8", "ignore")
pruefe('name="MassGoalRatio"' in _xml and "0.3" in _xml, "Zielmasse ist gespeichert")
pruefe("buckling" in _xml, "Optimierungsziel ist gespeichert")
pruefe("casting" in _xml, "Filter sind gespeichert")
pruefe('name="CpuCores"' in _xml, "Kerne sind gespeichert")
pruefe('name="FIViolatedTolerance"' in _xml, "FI-Toleranz ist gespeichert")
os.remove(pfad4)

# --- bundled beso + filter radius -------------------------------------------
from freecad.TopoOpt.core import beso as beso_modul  # noqa: E402
from freecad.TopoOpt.core import radius as radius_modul  # noqa: E402

ordner, fehlend = beso_modul.check()
pruefe(not fehlend, "beso liegt vollstaendig im Addon (%s)" % ordner)
if fehlend:
    print("beso: fehlende Dateien %s" % (fehlend,), flush=True)

lib, filters = beso_modul.module()
pruefe(hasattr(lib, "import_inp") and hasattr(filters, "prepare2s"),
       "beso_lib und beso_filters sind geladen")
pruefe("beso_lib" in sys.modules and sys.modules["beso_lib"] is lib,
       "beso_lib steht unter seinem eigenen Namen (so importiert beso sich selbst)")

beispiel = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "beispiel.inp")
daten = radius_modul.read_data(beispiel, ["MaterialSolidSolid", "NichtDesignSolid"],
                               ["MaterialSolidSolid"])
print("Elementdaten: mittel=%.4f maximum=%.4f anzahl=%s"
      % (daten.get("mean", -1), daten.get("maximum", -1), daten.get("count", -1)), flush=True)
pruefe(daten.get("count", 0) > 0, "beso liest Elementgroessen aus der .inp (%s Elemente)"
       % daten.get("count"))
pruefe(0 < daten.get("mean", 0) <= daten.get("maximum", 0),
       "mittlere Groesse liegt unter der groessten (%.4f <= %.4f)"
       % (daten.get("mean", 0), daten.get("maximum", 0)))

zu_klein = radius_modul.without_neighbours(daten, daten["mean"] * 0.1)
gross_genug = radius_modul.without_neighbours(daten, daten["mean"] * 10.0)
print("ohne Nachbarn: bei 0,1x mittel %d, bei 10x mittel %d"
      % (len(zu_klein), len(gross_genug)), flush=True)
pruefe(len(zu_klein) > 0, "bei zu kleinem Radius fehlen Nachbarn (%d Elemente)" % len(zu_klein))
pruefe(len(gross_genug) == 0, "bei grossem Radius hat jedes Element Nachbarn")

# the fast grid check has to return the same as beso's prepare2s
gleich = True
for faktor in (0.5, 1.0, 1.5, 2.0, 3.0):
    radius = faktor * daten["mean"]
    if sorted(radius_modul.without_neighbours(daten, radius)) != \
            sorted(radius_modul.without_neighbours_beso(daten, radius)):
        gleich = False
        print("Unterschied bei Faktor %.1f" % faktor, flush=True)
pruefe(gleich, "schnelle Pruefung und besos prepare2s stimmen ueberein")

ergebnis = radius_modul.robust(daten)
print("robuster Radius: Faktor %.1f -> %.4f mm, ohne Nachbarn: %d"
      % (ergebnis.get("factor", -1), ergebnis.get("radius", -1),
         ergebnis.get("without_neighbours", -1)), flush=True)
pruefe(ergebnis.get("without_neighbours") == 0,
       "robuster Radius laesst kein Element ohne Nachbarn")
pruefe(ergebnis.get("radius", 0) >= radius_modul.BESO_AUTO * daten["mean"],
       "robuster Radius ist mindestens so gross wie besos 'auto'")
pruefe(radius_modul.robust({}) == {}, "ohne Elementdaten kommt ein leeres Ergebnis")
# beso writes a log file next to the .inp while reading it (write_to_log) - remove it
# again in the test, in the working directory it is wanted
protokoll = os.path.splitext(beispiel)[0] + ".log"
if os.path.isfile(protokoll):
    os.remove(protokoll)

# --- step 3: the configuration for beso -------------------------------------
from freecad.TopoOpt.core import conf as conf_modul  # noqa: E402

pruefe(conf_modul.SUBFOLDER == "topoopt_beso",
       "beso laeuft in einem Unterordner des Arbeitsordners (%s)" % conf_modul.SUBFOLDER)
pruefe("ccx" in os.path.basename(conf_modul.calculix_path()).lower(),
       "CalculiX wird gefunden (%s)" % conf_modul.calculix_path())
pruefe("python" in os.path.basename(conf_modul.python_path() or "").lower(),
       "ein Python fuer den Lauf wird gefunden (%s)" % conf_modul.python_path())
# The interpreter must never be FreeCAD itself: on FreeCADCmd "-u" is FreeCAD's own
# option (user parameter file), beso_main.py would be overwritten instead of running
# (measured in the Flatpak - there sys.executable is the FreeCADCmd in the app directory).
pruefe(conf_modul.python_path() is None
       or "freecad" not in os.path.basename(conf_modul.python_path()).lower(),
       "der Interpreter ist nicht FreeCAD selbst (%s)" % conf_modul.python_path())
pruefe(conf_modul.calculix_path() == "ccx" or os.path.isfile(conf_modul.calculix_path()),
       "der gefundene Solver ist eine Datei (%s)" % conf_modul.calculix_path())
pruefe(conf_modul.python_path() is None or os.path.isfile(conf_modul.python_path()),
       "der gefundene Interpreter ist eine Datei (%s)" % conf_modul.python_path())
# without Python there is no run: a clear message instead of starting a wrong process,
# and nothing is written into the working directory
_echter_pfad = conf_modul.python_path
conf_modul.python_path = lambda: None
try:
    conf_modul.start(None, None, {}, None)
    pruefe(False, "ohne Python wird der Lauf abgelehnt")
except RuntimeError as meldung:
    pruefe("python" in str(meldung).lower(),
           "ohne Python kommt eine klare Meldung (%s)" % meldung)
except Exception as meldung:  # noqa: BLE001
    pruefe(False, "ohne Python kommt ein RuntimeError, nicht %r" % meldung)
finally:
    conf_modul.python_path = _echter_pfad

doc5 = App.newDocument("TopoOptConfTest")
analyse5 = doc5.addObject("Fem::FemAnalysis", "Analyse")
obj5 = create_topology_object(doc5, analyse5, "TopoOpt5")
obj5.MassGoalRatio = 0.6
obj5.IterationsLimit = "auto"
obj5.Filters = "[['simple', 'robust']]"
obj5.RobusterRadius = 4.85
domains4 = {"SetA": "design", "SetB": "non_design"}
text = conf_modul.conf_text(obj5, os.path.join("C:", os.sep, "tmp", "Mesh.inp"), domains4,
                            os.path.join("C:", os.sep, "tmp"))
pruefe("path = " in text and "tmp" in text, "der Arbeitsordner steht in der Konfiguration")
pruefe("file_name = 'Mesh.inp'" in text, "die Eingabedatei steht in der Konfiguration")
pruefe("mass_goal_ratio = 0.6" in text, "die Zielmasse steht in der Konfiguration")
pruefe("FI_violated_tolerance = 1" in text, "die FI-Toleranz steht in der Konfiguration")
obj5.FIViolatedTolerance = 5
text_fi = conf_modul.conf_text(obj5, os.path.join("C:", os.sep, "tmp", "Mesh.inp"), domains4,
                               os.path.join("C:", os.sep, "tmp"))
obj5.FIViolatedTolerance = 1
pruefe("FI_violated_tolerance = 5" in text_fi and "FI_violated_tolerance = 1" not in text_fi,
       "ein geaenderter Wert der FI-Toleranz wird geschrieben (5)")
pruefe("{'SetA': True, 'SetB': False}" in text,
       "Design- und Nicht-Design-Raum stehen in der Konfiguration")
pruefe("['simple', 4.85]" in text,
       "der robuste Radius wird als Zahl geschrieben (kein 'robust' fuer beso)")
pruefe("_mpl.use('Agg')" in text, "ohne Fenster am Ende (beso_main ruft plt.show)")

# "ignore" means: the set does not appear in the optimization - no design
# space, no non-design space, and it needs no permissible stress either
domains_ignore = {"SetA": "design", "SetB": "non_design", "SetC": "ignore"}
text_ignore = conf_modul.conf_text(obj5, os.path.join("C:", os.sep, "tmp", "Mesh.inp"),
                                   domains_ignore, os.path.join("C:", os.sep, "tmp"))
zeile_opt = [z for z in text_ignore.splitlines() if z.startswith("domain_optimized")][0]
pruefe("SetC" not in zeile_opt and "SetA" in zeile_opt,
       "domain_optimized enthaelt kein ignoriertes Set (%s)" % zeile_opt)
pruefe("SetC" not in text_ignore,
       "ein ignoriertes Set kommt in der Konfiguration nicht vor")
pruefe("beso_conf_vorlage.py" in text, "die Vorlage von beso wird als Grundlage gelesen")

ordner4 = _tempfile.mkdtemp(prefix="topoopt_conf_")
ziel4, conf4 = conf_modul.write_files(obj5, os.path.join(ordner4, "Mesh.inp"),
                                      domains4, ordner4)
pruefe(os.path.isfile(conf4), "beso_conf.py wird geschrieben")
pruefe(os.path.isfile(os.path.join(ziel4, "beso_main.py")), "beso_main.py liegt im Unterordner")
pruefe(os.path.isfile(os.path.join(ziel4, "beso_conf_vorlage.py")),
       "die beso-Vorlage liegt unveraendert daneben")

# --- the run is started unbuffered ------------------------------------------
# Without -u/PYTHONUNBUFFERED the child buffers in blocks: the log file stays empty
# until the run ends, and the details field in the panel shows nothing while the run
# is going on (measured: 0 bytes until the process ends).
_echter_popen = conf_modul.subprocess.Popen
_aufrufe = []


class _FakeProzess(object):
    returncode = None


def _fake_popen(args, **kwargs):
    _aufrufe.append((args, kwargs))
    return _FakeProzess()


_conf_testordner = _tempfile.mkdtemp(prefix="topoopt_start_")
_inp5 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "beispiel.inp")
conf_modul.subprocess.Popen = _fake_popen
try:
    prozess5, log5, conf5 = conf_modul.start(obj5, _inp5, domains4, _conf_testordner)
finally:
    conf_modul.subprocess.Popen = _echter_popen
if _aufrufe:
    _args, _kwargs = _aufrufe[0]
    pruefe("-u" in _args, "der Lauf startet ungepuffert (-u): %s" % _args)
    pruefe(_kwargs.get("env", {}).get("PYTHONUNBUFFERED") == "1",
           "PYTHONUNBUFFERED steht in der Umgebung des Laufs")
    pruefe(_kwargs.get("env", {}).get("PYTHONUTF8") == "1",
           "PYTHONUTF8 steht in der Umgebung des Laufs")
else:
    pruefe(False, "der Lauf wird gestartet (Popen wurde aufgerufen)")

# --- permissible stress -> failure index ------------------------------------
limits = dom.parse_stress(["SetA|235.0", "SetB|", "SetC|kaputt", "SetD|0"])
pruefe(limits == {"SetA": 235.0},
       "nur gueltige, positive Spannungen werden gelesen (%s)" % limits)
pruefe(dom.format_stress({"SetA": 235.0}) == ["SetA|235.0"],
       "die Spannungen werden als Liste gespeichert (%s)" % dom.format_stress({"SetA": 235.0}))

pruefe("stress_limits = {}" in text,
       "ohne Spannung schreibt die Konfiguration keine Failure-Index-Werte")

obj5.StressLimits = ["SetA|235.0"]
text2 = conf_modul.conf_text(obj5, os.path.join("C:", os.sep, "tmp", "Mesh.inp"), domains4,
                             os.path.join("C:", os.sep, "tmp"))
pruefe("stress_limits = {'SetA': 235.0}" in text2,
       "die zulaessige Spannung steht in der Konfiguration")
pruefe("domain_FI[_name] = [[('stress_von_Mises', _sigma * 1e6)]" in text2,
       "daraus wird besos domain_FI (Stress in Pa plus zulaessiger Wert)")

# the hard proof: the written configuration executes and sets domain_FI
obj5.StressLimits = ["SetA|235.0", "SetB|100.0"]
ziel5, conf5 = conf_modul.write_files(obj5, os.path.join(ordner4, "Mesh.inp"),
                                      domains4, ordner4)
raum = {"__file__": conf5}          # the configuration reads the template via __file__
# beso_main defines these names before it reads the configuration (line 25 ff.);
# the configuration builds on them - without them it does not run
for _name in ("domain_optimized", "domain_density", "domain_material", "domain_thickness",
              "domain_offset", "domain_orientation", "domain_FI", "domain_same_state"):
    raum[_name] = {}
exec(open(conf5, encoding="utf8").read(), raum)
fi = raum.get("domain_FI", {})
pruefe(fi.get("SetA") == [[("stress_von_Mises", 235.0e6)], [("stress_von_Mises", 235.0)]],
       "die Konfiguration setzt domain_FI fuer SetA (%s)" % (fi.get("SetA"),))
pruefe(fi.get("SetB") == [[("stress_von_Mises", 100.0e6)], [("stress_von_Mises", 100.0)]],
       "die Konfiguration setzt domain_FI fuer SetB (%s)" % (fi.get("SetB"),))
pruefe("SetC" not in fi, "ohne Spannung bleibt die Domain ohne Failure Index")
pruefe(os.path.isfile(os.path.join(ziel4, "beso_lib.py")), "beso_lib.py liegt im Unterordner")
pruefe(conf_modul.log_path(os.path.join(ordner4, "Mesh.inp")).endswith("Mesh_topoopt.log"),
       "die Logdatei liegt neben der Eingabedatei")
_shutil.rmtree(ordner4, ignore_errors=True)

# --- step 3: read the protocol of a run -------------------------------------
from freecad.TopoOpt.core import lauf as lauf_modul  # noqa: E402

# --- step 3: read beso's iteration table ------------------------------------
beso_beispiel = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                             "beso_beispiel.log")
# The recording of a run is a test input and lives in the repository.  If it is missing
# that is reported - but the run does not stop: a missing file must not swallow the
# checks after it (the VTK and state readers).
pruefe(os.path.isfile(beso_beispiel), "die Testdatei tests/data/beso_beispiel.log ist da")
tabelle = lauf_modul.read_table(beso_beispiel)
pruefe(len(tabelle) == 6, "die Iterationstabelle wird gelesen (6 Zeilen, 2 Laeufe)")
if len(tabelle) == 6:
    pruefe(tabelle[0][0] == 0 and abs(tabelle[0][1]["mass"] - 20000.0) < 1e-6,
           "die Startmasse wird gelesen: %s" % tabelle[0][1]["mass"])
    pruefe(abs(tabelle[2][1]["mass"] - 19110.748316642857) < 1e-6,
           "die Masse der dritten Iteration wird gelesen")
    pruefe(tabelle[3][1].get("fi_violated") == 0 and abs(tabelle[5][1]["fi_max"] - 1.1) < 1e-6,
           "die FI-Spalten werden gelesen (ueberlastet=%s, FI_max=%s)"
           % (tabelle[3][1].get("fi_violated"), tabelle[5][1].get("fi_max")))
    pruefe("fi_mean" not in tabelle[0][1],
           "ohne Failure Index gibt es keine FI-Werte (nur Masse und Energiedichte)")

f = lauf_modul.progress(beso_beispiel, 0.6)
# without a table, iteration/mass/target are None - the checks have to report that,
# not abort with a TypeError (otherwise the errors after them are never seen)
pruefe(f["iteration"] == 2 and f["mass"] is not None
       and abs(f["mass"] - 19110.748316642857) < 1e-6,
       "der Fortschritt kennt Iteration und Masse (%s, %s)" % (f["iteration"], f["mass"]))
pruefe(f["target"] is not None and abs(f["target"] - 20000.0 * 0.6) < 1e-6,
       "die Zielmasse ist der Anteil der Startmasse: %s" % f["target"])
pruefe(abs(lauf_modul.ratio(f["start"], f["mass"], 0.6) - 11.12) < 0.1,
       "der Fortschritt in Prozent: %.1f %%" % lauf_modul.ratio(f["start"], f["mass"], 0.6))
pruefe(lauf_modul.ratio(20000.0, 8000.0, 0.6) == 100.0,
       "bei der Zielmasse steht der Balken auf 100 %")

beispiel_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                            "lauf_beispiel.log")
daten_lauf = lauf_modul.read_history(beispiel_log, 0.6)
print("Lauf-Protokoll: start=%s ziel=%s iteration=%s massen=%s fertig=%s"
      % (daten_lauf["start"], daten_lauf["target"], daten_lauf["iteration"],
         daten_lauf["masses"], daten_lauf["done"]), flush=True)
pruefe(daten_lauf["start"] is not None and abs(daten_lauf["start"] - 20000.0) < 1e-6,
       "die Startmasse wird gelesen (%s)" % daten_lauf["start"])
pruefe(abs((daten_lauf["target"] or 0) - 12000.0) < 1e-6,
       "die Zielmasse ist Anteil x Startmasse (%s)" % daten_lauf["target"])
pruefe(daten_lauf["iteration"] == 2, "die Iterationen werden gezaehlt (%d)"
       % daten_lauf["iteration"])
pruefe(len(daten_lauf["masses"]) == 2 and abs(daten_lauf["masses"][1][1] - 19110.748) < 1e-3,
       "die Massen je Iteration werden gelesen (%s)" % (daten_lauf["masses"],))
pruefe(daten_lauf["done"] is True, "das Ende des Laufs wird erkannt")
pruefe(lauf_modul.read_history("gibt-es-nicht.log")["iteration"] == 0,
       "ohne Logdatei kommt ein leeres Ergebnis")

# --- shell thicknesses from the .inp (*SHELL SECTION) -----------------------
schale = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                      "schale_beispiel.inp")
dicken = elset_reader.read_shell_thicknesses(schale)
pruefe(dicken == {"MaterialSolidElementGeometry2D": 10.0,
                  "MaterialSolidElementGeometry2D001": 2.5},
       "die Schalendicken werden je Element-Set gelesen (%s)" % (dicken,))
# a solid model has no SHELL SECTION card
pruefe(elset_reader.read_shell_thicknesses(os.path.join(
           os.path.dirname(os.path.abspath(__file__)), "data", "beispiel.inp")) == {},
       "ohne SHELL SECTION bleibt die Dicke leer")

# the configuration takes over exactly the thicknesses of the existing domains
text_schale = conf_modul.conf_text(obj5, schale,
                                   {"MaterialSolidElementGeometry2D": "design",
                                    "MaterialSolidElementGeometry2D001": "non_design"},
                                   os.path.join("C:", os.sep, "tmp"))
pruefe("thickness = {'MaterialSolidElementGeometry2D': 10.0, "
       "'MaterialSolidElementGeometry2D001': 2.5}" in text_schale,
       "beide Dicken stehen in der Konfiguration")
pruefe("domain_thickness[_name] = [_d, _d]" in text_schale,
       "daraus wird besos domain_thickness je Domain")
text_nur_eine = conf_modul.conf_text(obj5, schale,
                                     {"MaterialSolidElementGeometry2D": "design"},
                                     os.path.join("C:", os.sep, "tmp"))
pruefe("thickness = {'MaterialSolidElementGeometry2D': 10.0}" in text_nur_eine,
       "nur die Dicke der vorhandenen Domain wird uebernommen")
pruefe("thickness = {}" in text,
       "ein Volumenmodell bekommt keine Schalendicke in die Konfiguration")

# --- permissible stress from the material -----------------------------------
from freecad.TopoOpt.core import material as material_modul  # noqa: E402

pruefe(material_modul.MPa("315 MPa") == 315.0,
       "eine Materialangabe in MPa wird gelesen (%s)" % material_modul.MPa("315 MPa"))
pruefe(abs(material_modul.MPa("2.1e+08 kg/(mm*s^2)") - 210000.0) < 1e-6,
       "FreeCADs Einheit kg/(mm*s^2) wird umgerechnet (%s)" % material_modul.MPa("2.1e+08 kg/(mm*s^2)"))
pruefe(material_modul.MPa("45 GPa") == 45000.0 and material_modul.MPa("1000 psi") > 6.8,
       "GPa und psi werden umgerechnet")
pruefe(material_modul.MPa("") is None and material_modul.MPa("zach MPa") is None
       and material_modul.MPa("5 fuss") is None,
       "unbrauchbare Angaben liefern keinen Vorschlag")

# Values as in FreeCAD's material cards: Aluminum-6061-T6 has 'YieldStrength: 276 MPa',
# CalculiX-Steel has no yield strength (only YoungsModulus)
streck = material_modul.yield_strength(
    [("MaterialSolidSolid", {"Name": "Alu", "YieldStrength": "276 MPa",
                             "UltimateTensileStrength": "310 MPa"})],
    ["MaterialSolidSolid"])
pruefe(streck == {"MaterialSolidSolid": 276.0},
       "die Streckgrenze der Karte wird zum Vorschlag (%s)" % (streck,))
ohne = material_modul.yield_strength(
    [("MaterialSolidSolid", {"Name": "CalculiX-Steel", "YoungsModulus": "2.1e+08 kg/(mm*s^2)"})],
    ["MaterialSolidSolid"])
pruefe(ohne == {}, "ohne Streckgrenze in der Karte kommt kein Vorschlag (%s)" % (ohne,))
mehrere = material_modul.yield_strength(
    [("MaterialSolid", {"YieldStrength": "276 MPa"}),
     ("AnderesMaterial", {"YieldStrength": "100 MPa"})],
    ["MaterialSolidSolid", "AnderesMaterialSolid"])
pruefe(mehrere == {"MaterialSolidSolid": 276.0, "AnderesMaterialSolid": 100.0},
       "bei mehreren Materialien wird ueber den Namen zugeordnet (%s)" % (mehrere,))
nur_eins = material_modul.yield_strength([("Irgendwas", {"YieldStrength": "235 MPa"})],
                                         ["VoelligAnderes"])
pruefe(nur_eins == {"VoelligAnderes": 235.0},
       "bei genau einem Material gilt es fuer alle Sets (%s)" % (nur_eins,))

# The assignment from the input file takes precedence: it says which material
# CalculiX really uses.  The name of the set only looks like a material.
section_inp = os.path.join(tempfile.gettempdir(), "topoopt_section_test.inp")
with open(section_inp, "w", encoding="utf8") as fh:
    fh.write("*NODE\n1, 0, 0, 0\n2, 1, 0, 0\n3, 0, 1, 0\n4, 0, 0, 1\n5, 1, 1, 0\n"
             "*ELEMENT, TYPE=C3D10, ELSET=MaterialSolidSolid\n1, 1,2,3,4,5\n"
             "*SOLID SECTION, ELSET=MaterialSolidSolid, MATERIAL=MaterialSolid\n"
             "*SHELL SECTION, ELSET=FlaechenSet, MATERIAL=MaterialSolid001, OFFSET=0\n5\n")
zuordnung = elset_reader.read_section_materials(section_inp)
pruefe(zuordnung == {"MaterialSolidSolid": "MaterialSolid", "FlaechenSet": "MaterialSolid001"},
       "die Materialzuordnung kommt aus den Section-Karten (%s)" % (zuordnung,))
aus_inp = material_modul.yield_strength(
    [("MaterialSolid", {"YieldStrength": "235 MPa"}),
     ("MaterialSolid001", {"YieldStrength": "276 MPa"})],
    ["MaterialSolidSolid"], {"MaterialSolidSolid": "MaterialSolid001"})
pruefe(aus_inp == {"MaterialSolidSolid": 276.0},
       "die Zuordnung aus der .inp schlaegt den Namensanfang (%s)" % (aus_inp,))
ohne_inp = material_modul.yield_strength(
    [("MaterialSolid", {"YieldStrength": "235 MPa"}),
     ("MaterialSolid001", {"YieldStrength": "276 MPa"})],
    ["MaterialSolidSolid"])
pruefe(ohne_inp == {"MaterialSolidSolid": 235.0},
       "ohne Zuordnung in der .inp greift der Namensanfang (%s)" % (ohne_inp,))

# A truncated input file and a set without a material assignment have to stand out
kaputt = os.path.join(tempfile.gettempdir(), "topoopt_kaputt.inp")
with open(kaputt, "w", encoding="utf8") as fh:
    fh.write("*NODE\n1, 0, 0, 0\n2, 1, 0, 0\n"
             "*ELEMENT, TYPE=C3D10, ELSET=Set1\n1, 1,2\n"
             "*MATERIAL, NAME=M1\n*ELASTIC\n210000, 0.3\n")
bericht = elset_reader.check_inp(kaputt, ["Set1"])
pruefe(bericht["missing_cards"] == ["*STEP"],
       "eine abgebrochene .inp wird erkannt (es fehlt %s)" % bericht["missing_cards"])
pruefe(bericht["without_material"] == ["Set1"],
       "dazu faellt das Set ohne Section-Karte auf (%s)" % bericht["without_material"])

ganz = os.path.join(tempfile.gettempdir(), "topoopt_ganz.inp")
with open(ganz, "w", encoding="utf8") as fh:
    fh.write("*NODE\n1, 0, 0, 0\n2, 1, 0, 0\n3, 0, 1, 0\n4, 0, 0, 1\n5, 1, 1, 0\n"
             "*ELEMENT, TYPE=C3D10, ELSET=Set1\n1, 1,2,3,4,5\n"
             "*ELSET, ELSET=Set2\n1\n"
             "*MATERIAL, NAME=M1\n*ELASTIC\n210000, 0.3\n"
             "*SOLID SECTION, ELSET=Set1, MATERIAL=M1\n"
             "*STEP\n*STATIC\n*BOUNDARY\n1, 1, 3, 0.0\n*END STEP\n")
bericht2 = elset_reader.check_inp(ganz, ["Set1", "Set2"])
pruefe(bericht2["missing_cards"] == [], "eine vollstaendige .inp meldet keine fehlende Karte")
pruefe(bericht2["without_material"] == ["Set2"],
       "nur das Set ohne Section-Karte wird genannt (%s)" % bericht2["without_material"])

# A material without a Young's modulus makes FreeCAD abort while writing the .inp
fehlend = material_modul.missing_values(
    [("Vollstaendig", {"YoungsModulus": "210000 MPa", "PoissonRatio": "0.3"}),
     ("Leer", {"Density": "7.9e-06 kg/mm^3"}),
     ("OhneNu", {"YoungsModulus": "210000 MPa"})])
pruefe(fehlend == {"Leer": ["YoungsModulus", "PoissonRatio"], "OhneNu": ["PoissonRatio"]},
       "fehlende Werkstoffwerte werden je Material gemeldet (%s)" % fehlend)
pruefe(material_modul.missing_values([("A", {"YoungsModulus": "x", "PoissonRatio": "y"})]) == {},
       "ein vollstaendiges Material wird nicht gemeldet")

# --- read VTK iterations (resulting_states.vtk) -------------------------------
from freecad.TopoOpt.core import vtk as vtk_modul  # noqa: E402

vtk_beispiel = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                            "states_beispiel.vtk")
vtk_daten = vtk_modul.load(vtk_beispiel)
pruefe(len(vtk_daten["points"]) == 170, "die Knoten werden gelesen (%d)"
       % len(vtk_daten["points"]))
pruefe(len(vtk_daten["cells"]) == 401, "die Zellen werden gelesen (%d)"
       % len(vtk_daten["cells"]))
pruefe(vtk_daten["cells"][0][0] < len(vtk_daten["points"]),
       "die Knotennummern sind 0-basiert (erste Nummer %d)" % vtk_daten["cells"][0][0])
pruefe(len(vtk_daten["states"]) == 2 and vtk_daten["names"][0] == "element_states001",
       "beide Iterationen werden gelesen (%s)" % (vtk_daten["names"],))

# The node numbers are 0-based: cells shifted by -1 give corners that lie far
# apart.  The test checks that the cells really hang together (small edge
# lengths) instead of relying on the order.
def _groesste_kante(punkte, zellen, zustand):
    groesste = 0.0
    for i, zelle in enumerate(zellen[:300]):
        if not zustand[i]:
            continue
        ecken = [punkte[zelle[j]] for j in range(4)]
        for a in range(4):
            for b in range(a + 1, 4):
                groesste = max(groesste, (ecken[a] - ecken[b]).Length)
    return groesste

richtig = _groesste_kante(vtk_daten["points"], vtk_daten["cells"], vtk_daten["states"][0])
verschoben = _groesste_kante(vtk_daten["points"],
                             [[k - 1 for k in zelle] for zelle in vtk_daten["cells"]],
                             vtk_daten["states"][0])
# The example mesh is coarse (beam 100 x 20 x 10 mm, 401 elements): the largest
# element edge is around 13 mm, with shifted numbers above 100 mm.
pruefe(richtig < 20, "mit 0-basierten Nummern bleibt die groesste Kante zur Elementgroesse "
       "passend (%.2f mm)" % richtig)
pruefe(verschoben > 5 * richtig,
       "mit -1 verschobenen Nummern wird das Netz zerfetzt (%.2f mm gegen %.2f mm, Faktor %.1f)"
       % (verschoben, richtig, verschoben / richtig))

zusammen = vtk_modul.summary(vtk_daten, 1)
pruefe(zusammen["number"] == 1 and zusammen["count"] == 2 and zusammen["total"] == 401,
       "die Zusammenfassung kennt Iteration, Anzahl und Zellen (%s)" % (zusammen,))
pruefe(0 <= zusammen["percent"] <= 100, "der Materialanteil liegt zwischen 0 und 100 %% (%.1f)"
       % zusammen["percent"])

flaechen = vtk_modul.boundary_faces(vtk_daten["cells"], vtk_daten["states"][-1],
                                    vtk_daten["points"])
pruefe(len(flaechen) > 100, "die Oberflaeche hat Flaechen (%d)" % len(flaechen))
volumen = vtk_modul.volume(vtk_daten["points"], flaechen)
pruefe(volumen > 0, "die Flaechen zeigen nach aussen (Volumen %.1f positiv)" % volumen)
zufall = vtk_modul.volume(vtk_daten["points"], [f[::-1] for f in flaechen])
pruefe(zufall < 0, "umgedrehte Flaechen ergeben negatives Volumen (%.1f)" % zufall)
kanten = vtk_modul.edge_check(flaechen)
pruefe(kanten.get(2, 0) > 0.9 * sum(kanten.values()),
       "die Kantenprobe zeigt eine geschlossene Oberflaeche (%s)" % (kanten,))
pruefe(vtk_modul.cell_volume(vtk_daten["points"], vtk_daten["cells"],
                             vtk_daten["states"][-1]) > 0,
       "das Zellvolumen des Materials ist positiv")

print()
if fehler:
    print("%d Pruefung(en) fehlgeschlagen" % len(fehler))
    beenden(1)
print("Alle Pruefungen bestanden", flush=True)
beenden(0)
