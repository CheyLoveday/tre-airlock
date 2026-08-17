# Example Configs

These are complete runnable `Config` YAML files, not templates or fragments. They load through the
same strict Pydantic model as `config.yaml`; unknown keys fail fast, the consent gate cannot be
disabled, and SDC rounding must divide the configured minimum cell.

- `single_variant_simplified.yaml` — BAG3 single-variant demo over the simplified synthetic files.
- `ofh_tre_chek2_i157t.yaml` — CHEK2 I157T over generated OFH-format pVCF/tabix stand-ins.
- `gene_panel_simplified.yaml` — CHEK2 gene or breast-cancer panel requests over the catalogue-backed
  batch path.

Use an example config directly:

```bash
uv run python scripts/generate_synthetic.py
uv run ofh-feasibility run --config configs/examples/single_variant_simplified.yaml
uv run python run_demo.py --config configs/examples/single_variant_simplified.yaml
uv run snakemake --cores 1 -s workflow/Snakefile \
  --config config_path=configs/examples/single_variant_simplified.yaml
```

The OFH-format example needs the local pVCF/tabix generator and the optional workflow dependency:

```bash
uv run --extra ofhgen python scripts/generate_ofh_files.py --in data/synthetic --out data/synthetic/ofh_tre
uv run --extra workflow --extra ofhgen snakemake --cores 1 -s workflow/Snakefile \
  --config config_path=configs/examples/ofh_tre_chek2_i157t.yaml
```

CLI flags such as `--results-dir`, `--data-dir`, `--request`, `--source-format`, and
`--variant-catalog` still override the loaded config for run matrices.
