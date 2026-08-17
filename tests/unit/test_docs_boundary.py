"""Enforcement: the shareable docs surface must not link into internal working material.

`docs/` is the shareable-only documentation tree; internal working notes live outside it. Two
guards:

- `test_shareable_docs_do_not_link_into_internal`: no canonical shareable doc may link into an
  internal subtree.
- `test_docs_tree_is_shareable_only`: internal subtrees must not exist under `docs/`.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
INTERNAL_SUBTREES = ("plans", "review", "handover")
_LINK = re.compile(r"\]\(([^)]+)\)")
# A markdown link target that points into an internal tree.
_INTERNAL_TARGET = re.compile(r"(^|/)(\.dev|plans|review|handover)/")


def _shareable_docs() -> list[Path]:
    """Top-level docs/*.md plus reference/ and templates/ — the canonical shareable surface."""
    files = list(DOCS.glob("*.md"))
    for sub in ("reference", "templates"):
        files += list((DOCS / sub).glob("*.md"))
    return files


def test_shareable_docs_do_not_link_into_internal():
    offenders = []
    for doc in _shareable_docs():
        for target in _LINK.findall(doc.read_text()):
            link = target.split("#")[0].strip()
            if link.startswith("http") or not link:
                continue
            if _INTERNAL_TARGET.search(link):
                offenders.append(f"{doc.relative_to(REPO)} -> {link}")
    assert not offenders, "shareable docs link into internal material:\n" + "\n".join(offenders)


def test_docs_tree_is_shareable_only():
    present = [name for name in INTERNAL_SUBTREES if (DOCS / name).exists()]
    assert not present, f"internal subtrees must not live under docs/: {present}"
