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
SUFFIX = "_state1.inp"


def latest_state1(folder):
    """The state file written last in the working directory.

    Sorted by modification time, not alphabetically: alphabetically the
    highest iteration number **of an earlier** run would be the "last" one.
    Returns the path or "".
    """
    if not folder or not os.path.isdir(folder):
        return ""
    candidates = [name for name in os.listdir(folder) if name.endswith(SUFFIX)]
    if not candidates:
        return ""
    candidates.sort(key=lambda name: os.path.getmtime(os.path.join(folder, name)))
    return os.path.join(folder, candidates[-1])


def load(path, document=None):
    """Put the mesh from a state file into the document as a mesh object.

    A missing importer is passed on as a clear message - without the FEM module
    FreeCAD cannot read the file.
    """
    if not path or not os.path.isfile(path):
        raise ValueError("Datei nicht gefunden: %s" % (path or "-"))
    try:
        import femimport                      # noqa: F401  (loads the importer)
    except Exception:
        pass
    from feminout import importInpMesh
    if document is not None:
        import FreeCADGui
        FreeCADGui.ActiveDocument = FreeCADGui.getDocument(document.Name)
    importInpMesh.import_inp(path)
    return path
