# SPDX-License-Identifier: LGPL-3.0-or-later
"""Create small CalculiX models for the scenario matrix.

beso reads only the ``.inp`` - FreeCAD does not have to run for that.  The models
here are tiny (8 hexahedra or 8 triangles) and have real loads and supports, so that
``stiffness`` does not fail on missing CalculiX results.

Written to ``tests/szenarien``:
  modell_3d_hex.inp    2x2x2 hexahedra (C3D8), 20 mm cube, tension from above
  modell_2d_schale.inp 2x4 S3 triangles, 20 x 10 mm, 5 mm thick, tension at the edge
  modell_2d_ohne_dicke.inp  the same without *SHELL SECTION (error case)

Call:  python tests/make_szenario_inp.py   (plain Python, no FreeCAD)
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "szenarien")


def hexahedron_model(edge_length=20.0, parts=2, two_sets=False):
    """Cube made of hexahedra, fixed at the bottom, tension applied at the top.

    With ``zwei_sets`` two element sets with their own material each appear -
    the case "one domain without a permissible stress".
    """
    step = edge_length / parts
    nodes = {}
    lines = ["*NODE"]
    number = 0
    for k in range(parts + 1):
        for j in range(parts + 1):
            for i in range(parts + 1):
                number += 1
                nodes[(i, j, k)] = number
                lines.append("%d, %.6f, %.6f, %.6f"
                              % (number, i * step, j * step, k * step))
    total = parts ** 3
    half = total // 2
    first_set = "SetA" if two_sets else "MaterialSolidSolid"
    elements = ["*ELEMENT, TYPE=C3D8, ELSET=%s" % first_set]
    number = 0
    second_lines = []
    for k in range(parts):
        for j in range(parts):
            for i in range(parts):
                number += 1
                e = [nodes[(i, j, k)], nodes[(i + 1, j, k)],
                     nodes[(i + 1, j + 1, k)], nodes[(i, j + 1, k)],
                     nodes[(i, j, k + 1)], nodes[(i + 1, j, k + 1)],
                     nodes[(i + 1, j + 1, k + 1)], nodes[(i, j + 1, k + 1)]]
                line = "%d, %s" % (number, ", ".join(str(x) for x in e))
                if two_sets and number > half:
                    second_lines.append(line)
                else:
                    elements.append(line)
    if two_sets:
        elements.append("*ELEMENT, TYPE=C3D8, ELSET=SetB")
        elements += second_lines
    bottom = [nodes[(i, j, 0)] for i in range(parts + 1) for j in range(parts + 1)]
    top = [nodes[(i, j, parts)] for i in range(parts + 1) for j in range(parts + 1)]
    if two_sets:
        header = [
            "*ELSET, ELSET=Eall",
            "SetA",
            "SetB",
            "*MATERIAL, NAME=MaterialSolid",
            "*ELASTIC",
            "210000, 0.3",
            "*DENSITY",
            "7.9e-09",
            "*MATERIAL, NAME=MaterialSolid001",
            "*ELASTIC",
            "70000, 0.33",
            "*DENSITY",
            "2.7e-09",
            "*SOLID SECTION, ELSET=SetA, MATERIAL=MaterialSolid",
            "*SOLID SECTION, ELSET=SetB, MATERIAL=MaterialSolid001",
        ]
    else:
        header = [
            "*ELSET, ELSET=Eall",
            "MaterialSolidSolid",
            "*MATERIAL, NAME=MaterialSolid",
            "*ELASTIC",
            "210000, 0.3",
            "*DENSITY",
            "7.9e-09",
        ]
    return "\n".join(lines + elements + header + [
        "*BOUNDARY",
        "\n".join("%d, 1, 3, 0.0" % n for n in bottom),
        "*STEP",
        "*STATIC",
        "*CLOAD",
        "\n".join("%d, 3, -%.1f" % (n, 1000.0 / len(top)) for n in top),
        "*NODE FILE",
        "U",
        "*EL FILE",
        "S, E, ENER",
        "*END STEP",
        "",
    ])


def shell_model(thickness=5.0, with_thickness=True):
    """Surface 20 x 10 mm made of two S3 strips, fixed on the left, tension at the
    bottom right."""
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0),
              (0.0, 10.0), (10.0, 10.0), (20.0, 10.0)]
    lines = ["*NODE"]
    for i, (x, y) in enumerate(points, start=1):
        lines.append("%d, %.6f, %.6f, 0.0" % (i, x, y))
    lines.append("*ELEMENT, TYPE=S3, ELSET=MaterialSolidElementGeometry2D")
    lines.append("1, 1, 2, 5")
    lines.append("2, 1, 5, 4")
    lines.append("3, 2, 3, 6")
    lines.append("4, 2, 6, 5")
    lines += ["*ELSET, ELSET=Eall", "MaterialSolidElementGeometry2D"]
    if with_thickness:
        lines += ["*SHELL SECTION, ELSET=MaterialSolidElementGeometry2D, "
                   "MATERIAL=MaterialSolid, OFFSET=0", "%g" % thickness]
    lines += [
        "*MATERIAL, NAME=MaterialSolid",
        "*ELASTIC",
        "210000, 0.3",
        "*DENSITY",
        "7.9e-09",
        "*BOUNDARY",
        "1, 1, 3, 0.0",
        "4, 1, 3, 0.0",
        "*STEP",
        "*STATIC",
        "*CLOAD",
        "3, 2, -500.0",
        "6, 2, -500.0",
        "*NODE FILE",
        "U",
        "*EL FILE",
        "S, E, ENER",
        "*END STEP",
        "",
    ]
    return "\n".join(lines)


def main():
    if not os.path.isdir(TARGET):
        os.makedirs(TARGET)
    files = {
        "modell_3d_hex.inp": hexahedron_model(),
        "modell_2sets.inp": hexahedron_model(two_sets=True),
        "modell_2d_schale.inp": shell_model(),
        "modell_2d_ohne_dicke.inp": shell_model(with_thickness=False),
    }
    for name, content in files.items():
        path = os.path.join(TARGET, name)
        with open(path, "w", encoding="utf8", newline="\n") as fh:
            fh.write(content)
        print("%-28s %6d Zeilen" % (name, content.count("\n")), flush=True)
    print("Ordner:", TARGET, flush=True)


main()
