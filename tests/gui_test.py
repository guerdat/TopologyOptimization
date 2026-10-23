#!/usr/bin/env python
# SPDX-License-Identifier: LGPL-3.0-or-later
"""GUI test of the addon.

GUI FreeCAD writes nothing to stdout, so this script writes its result into
tests/gui_test_ausgabe.txt and quits FreeCAD afterwards:

    rm -f tests/gui_test_ausgabe.txt
    ("<FreeCAD>/bin/freecad.exe" "C:/.../tests/gui_test.py" >/dev/null 2>&1 &)
    # wait for the file, then read it

Checks: workbench registered and activatable, toolbar and menu present, icons
exist, the command works with and without an active analysis.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(HERE, "gui_test_ausgabe.txt")
lines = []
errors = []


def log(text):
    lines.append(str(text))


def check(condition, text):
    log("%-5s %s" % ("OK" if condition else "FEHLT", text))
    if not condition:
        errors.append(text)


try:
    import FreeCAD as App
    import FreeCADGui as Gui
    from PySide import QtWidgets

    log("FreeCAD %s" % ".".join(App.Version()[:3]))

    from freecad.TopoOpt.commands.create_optimization import (
        CreateOptimizationCommand,
        active_analysis,
    )

    # 1. Workbench
    workbenches = list(Gui.listWorkbenches().keys())
    check("TopoOptWorkbench" in workbenches, "Workbench TopoOptWorkbench ist registriert")
    if "TopoOptWorkbench" in workbenches:
        Gui.activateWorkbench("TopoOptWorkbench")
        Gui.updateGui()
        window = Gui.getMainWindow()
        toolbars = [tb.objectName() for tb in window.findChildren(QtWidgets.QToolBar)]
        menus = [m.title() for m in window.menuBar().findChildren(QtWidgets.QMenu)]
        check("TopoOpt" in toolbars, "Toolbar 'TopoOpt' vorhanden")
        check("TopoOpt" in menus, "Menue 'TopoOpt' vorhanden")
        wb = Gui.listWorkbenches()["TopoOptWorkbench"]
        check(os.path.isfile(wb.Icon), "Workbench-Icon existiert (%s)" % wb.Icon)

    # 2. Command and icon
    command = CreateOptimizationCommand()
    res = command.GetResources()
    check(command.Name == "TopoOpt_CreateOptimization", "Befehlsname ist TopoOpt_CreateOptimization")
    check(os.path.isfile(res["Pixmap"]), "Befehlssymbol existiert (%s)" % res["Pixmap"])
    log("     MenuText: %s" % res["MenuText"])

    # 3. no analysis
    doc = App.newDocument("TopoOptGuiTest")
    check(active_analysis() is None, "ohne Analyse ist keine aktiv")

    # 4. analysis present and active
    analysis = doc.addObject("Fem::FemAnalysis", "Analysis")
    doc.recompute()
    import FemGui
    FemGui.setActiveAnalysis(analysis)
    check(active_analysis() is analysis, "aktive Analyse wird gefunden")

    command.Activated()
    doc.recompute()
    obj = doc.getObject("TopologieOptimierung")
    check(obj is not None, "Befehl hat das Objekt angelegt")
    if obj is not None:
        check(obj.Name in [o.Name for o in analysis.Group], "Objekt liegt in der Analyse")
        check(os.path.isfile(obj.ViewObject.Proxy.getIcon()), "Objektsymbol existiert")

    # the assistant should have opened automatically (as with FEM commands)
    from freecad.TopoOpt.gui import assistant as assist
    panel = assist.panel_for(obj.Name) if obj is not None else None
    check(panel is not None, "Assistent oeffnet sich automatisch")
    if panel is not None:
        corners = panel.getStandardButtons()
        check(bool(corners & QtWidgets.QDialogButtonBox.Ok.value), "OK-Knopf vorhanden")
        check(bool(corners & QtWidgets.QDialogButtonBox.Close.value), "Schliessen-Knopf vorhanden")
        panel._close()
        check(assist.panel_for(obj.Name) is None, "Assistent wurde geschlossen")

    App.closeDocument(doc.Name)
    log("ERGEBNIS: %s" % ("OK" if not errors else "%d FEHLER" % len(errors)))
except Exception:
    log("AUSNAHME:\n" + traceback.format_exc())
    errors.append("Ausnahme")
finally:
    with open(OUTPUT, "w", encoding="utf8") as f:
        f.write("\n".join(lines) + "\n")
    sys.exit(1 if errors else 0)
