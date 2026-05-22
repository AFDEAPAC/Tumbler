# TUMBLER — ROCm Runtime & Driver Survival Stack

![cover](docs/cover.png)

> **TUMBLER** — a **T**hree-tier **U**nified **M**ulti-tenant **B**ounded-wait
> **L**ayered **E**scape-hatch **R**untime — is a layered survival firewall for
> AMD ROCm across the CLR (HIP host runtime), ROCr (HSA runtime), and amdgpu
> (kernel driver) layers. Bounded-wait knobs at every layer let production AI
> serving stacks degrade gracefully — drop the affected request — instead of
> aborting the whole process on a transient hardware or driver fault.
>
> The name fits the function: a *tumbler* is a self-righting toy — push it
> over and it pops back upright. Tumbler does the same for the ROCm runtime
> under transient HW and driver faults.

## Why Tumbler

Imagine you are driving on the highway and the in-car infotainment
touchscreen — rendered on AMD `amdgpu` — hits a transient GPU fault. You
would rather drop that one frame and keep the dashboard alive than freeze
the entire display. The same logic applies to multi-tenant AI inference
fleets: drop the bad request, keep serving the other tenants.

Stock ROCm was designed for HPC single-tenant correctness, so its default
on a VM fault / SDMA wedge / signal stall is `std::abort()`. Tumbler adds
opt-in bounded-wait knobs at every layer that turn those abort sites into
*graceful-failure* sites without changing default behaviour.

## Upstream PRs

| Layer | Repo | PR | Knob(s) |
|---|---|---|---|
| CLR (HIP host runtime) | `ROCm/rocm-systems` | [#6328](https://github.com/ROCm/rocm-systems/pull/6328) | `HIP_MAX_SIGNAL_WAIT` |
| ROCr (HSA runtime)     | `ROCm/rocm-systems` | [#6329](https://github.com/ROCm/rocm-systems/pull/6329) | `ROCR_SERVICE_SURVIVAL`, `ROCR_SIGNAL_WAIT_MAX_MS`, `ROCR_SDMA_WRITE_ADDR_FAIL_MS` |
| amdkcl (DKMS shim)     | `ROCm/amdgpu`       | [#214](https://github.com/ROCm/amdgpu/pull/214)         | `suballoc_timeout_ms` |
| amdgpu (GTT path)      | `ROCm/amdgpu`       | [#215](https://github.com/ROCm/amdgpu/pull/215)         | `gtt_lock_timeout_ms` |
| amdgpu (KFD pin reaper)| `ROCm/amdgpu`       | [#216](https://github.com/ROCm/amdgpu/pull/216)         | `kfd_free_wait_ms`, `kfd_unpin_drain_ms`, `kfd_free_on_pinned`, `pin_orphan_timeout_ms`, `pin_reaper_interval_ms` |

## Repository layout

```
Tumbler/
├── README.md
├── .gitignore
├── .gitmodules
├── docs/
│   ├── cover.png
│   ├── paper/                # GTAC 2026 submission
│   │   ├── tumbler-paper-gtac2026.docx
│   │   ├── tumbler-paper-gtac2026.pdf
│   │   ├── figures/                  # source SVG/PNG figures
│   │   └── figures-rendered/         # rendered page-{1..5}.png (review)
│   ├── slides/
│   │   ├── tumbler-slides-gtac2026.pptx
│   │   ├── tumbler-slides-gtac2026.pdf
│   │   └── figures-rendered/         # rendered slide-{01..13}.png (review)
│   └── templates/            # GTAC 2025 templates (traceability)
├── scripts/                  # reproducible artifact builders
│   ├── build_paper.py        # docx -> docs/paper/tumbler-paper-gtac2026.docx
│   ├── build_slides.py       # pptx -> docs/slides/tumbler-slides-gtac2026.pptx
│   ├── make_waveform.py      # regenerates fig-05-latency-waveform.png
│   └── verify_paper.py       # sanity-checks the produced docx
├── rocm-systems/             # submodule: chun-wan/rocm-systems @ tumbler-integrated
│                             # (upstream develop + CLR #6328 + ROCr #6329)
└── amdgpu/                   # submodule: chun-wan/amdgpu @ tumbler-integrated
                              # (upstream master + amdgpu #214 + #215 + #216)
```

## Build

The submodules pin a specific integration tip per repo so the stack can be
rebuilt deterministically:

```bash
git clone --recurse-submodules https://github.com/AFDEAPAC/Tumbler.git
cd Tumbler

# CLR + ROCr (build via TheRock or the rocm-systems CMake top-level)
cd rocm-systems
# follow upstream build instructions

# amdgpu (build via DKMS; see ROCm/amdgpu/README)
cd ../amdgpu
make -C drivers/gpu/drm/amd/amdgpu
```

## Reproduce the paper / slides

The committed `.docx` / `.pptx` / `.pdf` artifacts can be regenerated from the
templates and source figures via the scripts in `scripts/`. They take their
input from `docs/templates/` + `docs/paper/figures/` and write into
`docs/paper/` and `docs/slides/`:

```bash
pip install python-docx python-pptx matplotlib   # build-time deps
python3 scripts/build_paper.py
python3 scripts/build_slides.py

# Optional: re-render the PDF + page PNGs used in figures-rendered/
sudo apt-get install -y libreoffice poppler-utils
libreoffice --headless --convert-to pdf --outdir docs/paper  \
            docs/paper/tumbler-paper-gtac2026.docx
libreoffice --headless --convert-to pdf --outdir docs/slides \
            docs/slides/tumbler-slides-gtac2026.pptx
pdftoppm -r 110 docs/paper/tumbler-paper-gtac2026.pdf  \
                docs/paper/figures-rendered/page  -png
pdftoppm -r 110 docs/slides/tumbler-slides-gtac2026.pdf \
                docs/slides/figures-rendered/slide -png
```

## Gold settings (rc4 deployed reference)

Recommended starting values for a multi-tenant MI300X serving box. All knobs
default to off / unbounded — set only the ones you need:

```
# CLR
HIP_MAX_SIGNAL_WAIT=4

# ROCr
ROCR_SERVICE_SURVIVAL=1
ROCR_SIGNAL_WAIT_MAX_MS=2000
ROCR_SDMA_WRITE_ADDR_FAIL_MS=500

# amdgpu modprobe
suballoc_timeout_ms=4000
gtt_lock_timeout_ms=4000
kfd_free_wait_ms=4000
kfd_unpin_drain_ms=4000
kfd_free_on_pinned=1
pin_orphan_timeout_ms=30000
pin_reaper_interval_ms=5000
```

## Authors

- **Chun-Hung Wang** &lt;Chun-Hung.Wang@amd.com&gt; — *first / corresponding*
- **Clement Lin** &lt;Clement.Lin@amd.com&gt;
- **Jeremy Liao** &lt;Jeremy.Liao@amd.com&gt;

## License

Each submodule retains its upstream license (MIT-like for CLR/ROCr, GPL-2.0
for the kernel driver). This meta-repo's documentation is released under MIT.
