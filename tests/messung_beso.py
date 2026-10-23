# SPDX-License-Identifier: LGPL-3.0-or-later
"""Measure the preparation time of a beso copy (called from vergleich_varianten.py).

Parameters: <beso-directory> <inp-file> <elset>
Prints one line with the times so the harness can collect them.
Each variant runs in its own process because each brings its own
beso_lib/beso_filters.
"""
import os
import sys
import time

beso_folder, inp, elset = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, beso_folder)

import beso_filters                          # noqa: E402
import beso_lib                              # noqa: E402

t0 = time.time()
read_result = beso_lib.import_inp(inp, [elset], {elset: True}, False)
t_import = time.time() - t0
nodes, elements, opt_domains = read_result[0], read_result[1], read_result[3]

t0 = time.time()
cg, cg_min, cg_max = beso_lib.elm_volume_cg(inp, nodes, elements)[:3]
t_cg = time.time() - t0

t0 = time.time()
sizes = beso_filters.find_size_elm(elements, nodes)
t_size = time.time() - t0
mean_size = sum(sizes[en] for en in opt_domains) / len(opt_domains)

t0 = time.time()
weight_factor2, near_elm = beso_filters.prepare2s(cg, cg_min, cg_max, 2.0 * mean_size, opt_domains,
                                                 {}, {})
t_prep = time.time() - t0

print("MESSUNG|%.2f|%.2f|%.2f|%.2f|%d|%d|%.4f"
      % (t_import, t_cg, t_size, t_prep, len(opt_domains),
         sum(len(v) for v in near_elm.values()), mean_size), flush=True)
sys.stdout.flush()
os._exit(0)
