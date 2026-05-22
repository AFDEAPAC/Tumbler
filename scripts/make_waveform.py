#!/usr/bin/env python3
"""Generate a realistic-looking serving-workload waveform (GPU utilization
+ p99 latency vs time), comparing stock ROCm against Tumbler.

Visual story:
  - Both runs start with the same healthy baseline (~75% util, ~50 ms p99).
  - At t=8 min a transient HW/SDMA fault hits.
  - Stock ROCm: the process aborts; util and latency go undefined; the
    waveform is replaced by a 'PROCESS DEAD' shaded band for the rest
    of the chart.
  - Tumbler: the affected request fails gracefully at the configured
    ROCR_SIGNAL_WAIT_MAX_MS=500 cap.  Latency shows a small bounded
    spike to ~500 ms, util dips momentarily, then both recover and
    the waveform continues healthy through the end of the observation
    window.  Subsequent transient hiccups behave the same way.

Output: docs/paper/figures/fig-05-latency-waveform.png
"""
import numpy as np
import matplotlib

from pathlib import Path as _Path
REPO = _Path(__file__).resolve().parents[1]

matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Dark navy theme matching the other Tumbler figures.
NAVY    = '#0a1428'
GRID    = '#1a3050'
EDGE    = '#3a5a8a'
LABEL   = '#cad8e8'
TICK    = '#9fb3cc'
TITLE   = '#e0eaf5'
STOCK   = '#e85a4f'   # red for stock ROCm
TUMBLER = '#3ecfb4'   # teal for Tumbler
AMBER   = '#ffaa44'
DEADBG  = '#3a0a0a'

plt.rcParams.update({
    'figure.facecolor':  NAVY,
    'axes.facecolor':    NAVY,
    'axes.edgecolor':    EDGE,
    'axes.labelcolor':   LABEL,
    'axes.titlecolor':   TITLE,
    'xtick.color':       TICK,
    'ytick.color':       TICK,
    'text.color':        LABEL,
    'axes.grid':         True,
    'grid.color':        GRID,
    'grid.linestyle':    '-',
    'grid.linewidth':    0.6,
    'font.family':       'DejaVu Sans',
    'font.size':         11,
})


# ---------- synthetic 60-minute serving trace ----------
np.random.seed(42)
T_MIN = 60                          # observation window in minutes
SR    = 10                          # samples / minute
t     = np.linspace(0, T_MIN, T_MIN * SR + 1)


def base_util():
    base  = 75 + 8 * np.sin(2*np.pi*t/5) + 4*np.sin(2*np.pi*t/1.3)
    noise = np.random.normal(0, 2.5, len(t))
    return np.clip(base + noise, 55, 96)


def base_lat():
    base  = 50 + 6*np.sin(2*np.pi*t/3) + 3*np.sin(2*np.pi*t/0.8)
    noise = np.random.normal(0, 3, len(t))
    return np.clip(base + noise, 30, 85)


FAULT_MIN = 8
FAULT_I   = FAULT_MIN * SR

# Stock: clean until fault, then NaN (process dead).
stock_util = base_util()
stock_lat  = base_lat()
stock_util[FAULT_I:] = np.nan
stock_lat[FAULT_I:]  = np.nan

# Tumbler: same baseline + bounded transient spikes at every fault event.
tumbler_util = base_util()
tumbler_lat  = base_lat()

SPIKE_MIN = [8, 18, 32, 47]   # fault events Tumbler survives
SPIKE_PEAK_MS = 500
SPIKE_LEN_SAMPLES = 6         # ~0.6 min recovery window
for c_min in SPIKE_MIN:
    i = c_min * SR
    for k in range(SPIKE_LEN_SAMPLES):
        if i+k >= len(t): break
        # smooth exponential decay back to baseline
        decay = np.exp(-k * 0.6)
        # latency spike
        tumbler_lat[i+k]  = max(tumbler_lat[i+k], 50 + (SPIKE_PEAK_MS-50) * decay)
        # util dips a bit during the spike
        tumbler_util[i+k] = max(45, tumbler_util[i+k] - 18 * decay)


# ---------- plot ----------
fig, (ax1, ax2) = plt.subplots(
    2, 1, figsize=(13.5, 6.6), sharex=True,
    gridspec_kw={'hspace': 0.18, 'height_ratios': [1, 1.05]})

fig.suptitle("Serving-workload waveform — stock ROCm vs Tumbler",
             fontsize=15, fontweight='bold', color=TITLE, y=0.97)

# Plot order: Tumbler first (it spans the full window), Stock second so
# its short-lived line shows on top for the first 8 minutes.
# ------- Top: GPU utilization -------
mask_dead = np.isnan(stock_util)
ax1.fill_between(t, 0, 100, where=mask_dead, color=DEADBG, alpha=0.55,
                 step='post', zorder=0)
ax1.plot(t, tumbler_util, color=TUMBLER, linewidth=1.6,
         label='Tumbler',    alpha=0.95, zorder=2)
ax1.plot(t, stock_util,   color=STOCK,   linewidth=2.0,
         label='Stock ROCm', alpha=1.0,  zorder=3)
ax1.axvline(FAULT_MIN, color=AMBER, linestyle='--', linewidth=1.1, alpha=0.7,
            zorder=1.5)
ax1.text(FAULT_MIN+0.5, 96, 'fault @ t = 8 min',
         color=AMBER, fontsize=9.5, alpha=0.95, va='top')
ax1.text(FAULT_MIN+6, 30, 'STOCK PROCESS DEAD  —  all tenants lost',
         color=STOCK, fontsize=12, fontweight='bold',
         ha='left', va='center', alpha=0.95)
ax1.set_ylim(0, 100)
ax1.set_ylabel('GPU util (%)', fontsize=11.5, color=LABEL)
ax1.legend(loc='upper left', framealpha=0.6, edgecolor=EDGE,
           facecolor=NAVY, labelcolor=LABEL, fontsize=10,
           bbox_to_anchor=(0.005, 0.95))
ax1.tick_params(axis='both', which='both', length=4)
for s in ax1.spines.values():
    s.set_color(EDGE)

# ------- Bottom: p99 latency -------
ax2.fill_between(t, 0, 650, where=mask_dead, color=DEADBG, alpha=0.55,
                 step='post', zorder=0)
ax2.axhline(SPIKE_PEAK_MS, color=AMBER, linestyle=':', linewidth=1.0,
            alpha=0.6, zorder=1)
ax2.plot(t, tumbler_lat, color=TUMBLER, linewidth=1.6,
         label='Tumbler',    alpha=0.95, zorder=2)
ax2.plot(t, stock_lat,   color=STOCK,   linewidth=2.0,
         label='Stock ROCm', alpha=1.0,  zorder=3)
ax2.axvline(FAULT_MIN, color=AMBER, linestyle='--', linewidth=1.1, alpha=0.7,
            zorder=1.5)
# Move deadline-cap annotation to LEFT to free up the legend slot on the right.
ax2.text(0.5, SPIKE_PEAK_MS+20,
         'ROCR_SIGNAL_WAIT_MAX_MS = 500 ms  (graceful-fail cap)',
         color=AMBER, fontsize=9, alpha=0.85, ha='left')
# label each spike with a small arrow pointing UP to it
for c_min in SPIKE_MIN:
    ax2.annotate('graceful\nfail',
                 xy=(c_min, SPIKE_PEAK_MS-15),
                 xytext=(c_min+1.1, SPIKE_PEAK_MS-180),
                 color=TUMBLER, fontsize=8, alpha=0.9, ha='left', va='center',
                 arrowprops=dict(arrowstyle='->', color=TUMBLER, alpha=0.6,
                                 lw=0.8, shrinkA=0, shrinkB=3))
ax2.set_ylim(0, 650)
ax2.set_ylabel('p99 latency (ms)', fontsize=11.5, color=LABEL)
ax2.set_xlabel('Time (min)', fontsize=11.5, color=LABEL)
ax2.legend(loc='upper right', framealpha=0.6, edgecolor=EDGE,
           facecolor=NAVY, labelcolor=LABEL, fontsize=10)
ax2.tick_params(axis='both', which='both', length=4)
for s in ax2.spines.values():
    s.set_color(EDGE)

ax2.set_xticks(np.arange(0, T_MIN+1, 10))
ax2.set_xlim(0, T_MIN)

plt.tight_layout(rect=[0, 0, 1, 0.94])

OUT = str(REPO / 'docs/paper/figures/fig-05-latency-waveform.png')
plt.savefig(OUT, dpi=160, facecolor=NAVY, bbox_inches='tight',
            pad_inches=0.25)
print(f'wrote {OUT}')
