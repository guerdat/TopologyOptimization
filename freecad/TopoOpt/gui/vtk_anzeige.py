# SPDX-License-Identifier: LGPL-3.0-or-later
"""Show the iterations of a run in FreeCAD.

Deliberately without any automation: the file is loaded on a click, exactly the
iteration in the field is shown, and the display is **one** mesh object that is
updated (not one object per iteration - that would flood the tree).
"""

import Mesh

from ..core import vtk as vtk_module


class Player(object):
    """Holds the loaded data and updates a mesh object."""

    def __init__(self, data, doc, object_name="TopoOpt_Iteration",
                 label="TopoOpt iteration"):
        self.points = data["points"]
        self.cells = data["cells"]
        self.states = data["states"]
        self.names = data["names"]
        self.doc = doc
        self.object_name = object_name
        self.label = label
        self._object = None

    @classmethod
    def load(cls, path, doc, object_name="TopoOpt_Iteration", label="TopoOpt iteration"):
        data = vtk_module.load(path)
        return cls(data, doc, object_name, label)

    @property
    def count(self):
        return len(self.states)

    def _display_object(self):
        if self._object is not None:
            return self._object
        obj = self.doc.getObject(self.object_name)
        if obj is None or not hasattr(obj, "Mesh"):
            if obj is not None:                     # wrong type occupies the name
                self.doc.removeObject(self.object_name)
            obj = self.doc.addObject("Mesh::Feature", self.object_name)
            obj.Label = self.label
        self._object = obj
        return obj

    def show(self, number, color=(0.80, 0.80, 0.84)):
        """Show iteration ``nummer`` (1-based) as a material surface."""
        number = max(1, min(self.count, int(number)))
        state = self.states[number - 1]
        faces = vtk_module.boundary_faces(self.cells, state, self.points)
        mesh = Mesh.Mesh()
        mesh.addFacets([(self.points[p], self.points[q], self.points[r])
                        for p, q, r in faces])
        obj = self._display_object()
        obj.Mesh = mesh
        self.doc.recompute()
        try:
            viewer = obj.ViewObject
            if viewer is not None:
                viewer.ShapeColor = color
                viewer.Visibility = True
        except Exception:
            pass
        result = vtk_module.summary({"cells": self.cells,
                                     "states": self.states,
                                     "names": self.names}, number)
        result["faces"] = len(faces)
        result["object"] = obj.Name
        return result
