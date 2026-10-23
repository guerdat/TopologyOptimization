# SPDX-License-Identifier: LGPL-3.0-or-later
"""Live charts of a running optimization - an own window in FreeCAD.

Like CfdOF: FreeCAD's own Plot module
(``Mod/Plot``) shows matplotlib as an MDI child window, a QTimer redraws it every
1.5 s, so the charts follow the run.

Four charts in one window (drawn from the iteration table in beso's log file):

1. mass in percent of the first mass (dashed line = target mass)
2. FI_mean and FI_max (dashed line at 1.0 = limit)
3. overloaded elements (FI_violated)
4. mean energy density

The values come from ``core/lauf.py``, so this module only draws.
"""

import time

from PySide import QtCore

COLORS = {
    "mass": "#1f77b4",
    "target": "#7f7f7f",
    "fi_mean": "#2ca02c",
    "fi_max": "#d62728",
    "fi_violated": "#ff7f0e",
    "limit": "#7f7f7f",
    "ener": "#9467bd",
}
WINDOW_TITLE = "Topology optimization - history"
# Height of the four charts in the window (bottom first, then upwards)
POSITIONS = ((0.14, 0.07, 0.82, 0.18), (0.14, 0.29, 0.82, 0.18),
             (0.14, 0.51, 0.82, 0.18), (0.14, 0.73, 0.82, 0.18))


class History(object):
    """Collects the iteration values and draws them into a plot window."""

    def __init__(self, title=WINDOW_TITLE, target_mass=None):
        self.title = title
        self.target_mass = target_mass
        self.values = []                  # [(iteration, dict), ...]
        self.closed = False
        self.running = False
        self._window = None
        self._axes = []
        self._start_time = None
        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self.draw)
        self._timer.start(1500)

    # ------------------------------------------------------------------- Data
    def set_values(self, values):
        self.values = list(values or [])

    def reset(self):
        self.values = []
        self.closed = False
        self._start_time = time.time()

    # ----------------------------------------------------------------- Window
    def show(self):
        """Show the window (creating it when there is none yet)."""
        self.closed = False
        window = self._ensure_window()
        self.draw(force=True)
        self._bring_to_front(window)
        return window

    def _bring_to_front(self, window):
        """Activate the window's tab - when it already exists, nothing visible would happen otherwise."""
        if window is None:
            return
        try:
            tab = window.parentWidget() if not hasattr(window, "mdiArea") else window
            mdi = tab.mdiArea() if hasattr(tab, "mdiArea") else None
            if mdi is not None:
                mdi.setActiveSubWindow(tab)
            # only when it really is minimized: in tab mode the tabs are internally
            # maximized - a showNormal() would turn them into free-standing windows
            if tab.isMinimized():
                tab.showNormal()
            tab.raise_()
            tab.activateWindow()
        except Exception:
            pass

    def close(self):
        """After a run: stop the timer (the window stays open)."""
        self._timer.stop()

    def _ensure_window(self):
        if self._window is not None:
            return self._window
        try:
            from FreeCAD.Plot import Plot
        except Exception:
            return None
        try:
            window = Plot.figure(self.title)
        except Exception:
            return None
        if window is None:
            return None
        self._window = window
        try:
            window.destroyed.connect(self._window_closed)
        except Exception:
            pass
        # Important: also put the first axes created by the Plot module at its own
        # position - otherwise it spans the whole window height.
        fig = window.fig
        self._axes = [window.axes]
        try:
            window.axes.set_position(POSITIONS[0])
        except Exception:
            pass
        for rect in POSITIONS[1:]:
            try:
                self._axes.append(fig.add_axes(rect))
            except Exception:
                pass
        return self._window

    def _window_closed(self, *_):
        """Closed by the user - do not reopen it unasked."""
        self._window = None
        self._axes = []
        self.closed = True

    # ---------------------------------------------------------------- Drawing
    def draw(self, force=False):
        if not self.values:
            if (self.running or force) and not self.closed:
                self._waiting_note()
            return
        if self.closed and not force:
            return
        window = self._ensure_window()
        if window is None or len(self._axes) < 4:
            return

        for axis, rect in zip(self._axes, POSITIONS):
            try:
                axis.set_position(list(rect))
            except Exception:
                pass

        iterations = [i for i, _ in self.values]

        def column(name):
            return [(row.get(name) if row else None) for _, row in self.values]

        masses = column("mass")
        fi_mean = column("fi_mean")
        fi_max = column("fi_max")
        overloaded = column("fi_violated")
        energies = column("ener")

        # 1) mass in percent
        axis = self._axes[3]
        axis.cla()
        axis.set_ylabel("Mass [%]", fontsize=8)
        axis.tick_params(labelsize=7, labelbottom=False)
        start = next((m for m in masses if m), None)
        if start:
            axis.plot(iterations,
                      [100.0 * (m / start if m else float("nan")) for m in masses],
                      color=COLORS["mass"], lw=1.2, marker="o", markersize=2.5)
            if self.target_mass:
                axis.axhline(100.0 * self.target_mass, color=COLORS["target"], ls="--", lw=1)
        axis.grid(True, alpha=0.3)
        axis.set_title("Optimization history", fontsize=9)

        # 2) utilisation
        axis = self._axes[2]
        axis.cla()
        axis.set_ylabel("FI", fontsize=8)
        axis.tick_params(labelsize=7, labelbottom=False)
        if any(v is not None for v in fi_mean):
            axis.plot(iterations, fi_mean, color=COLORS["fi_mean"], lw=1.2, marker="o",
                      markersize=2.2, label="FI_mean")
        if any(v is not None for v in fi_max):
            axis.plot(iterations, fi_max, color=COLORS["fi_max"], lw=1.2, marker="o",
                      markersize=2.2, label="FI_max")
            axis.axhline(1.0, color=COLORS["limit"], ls="--", lw=1, label="limit 1.0")
            axis.legend(loc="upper right", fontsize=7)
        else:
            axis.text(0.5, 0.5, "no failure index in this run", ha="center", va="center",
                      fontsize=7, color="#666666", transform=axis.transAxes)
        axis.grid(True, alpha=0.3)

        # 3) overloaded elements
        axis = self._axes[1]
        axis.cla()
        axis.set_ylabel("overloaded", fontsize=8)
        axis.tick_params(labelsize=7, labelbottom=False)
        if any(v is not None for v in overloaded):
            values = [0 if v is None else v for v in overloaded]
            axis.step(iterations, values, where="post", color=COLORS["fi_violated"], lw=1.2,
                      marker="o", markersize=2.2)
            axis.set_ylim(bottom=-0.5)
        else:
            axis.text(0.5, 0.5, "no failure index in this run", ha="center", va="center",
                      fontsize=7, color="#666666", transform=axis.transAxes)
        axis.grid(True, alpha=0.3)

        # 4) energy density
        axis = self._axes[0]
        axis.cla()
        axis.set_xlabel("iteration", fontsize=8)
        axis.set_ylabel("energy density", fontsize=8)
        axis.tick_params(labelsize=7)
        if any(v is not None for v in energies):
            axis.plot(iterations, energies, color=COLORS["ener"], lw=1.2, marker="o",
                      markersize=2.2)
        axis.grid(True, alpha=0.3)

        try:
            window.fig.canvas.draw()
        except Exception:
            pass

    def _waiting_note(self):
        """Placeholder while the first iteration is still running."""
        window = self._ensure_window()
        if window is None or not self._axes:
            return
        for axis in self._axes:
            try:
                axis.cla()
            except Exception:
                pass
        axis = self._axes[0]
        elapsed = ""
        if self._start_time:
            seconds = int(max(0, time.time() - self._start_time))
            elapsed = "Optimization running for %d:%02d\n" % (seconds // 60, seconds % 60)
        axis.text(0.5, 0.55,
                  elapsed + "no iteration finished yet - the preparation is running:\n"
                  "reading the input file and building the filter neighbourhood",
                  ha="center", va="center", fontsize=8, transform=axis.transAxes)
        axis.text(0.5, 0.28,
                  "The first iteration of a fine mesh takes a while.\n"
                  "After that one point is added per iteration.",
                  ha="center", va="center", fontsize=7.5, color="#666666",
                  transform=axis.transAxes)
        try:
            window.fig.canvas.draw()
        except Exception:
            pass
