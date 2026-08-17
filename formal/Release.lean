/-! # Formal release-boundary gate (Wave 5)

The terminal `AirlockExport` is UNCONSTRUCTABLE without a machine-checked proof that every
disclosure-control release requirement holds — so a non-compliant release fails to compile.
`ReleaseOK` mirrors `airlock.release_ok` in the Python package; a conformance test binds the two.

Lean runs at design / CI time only; it is never a TRE runtime dependency and never on the package
allowlist. The gate certifies the released ARTIFACT is policy-safe and well-formed, not that the
upstream count is scientifically correct. -/

namespace Feasibility

/-- A released subgroup cell: a label and a rounded count. -/
structure Cell where
  label : String
  count : Nat
deriving Repr, DecidableEq

/-- The aggregate-only release object. Mirrors `models.ReleaseCandidate` (no participant fields). -/
structure ReleaseCandidate where
  studyId : String := ""
  cpra : String := ""
  clientTotal : String
  breakdownSuppressed : Bool
  reportedCells : List Cell
  minCell : Nat
  roundTo : Nat
deriving Repr

/-- A released total token is safe: EXACTLY the `<minCell` suppression token, or `~N` with N a
    multiple of roundTo and N ≥ minCell. (A bare `<` prefix is not enough — `<banana`/`<5` fail.) -/
def totalSafe (token : String) (minCell : Nat) (roundTo : Nat) : Bool :=
  if token.startsWith "<" then token == "<" ++ toString minCell
  else if token.startsWith "~" then
    match (token.drop 1).toNat? with
    | some n => roundTo != 0 && n % roundTo == 0 && decide (minCell ≤ n)
    | none => false
  else false

/-- The release requirements (03_GOVERNANCE_SDC) as a decidable proposition:
    minimum cell · secondary suppression (a suppressed breakdown releases no subgroup) · rounding ·
    a safe total. (Least privilege is structural: this object has no participant-level field.) -/
def ReleaseOK (c : ReleaseCandidate) : Prop :=
  (∀ cell ∈ c.reportedCells, cell.count = 0 ∨ cell.count ≥ c.minCell) ∧
  (c.breakdownSuppressed = true → c.reportedCells = []) ∧
  (∀ cell ∈ c.reportedCells, cell.count % c.roundTo = 0) ∧
  (totalSafe c.clientTotal c.minCell c.roundTo = true)

instance (c : ReleaseCandidate) : Decidable (ReleaseOK c) := by
  unfold ReleaseOK; infer_instance

/-- The terminal release artifact: its constructor DEMANDS a `ReleaseOK` witness, so an
    `AirlockExport` cannot exist for a non-compliant candidate. -/
structure AirlockExport where
  candidate : ReleaseCandidate
  proof : ReleaseOK candidate

/-- Smart constructor — an export exists only with a proof. -/
def mkAirlockExport (c : ReleaseCandidate) (h : ReleaseOK c) : AirlockExport := ⟨c, h⟩

/-! Machine-checked invariants over ANY `AirlockExport` (projections of the witness). Deleting or
weakening a conjunct of `ReleaseOK` breaks these proofs — `lake build` goes red. -/

theorem export_min_cell (e : AirlockExport) :
    ∀ cell ∈ e.candidate.reportedCells, cell.count = 0 ∨ cell.count ≥ e.candidate.minCell :=
  e.proof.1

theorem export_secondary_suppression (e : AirlockExport) :
    e.candidate.breakdownSuppressed = true → e.candidate.reportedCells = [] :=
  e.proof.2.1

theorem export_rounding (e : AirlockExport) :
    ∀ cell ∈ e.candidate.reportedCells, cell.count % e.candidate.roundTo = 0 :=
  e.proof.2.2.1

theorem export_total_safe (e : AirlockExport) :
    totalSafe e.candidate.clientTotal e.candidate.minCell e.candidate.roundTo = true :=
  e.proof.2.2.2

/-- Corollary: no released subgroup cell is a positive value below the minimum (the disclosure
    invariant 03_GOVERNANCE_SDC asks for, machine-checked). -/
theorem export_no_subminimum (e : AirlockExport) :
    ∀ cell ∈ e.candidate.reportedCells, ¬ (0 < cell.count ∧ cell.count < e.candidate.minCell) := by
  intro cell hmem hbad
  rcases export_min_cell e cell hmem with h0 | hge
  · exact (Nat.lt_irrefl 0) (h0 ▸ hbad.1)
  · exact (Nat.not_lt.mpr hge) hbad.2

/-! Negative test of the gate (kept as a comment — uncomment to confirm it FAILS to compile):
a candidate with a sub-minimum released cell has no `ReleaseOK` proof, so the export cannot be built.

`def badExport : AirlockExport :=`
`  mkAirlockExport`
`    { clientTotal := "~40", breakdownSuppressed := false,`
`      reportedCells := [⟨"a", 5⟩], minCell := 10, roundTo := 5 }`
`    (by decide)   -- ERROR: failed to prove ReleaseOK (it is False)` -/

end Feasibility
