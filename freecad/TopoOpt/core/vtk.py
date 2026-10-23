# SPDX-License-Identifier: LGPL-3.0-or-later
"""Read ``resulting_states.vtk`` - the material states of every iteration.

beso writes this file once at the end of a run.  It contains **all** iterations as
separate cell fields:

    POINTS 72051            node coordinates (3 numbers per node)
    CELLS 41666 458326      per cell "10 <10 node numbers>" (TETRA10)
    CELL_TYPE 41666         all 24 (quadratic tetrahedron)
    CELL_DATA 41666         44 x "SCALARS element_statesNNN float" (0/1 per element)

Shown is the **surface of the material that is left**: from every tetrahedron with
state 1 the four triangles are collected and only the ones that occur once are
drawn - those are exactly the boundary faces.

The reader for these files; the three traps it
had to solve are noted at the places where they are handled:

* node numbers are **0-based** (see :func:`load`),
* the ``LOOKUP_TABLE`` line must not end a section (see :func:`_sections`),
* the triangles must be turned outwards (see :func:`boundary_faces`).
"""

import os

import FreeCAD


def _sections(path):
    """Split the file into sections: keyword line -> following lines.

    More reliable than guessing line by line, because VTK wraps the numbers
    anywhere (the POINTS lines carry two nodes, the state lines 30 values).
    """
    sections = []
    current = None
    with open(path, "r", encoding="utf8", errors="replace") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped[0].isalpha():
                # "LOOKUP_TABLE default" belongs to the SCALARS section before it and
                # must not end it - otherwise every state value lands in that line and
                # the iterations stay empty.
                if stripped.split()[0].upper() == "LOOKUP_TABLE":
                    continue
                current = [stripped, []]
                sections.append(current)
            elif current is not None:
                current[1].extend(stripped.split())
    return sections


def load(path):
    """Read nodes, cells and the state arrays.

    Returns dict with ``points`` (list of Vector), ``cells`` (list of 10 node
    indices), ``states`` (list of bytearray, one per iteration) and ``names``
    (iteration names from the file).

    Important: the node numbers in the file are **0-based** and are used directly as
    index into ``points``.  Subtracting 1 (as with CalculiX .inp) moves every cell;
    because Netgen does not number the nodes spatially, this creates far apart
    "corner nodes" and a torn mesh.  Measured on 300 cells: largest edge among the
    four corners median 1.42 mm, max 2.18 mm (right) against median 2.83 mm,
    max 81.76 mm (with -1).
    """
    sections = _sections(path)
    points, cells, states, names = [], [], [], []
    for header, values in sections:
        parts = header.split()
        key = parts[0].upper()
        if key == "POINTS":
            count = int(parts[1])
            numbers = [float(w) for w in values[:3 * count]]
            points = [FreeCAD.Vector(numbers[i], numbers[i + 1], numbers[i + 2])
                      for i in range(0, len(numbers) - 2, 3)]
        elif key == "CELLS" and len(parts) >= 2:
            count = int(parts[1])
            rest = [int(w) for w in values]
            i, read_count = 0, 0
            while read_count < count and i < len(rest):
                nodes_per_cell = rest[i]
                i += 1
                # node numbers are 0-based - do NOT subtract 1 (see docstring)
                cells.append(list(rest[i:i + nodes_per_cell]))
                i += nodes_per_cell
                read_count += 1
        elif key == "SCALARS" and len(parts) >= 2:
            count = len(cells)
            data = bytearray(count)
            for i, w in enumerate(values[:count]):
                data[i] = 1 if float(w) > 0.5 else 0
            names.append(parts[1])
            states.append(data)
    if not points or not cells or not states:
        raise ValueError("file contains no points/cells/states (%s)"
                         % os.path.basename(path))
    return {"points": points, "cells": cells, "states": states, "names": names}


def boundary_faces(cells, state, points):
    """Outward facing triangles of the material surface.

    From every tetrahedron with state 1 the four triangles are collected; a triangle
    two material cells share is inside and falls away.  Counting uses a dict (a list
    would be quadratic).

    The triangles are turned **outwards**: the normal has to point away from the
    fourth node of the tetrahedron.  Without that turn about half of the faces point
    inwards and are lit wrongly - that looks like a hole in the tree (seen in tests).

    Returns list of (i, j, k) node indices, oriented outwards.
    """
    faces = {}
    for i, cell in enumerate(cells):
        if not state[i]:
            continue
        corners = (cell[0], cell[1], cell[2], cell[3])
        for k in range(4):
            opposite = corners[k]
            triangle = tuple(corners[j] for j in range(4) if j != k)
            key = tuple(sorted(triangle))
            if key in faces:
                faces[key] = None            # inside: shared by two cells
            else:
                faces[key] = (triangle, opposite)

    result = []
    for key, value in faces.items():
        if value is None:
            continue
        triangle, opposite = value
        p0, p1, p2 = (points[triangle[0]], points[triangle[1]], points[triangle[2]])
        normal = (p1 - p0).cross(p2 - p0)
        if normal.dot(p0 - points[opposite]) < 0:
            triangle = (triangle[0], triangle[2], triangle[1])
        result.append(triangle)
    return result


def edge_check(triangles):
    """How often does every edge occur?  Closed surface -> always 2."""
    counter = {}
    for a, b, c in triangles:
        for p, q in ((a, b), (b, c), (c, a)):
            key = (p, q) if p < q else (q, p)
            counter[key] = counter.get(key, 0) + 1
    distribution = {}
    for count in counter.values():
        distribution[count] = distribution.get(count, 0) + 1
    return distribution


def volume(points, triangles):
    """Signed volume of the faces (correctly oriented -> positive)."""
    total = 0.0
    for a, b, c in triangles:
        p0, p1, p2 = points[a], points[b], points[c]
        total += p0.dot(p1.cross(p2))
    return total / 6.0


def cell_volume(points, cells, state):
    """Sum of the volumes of all material cells (corner nodes only)."""
    total = 0.0
    for i, cell in enumerate(cells):
        if not state[i]:
            continue
        a, b, c, d = (points[cell[0]], points[cell[1]],
                      points[cell[2]], points[cell[3]])
        total += abs((b - a).dot((c - a).cross(d - a))) / 6.0
    return total


def summary(data, number):
    """How much material is left in iteration ``number`` (1-based)?"""
    count = len(data["states"])
    number = max(1, min(count, int(number)))
    state = data["states"][number - 1]
    material = int(sum(state))
    total = len(data["cells"])
    return {"number": number, "count": count,
            "name": data["names"][number - 1] if number <= len(data["names"]) else "",
            "cells": material, "total": total,
            "percent": 100.0 * material / max(1, total)}
