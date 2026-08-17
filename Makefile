.PHONY: install gen test test-unit test-int test-e2e lint format demo fresh-demo examples fresh-examples profile notebook notebook-render airlock

# Build the runtime Lean airlock (the release authority) + precursor checker.
# The pipeline's release path REQUIRES this binary — there is no Python fallback.
airlock:
	cd formal && lake build

install:
	uv sync --extra dev

gen:
	uv run python scripts/generate_synthetic.py

test:
	uv run pytest

test-unit:
	uv run pytest -m unit

test-int:
	uv run pytest -m integration

test-e2e:
	uv run pytest -m e2e

lint:
	uv run ruff check

format:
	uv run ruff format

demo:
	@test -f data/synthetic/variant_request.csv || \
		(echo "Missing synthetic demo inputs. Run: make gen"; exit 1)
	@test -x formal/.lake/build/bin/airlock || \
		(echo "Missing Lean adjudicator (release authority). Run: make airlock"; exit 1)
	uv run python run_demo.py

fresh-demo: gen demo

# Run all three example configs end-to-end (the demo MVP use cases).
examples:
	@test -f data/synthetic/variant_request.csv || \
		(echo "Missing synthetic demo inputs. Run: make gen"; exit 1)
	uv run ofh-feasibility run --config configs/examples/single_variant_simplified.yaml
	uv run ofh-feasibility gene --symbol CHEK2 --config configs/examples/gene_panel_simplified.yaml
	uv run ofh-feasibility disease --panel breast_cancer --config configs/examples/gene_panel_simplified.yaml --results-dir results/config_breast_cancer_panel
	uv run --extra ofhgen python scripts/generate_ofh_files.py --in data/synthetic --out data/synthetic/ofh_tre
	uv run --extra ofhgen ofh-feasibility run --config configs/examples/ofh_tre_chek2_i157t.yaml

fresh-examples: gen examples

profile:
	uv run python -m cProfile -o prof.out run_demo.py

notebook:
	uv run --extra notebook jupyter lab notebooks/ofh_feasibility_walkthrough.ipynb

notebook-render:
	uv run --extra notebook jupyter nbconvert --to notebook --execute --inplace notebooks/ofh_feasibility_walkthrough.ipynb
