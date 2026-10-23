# SPDX-License-Identifier: LGPL-3.0-or-later
"""Finding the FEM parts of a document and preparing the CalculiX input file."""

import glob
import os
import re
import shutil
import tempfile
import time

NO_WHITESPACE = re.compile(r"\s")


def find_solver(analysis):
    """The solver object inside an analysis (or None)."""
    for member in analysis.Group:
        if "Solver" in member.TypeId:
            return member
    return None


def find_mesh(analysis):
    """The FEM mesh object inside an analysis (or None)."""
    for member in analysis.Group:
        if "FemMesh" in member.TypeId:
            return member
    return None


def find_materials(doc):
    """All material objects of the document, with their thickness objects."""
    materials, thicknesses = [], []
    for obj in doc.Objects:
        if obj.TypeId == "App::MaterialObjectPython" or "Material" in obj.TypeId:
            materials.append(obj)
        elif obj.TypeId == "Fem::ElementGeometry2D":
            thicknesses.append(obj)
    return materials, thicknesses


def run_dir(doc_name, base_name):
    """Fallback working directory - without spaces, inside temp.

    CalculiX cuts the job name at the first space, so a directory with spaces
    would silently produce a 0 byte .dat file.  Normally the FEM working
    directory of the solver is used (see working_dir()).
    """
    root = os.path.join(tempfile.gettempdir(), "TopoOpt")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", "%s_%s" % (doc_name, base_name))
    path = os.path.join(root, safe)
    os.makedirs(path, exist_ok=True)
    return path


def working_dir(solver, doc_name="TopoOpt", mesh=None, remembered=""):
    """The working directory the FEM workbench uses for this solver.

    The optimization object is a child of the FEM analysis, so its files belong
    next to the FEM files: FreeCAD's own function is used, which honours the user
    setting (temporary / beside the document / custom).

    `remembered` is the directory stored in the document object from an earlier run.
    It is used when it still exists, because FreeCAD's get_temp_dir() builds a new
    directory on every call (measured: it does not cache) - without this the files
    would end up in a different directory each time the dialog is opened.
    """
    if remembered and os.path.isdir(remembered):
        return remembered

    from femtools import femutils

    path = ""
    try:
        path = femutils.get_pref_working_dir(solver)
    except Exception:
        # e.g. MustSaveError when the user wants the directory beside an
        # unsaved document
        path = ""
    if not path:
        try:
            path = femutils.get_temp_dir(solver)
        except Exception:
            path = ""
    if not path:
        path = run_dir(doc_name, mesh.Name if mesh else "modell")
    os.makedirs(path, exist_ok=True)
    return path


def find_inp(solver, mesh, doc_name, remembered=""):
    """Look for an input file that already exists. Returns (path, source) or (None, "").

    If the user ran the analysis before (solver panel: "Write .inp file"), the
    file is already there and does not have to be written again:

    1. the FEM working directory of the solver (where FreeCAD writes it),
    2. FreeCAD's other FEM working directories (%TEMP%/fcfem_*), newest first,
    3. a working directory this addon used in an earlier version.
    """
    if mesh is None:
        return None, ""
    file_name = "%s.inp" % mesh.Name

    folder = working_dir(solver, doc_name, mesh, remembered)
    path = os.path.join(folder, file_name)
    if os.path.isfile(path):
        return path, "fem"

    candidates = []
    for other in glob.glob(os.path.join(tempfile.gettempdir(), "fcfem_*")):
        path = os.path.join(other, file_name)
        if os.path.isfile(path) and os.path.abspath(path) != os.path.abspath(
                os.path.join(folder, file_name)):
            candidates.append(path)
    if candidates:
        return max(candidates, key=os.path.getmtime), "other"

    path = os.path.join(run_dir(doc_name, mesh.Name), file_name)
    if os.path.isfile(path):
        return path, "own"
    return None, ""


def adopt_inp(source, solver, doc_name, mesh, remembered=""):
    """Copy an existing input file into the FEM working directory of the solver.

    The optimizer writes its iteration files next to the input file, so they
    belong next to the FEM files - and the directory the file came from stays
    untouched.  Returns the path of the copy.
    """
    target = os.path.join(working_dir(solver, doc_name, mesh, remembered), "%s.inp" % mesh.Name)
    if os.path.abspath(source) != os.path.abspath(target):
        shutil.copyfile(source, target)
    return target


def write_inp(analysis, solver, mesh, target_dir):
    """Create the input file with FreeCAD's writer and return its path.

    The order matters: setup_working_dir() first, then update_objects() (without
    it `f.mesh` is missing), and write_inp_file() last - set_inp_file_name()
    alone has no effect, the writer builds the name from working_dir + base_name.
    """
    from femtools import ccxtools

    if mesh is None:
        raise ValueError("Die Analyse enthaelt kein Netz.")
    if solver is None:
        raise ValueError("Die Analyse enthaelt keinen Solver.")
    if NO_WHITESPACE.search(os.path.abspath(target_dir)):
        raise ValueError("Der Arbeitsordner darf keine Leerzeichen enthalten: %s" % target_dir)

    fem = ccxtools.FemToolsCcx(analysis=analysis, solver=solver)
    fem.set_base_name(mesh.Name)
    os.makedirs(target_dir, exist_ok=True)
    fem.setup_working_dir(param_working_dir=target_dir, create=True)
    fem.setup_ccx()
    fem.update_objects()
    fem.write_inp_file()
    return fem.inp_file_name


def create_inp(analysis, solver, mesh, doc_name, remembered=""):
    """Write a new input file into the FEM working directory. Returns (path, seconds).

    FreeCAD creates the directory if it does not exist yet (it is the same
    directory the solver would use), so the files of the optimization sit next to
    the FEM files.
    """
    target = working_dir(solver, doc_name, mesh, remembered)
    if NO_WHITESPACE.search(os.path.abspath(target)):
        raise ValueError("Der Arbeitsordner darf keine Leerzeichen enthalten: %s" % target)
    start = time.time()
    path = write_inp(analysis, solver, mesh, target)
    return path, time.time() - start


def file_info(path):
    """Short description of a file for the user: size and timestamp."""
    if not path or not os.path.isfile(path):
        return ""
    size = os.path.getsize(path)
    unit = "kB"
    value = size / 1024.0
    if value > 1024:
        value, unit = value / 1024.0, "MB"
    modified = time.strftime("%d.%m.%Y %H:%M", time.localtime(os.path.getmtime(path)))
    return "%.1f %s, Stand %s" % (value, unit, modified)
