# SPDX-License-Identifier: LGPL-3.0-or-later
"""Load the result mesh of a run - the real FEM mesh, not an illustration.

beso saves every stored iteration as a pair of states ``<name>_state0.inp`` /
``<name>_state1.inp`` (state 1 = element remains, state 0 = element removed).
``state1`` is therefore the material that is left at the end - a proper
CalculiX input file with mesh nodes, elements and material data.

It is loaded with FreeCAD's own FEM import (``feminout.importInpMesh``), as it is
done with the importInpMesh from FreeCAD.  That produces a mesh object you can
continue working with in FreeCAD (for example an FEM calculation on it).

This is something different from the VTK player in ``core/vtk.py``: that one shows
the **surface** of the remaining material from ``resulting_states.vtk`` and
only serves for looking at it (and for the iteration movie).
"""

import os

# state file of an iteration ("file001_state1.inp")
ENDUNG = "_state1.inp"


def neueste_state1(ordner):
    """The state file written last in the working directory.

    Sorted by modification time, not alphabetically: alphabetically the
    highest iteration number **of an earlier** run would be the "last" one.
    Returns the path or "".
    """
    if not ordner or not os.path.isdir(ordner):
        return ""
    kandidaten = [name for name in os.listdir(ordner) if name.endswith(ENDUNG)]
    if not kandidaten:
        return ""
    kandidaten.sort(key=lambda name: os.path.getmtime(os.path.join(ordner, name)))
    return os.path.join(ordner, kandidaten[-1])


def laden(pfad, dokument=None):
    """Put the mesh from a state file into the document as a mesh object.

    A missing importer is passed on as a clear message - without the FEM module
    FreeCAD cannot read the file.
    """
    if not pfad or not os.path.isfile(pfad):
        raise ValueError("Datei nicht gefunden: %s" % (pfad or "-"))
    try:
        import femimport                      # noqa: F401  (loads the importer)
    except Exception:
        pass
    from feminout import importInpMesh
    if dokument is not None:
        import FreeCADGui
        FreeCADGui.ActiveDocument = FreeCADGui.getDocument(dokument.Name)
    importInpMesh.import_inp(pfad)
    return pfad
