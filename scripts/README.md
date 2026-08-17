# Scripts

This directory contains developer and reproducibility entrypoints, not reusable package logic.

- `generate_synthetic.py` builds deterministic synthetic inputs.
- `generate_ofh_files.py` converts those inputs into OFH-format pVCF/tabix stand-ins.
- `build_identifiability_artifact.py` builds the small public-list-derived runtime artifact from local raw CPRA lists.
- `verify_cpra.py` streams public CPRA lists for manual verification.
- `profile_pipeline.py` runs saved profiling sweeps.
- `run_stage.py` is the thin stage entrypoint used by external workflow wrappers.

Reusable logic should live under `src/ofh_feasibility/`. Scripts should stay thin and call the package.
