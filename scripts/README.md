# scripts/ — Tumbler artifact builders

Reproducible builders for the GTAC 2026 paper and slides. The committed
`.docx`/`.pptx`/`.pdf` artifacts under `docs/paper/` and `docs/slides/` can be
regenerated from the templates in `docs/templates/` and the source figures
under `docs/paper/figures/` using the scripts here.

## Layout

| Script             | Purpose                                                            |
|--------------------|---------------------------------------------------------------------|
| `build_paper.py`   | Renders `docs/paper/tumbler-paper-gtac2026.docx` from the GTAC 2025 submission template. |
| `build_slides.py`  | Renders `docs/slides/tumbler-slides-gtac2026.pptx` from the AMD corporate `HIPER.pptx` template. |
| `make_waveform.py` | Generates `docs/paper/figures/fig-05-latency-waveform.png` (utilisation + p99 latency under fault). |
| `verify_paper.py`  | Lightweight sanity check on the produced `.docx` (page count, basic style assertions). |

All paths are computed from `__file__`, so the scripts work from any
checkout location — no `/tmp/...` hardcoding.

## Dependencies

```bash
pip install python-docx python-pptx matplotlib
# Optional, only for PDF + page PNG re-rendering:
sudo apt-get install -y libreoffice poppler-utils
```

## Build

```bash
# Regenerate the source figure (only if waveform parameters change)
python3 scripts/make_waveform.py

# Rebuild the artifacts
python3 scripts/build_paper.py
python3 scripts/build_slides.py

# Optionally re-render PDF + page PNGs used in docs/*/figures-rendered/
libreoffice --headless --convert-to pdf --outdir docs/paper  \
            docs/paper/tumbler-paper-gtac2026.docx
libreoffice --headless --convert-to pdf --outdir docs/slides \
            docs/slides/tumbler-slides-gtac2026.pptx
pdftoppm -r 110 docs/paper/tumbler-paper-gtac2026.pdf  \
                docs/paper/figures-rendered/page  -png
pdftoppm -r 110 docs/slides/tumbler-slides-gtac2026.pdf \
                docs/slides/figures-rendered/slide -png
```

## Notes

- The build scripts also patch `docProps/core.xml` and `docProps/app.xml`
  inside the docx/pptx so the file properties reflect the Tumbler authors
  rather than the template's original metadata (subject = "TSV DRAM",
  creator = "Mike O'Connor", etc.). If you add new metadata fields, edit
  the `--- core properties (Tumbler) ---` block at the bottom of each
  builder.
- The `_scrub_app_xml` helper rewrites the file via tempfile + shutil.move,
  then explicitly `chmod 0o644` so subsequent rebuilds don't leave the
  artifact with 0o600.
