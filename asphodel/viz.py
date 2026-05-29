"""
Visualization & output for the belief-cascade prototype.

All plotting uses a non-interactive matplotlib backend so it runs headless.
Three products:

  * time_series_plot  -- aggregate S/E/I/R/D, belief, panic count, infra fails
  * belief_snapshots  -- a grid of per-zone belief heatmaps over time (the
                         cascade made visible)
  * belief_animation  -- optional GIF of the same (requires pillow)
"""

from __future__ import annotations

import os

import numpy as np
import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt

from .runner import RunResult


def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)


def time_series_plot(result: RunResult, path: str, title: str | None = None) -> str:
    """Four-panel time-series summary of a run."""
    _ensure_dir(path)
    df = result.frame
    n_zones = result.graph.n_zones
    panic_thr = result.config.model.belief.panic_threshold

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle(title or f"Asphodel run: {result.config.name} (seed {result.seed})",
                 fontsize=14, fontweight="bold")

    # --- Panel 1: epidemic compartments -----------------------------------
    ax = axes[0, 0]
    ax.plot(df["day"], df["S"], label="S (susceptible)", color="tab:blue")
    ax.plot(df["day"], df["E"], label="E (exposed)", color="tab:orange")
    ax.plot(df["day"], df["I_asymp"], label="I asymptomatic (hidden)", color="tab:purple")
    ax.plot(df["day"], df["I_symp"], label="I symptomatic (visible)", color="tab:red")
    ax.plot(df["day"], df["R"], label="R (recovered)", color="tab:green")
    ax.plot(df["day"], df["D"], label="D (dead)", color="black")
    ax.set_title("Epidemic compartments (aggregate)")
    ax.set_xlabel("day"); ax.set_ylabel("people"); ax.legend(fontsize=8); ax.grid(alpha=0.3)

    # --- Panel 2: hidden vs visible infection + belief ---------------------
    ax = axes[0, 1]
    ax.plot(df["day"], df["I_asymp"], label="hidden infectious (I_a)", color="tab:purple")
    ax.plot(df["day"], df["I_symp"], label="visible infectious (I_s)", color="tab:red")
    ax.set_xlabel("day"); ax.set_ylabel("people")
    ax.set_title("Silent vs visible infection  +  mean belief")
    ax.grid(alpha=0.3)
    ax2 = ax.twinx()
    ax2.plot(df["day"], df["belief_mean"], label="mean belief", color="tab:gray", lw=2, ls="--")
    ax2.plot(df["day"], df["official_signal"], label="official signal", color="tab:cyan", lw=1.5)
    ax2.set_ylabel("belief / signal [0-1]"); ax2.set_ylim(-0.02, 1.05)
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="upper left")

    # --- Panel 3: the cascade -- zones in panic ----------------------------
    ax = axes[1, 0]
    ax.plot(df["day"], df["n_panic"], color="tab:red", lw=2,
            label=f"zones in panic (belief > {panic_thr})")
    ax.axhline(n_zones, color="gray", ls=":", lw=1, label=f"all {n_zones} zones")
    ax.set_title("Social tipping point: zones in panic")
    ax.set_xlabel("day"); ax.set_ylabel("# zones"); ax.set_ylim(0, n_zones * 1.05)
    ax.legend(fontsize=8); ax.grid(alpha=0.3)

    # --- Panel 4: infrastructure failures + outflow ------------------------
    ax = axes[1, 1]
    ax.plot(df["day"], df["n_power_fail"], label="zones power-fail", color="tab:orange")
    ax.plot(df["day"], df["n_water_fail"], label="zones water-fail", color="tab:blue")
    ax.set_title("Infrastructure failures  +  evacuation outflow")
    ax.set_xlabel("day"); ax.set_ylabel("# zones"); ax.grid(alpha=0.3)
    ax3 = ax.twinx()
    ax3.plot(df["day"], df["total_outflow"], label="outflow (people/tick)",
             color="tab:green", lw=1, alpha=0.7)
    ax3.set_ylabel("people moving / tick")
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax3.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="upper left")

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def belief_snapshots(result: RunResult, path: str, n_snapshots: int = 9) -> str:
    """Grid of per-zone belief heatmaps at evenly-spaced times (the cascade)."""
    _ensure_dir(path)
    hist = result.belief_history
    if hist is None:
        raise ValueError("RunResult has no belief_history (run with record_belief=True)")
    graph = result.graph
    dt = result.config.dt

    n_frames = hist.shape[0]
    idxs = np.linspace(0, n_frames - 1, n_snapshots).astype(int)

    cols = int(np.ceil(np.sqrt(n_snapshots)))
    rows = int(np.ceil(n_snapshots / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(3 * cols, 3 * rows))
    axes = np.atleast_1d(axes).ravel()

    for ax, k in zip(axes, idxs):
        grid = graph.to_grid(hist[k])
        im = ax.imshow(grid, vmin=0, vmax=1, cmap="inferno")
        ax.set_title(f"day {k * dt:.1f}", fontsize=10)
        ax.set_xticks([]); ax.set_yticks([])
    for ax in axes[len(idxs):]:
        ax.axis("off")

    fig.suptitle(f"Belief cascade across zones: {result.config.name}",
                 fontsize=13, fontweight="bold")
    fig.colorbar(im, ax=axes.tolist(), shrink=0.6, label="belief [0-1]")
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return path


def belief_animation(result: RunResult, path: str, fps: int = 12,
                     stride: int = 2) -> str | None:
    """Optional GIF animation of the belief heatmap over time."""
    _ensure_dir(path)
    hist = result.belief_history
    if hist is None:
        raise ValueError("RunResult has no belief_history")
    try:
        from matplotlib.animation import FuncAnimation, PillowWriter
    except Exception:
        return None

    graph = result.graph
    dt = result.config.dt
    frames = range(0, hist.shape[0], stride)

    fig, ax = plt.subplots(figsize=(5, 5))
    im = ax.imshow(graph.to_grid(hist[0]), vmin=0, vmax=1, cmap="inferno")
    ax.set_xticks([]); ax.set_yticks([])
    ttl = ax.set_title("day 0.0")
    fig.colorbar(im, ax=ax, shrink=0.8, label="belief [0-1]")

    def update(k):
        im.set_data(graph.to_grid(hist[k]))
        ttl.set_text(f"day {k * dt:.1f}")
        return im, ttl

    anim = FuncAnimation(fig, update, frames=frames, blit=False)
    try:
        anim.save(path, writer=PillowWriter(fps=fps))
    except Exception:
        plt.close(fig)
        return None
    plt.close(fig)
    return path
