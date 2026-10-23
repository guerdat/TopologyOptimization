#!/usr/bin/env python
# SPDX-License-Identifier: LGPL-3.0-or-later
"""Create the test document for the addon - a small FEM model, fully self made.

    ("<FreeCAD>/bin/freecad.exe" "C:/.../tests/make_test_document.py" >/dev/null 2>&1 &)

The document is written to %TEMP%/TopoOpt_Test/modell.FCStd (path can be given in
the environment variable TOPOOPT_TEST_DOKUMENT) and contains: a box, a material, a
FEM analysis with a coarse gmsh mesh and a CalculiX solver.  It is deliberately
small (a few hundred elements), so the tests run in seconds, and it is created
from scratch instead of using a document of the developer's own project.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(HERE, "make_test_document_ausgabe.txt")

lines = []


def log(text):
    lines.append(str(text))


try:
    import FreeCAD as App
    import ObjectsFem
    from PySide import QtWidgets

    FreeCADGui = None
    try:
        import FreeCADGui
    except ImportError:
        pass

    target = os.environ.get("TOPOOPT_TEST_DOKUMENT") or os.path.join(
        os.environ.get("TEMP", "/tmp"), "TopoOpt_Test", "modell.FCStd")
    os.makedirs(os.path.dirname(target), exist_ok=True)

    doc = App.newDocument("TopoOpt_Testmodell")

    # 1. the geometry: a beam 100 x 20 x 10 mm
    box = doc.addObject("Part::Box", "Balken")
    box.Length = 100.0
    box.Width = 20.0
    box.Height = 10.0
    doc.recompute()

    # 2. material - assigned to the body, otherwise FreeCAD writes no
    #    material ELSET into the input file (and the domains table stays empty)
    material = ObjectsFem.makeMaterialSolid(doc, "MaterialSolid")
    material.Material = {
        "Name": "Steel",
        "YoungsModulus": "210000 MPa",
        "PoissonRatio": "0.30",
        "Density": "7900 kg/m^3",
    }
    material.References = [(box, "Solid1")]

    # 3. meshing (coarse so the tests are fast)
    mesh = ObjectsFem.makeMeshGmsh(doc, "FEMMeshGmsh")
    mesh.Shape = box
    mesh.CharacteristicLengthMax = 8.0
    mesh.CharacteristicLengthMin = 8.0
    doc.recompute()

    # 4. analysis with mesh, material and solver
    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "SolverCalculiX")
    analysis.addObject(material)
    analysis.addObject(mesh)
    analysis.addObject(solver)
    doc.recompute()

    # 5. really create the mesh (gmsh runs as an external program)
    import femmesh.gmshtools as gmshtools
    result = gmshtools.GmshTools(mesh).create_mesh()
    log("Netz erzeugt: %s" % result)
    log("Knoten: %d, Volumenelemente: %d"
        % (mesh.FemMesh.NodeCount, mesh.FemMesh.VolumeCount))

    doc.recompute()
    doc.saveAs(target)
    log("Dokument gespeichert: %s (%d Bytes)" % (target, os.path.getsize(target)))
    log("Objekte: %s" % ", ".join(sorted(o.Name for o in doc.Objects)))

    if FreeCADGui is not None:
        App.closeDocument(doc.Name)
    log("ERGEBNIS: OK")
except Exception:
    log("AUSNAHME:\n" + traceback.format_exc())

with open(OUTPUT, "w", encoding="utf8") as f:
    f.write("\n".join(lines) + "\n")

if FreeCADGui is not None:
    sys.exit(0)
print("\n".join(lines))
