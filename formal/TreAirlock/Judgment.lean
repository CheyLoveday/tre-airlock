import TreAirlock.Policy
import TreAirlock.Candidate

/-!
Decidable release judgment `Γ ⊢ c : ReleaseOK` and the proof-carrying export.

Predicates are boolean so the runtime `authorize` branch and `decide` share one
implementation. `AirlockExport` still demands a `ReleaseOK` witness.
-/

namespace TreAirlock

/-- `n` is a multiple of `r` and `r ≠ 0`. -/
def roundedB (n r : Nat) : Bool :=
  r != 0 && n % r == 0

/-- A shown cell may be a structural zero or at least `k`, and must be rounded. -/
def shownCountOKB (Γ : Policy) (n : Nat) : Bool :=
  (n == 0 || decide (n ≥ Γ.minCell)) && roundedB n Γ.roundTo

def totalOKB (Γ : Policy) : ReleasedTotal → Bool
  | .suppressed => true
  | .shown n => decide (n ≥ Γ.minCell) && roundedB n Γ.roundTo

def breakdownOKB (Γ : Policy) : Breakdown → Bool
  | .suppressed => true
  | .shown cells => cells.all (fun cell => shownCountOKB Γ cell.count)

def labelsUniqueB : Breakdown → Bool
  | .suppressed => true
  | .shown cells => !hasDupLabels (cells.map (·.label))

def Policy.validB (Γ : Policy) : Bool :=
  decide (Policy.Valid Γ)

/-- `Γ ⊢ c : ReleaseOK`. Secondary suppression is structural (`Breakdown.suppressed`). -/
def ReleaseOK (Γ : Policy) (c : ReleaseCandidate) : Prop :=
  Γ.validB = true ∧
  totalOKB Γ c.total = true ∧
  breakdownOKB Γ c.breakdown = true ∧
  labelsUniqueB c.breakdown = true

instance (Γ : Policy) (c : ReleaseCandidate) : Decidable (ReleaseOK Γ c) := by
  unfold ReleaseOK; infer_instance

/-- Proof-indexed successful export. Cannot be built when `ReleaseOK` is false. -/
structure AirlockExport where
  policy : Policy
  candidate : ReleaseCandidate
  proof : ReleaseOK policy candidate

theorem export_policy_validB (e : AirlockExport) : e.policy.validB = true :=
  e.proof.1

theorem export_policy_valid (e : AirlockExport) : Policy.Valid e.policy :=
  of_decide_eq_true (by
    have h : decide (Policy.Valid e.policy) = true := e.proof.1
    exact h)

theorem export_total_ok (e : AirlockExport) : totalOKB e.policy e.candidate.total = true :=
  e.proof.2.1

theorem export_breakdown_ok (e : AirlockExport) :
    breakdownOKB e.policy e.candidate.breakdown = true :=
  e.proof.2.2.1

theorem export_labels_unique (e : AirlockExport) : labelsUniqueB e.candidate.breakdown = true :=
  e.proof.2.2.2

theorem shownCountOKB_no_subminimum {Γ : Policy} {n : Nat}
    (h : shownCountOKB Γ n = true) : ¬ (0 < n ∧ n < Γ.minCell) := by
  intro hbad
  unfold shownCountOKB at h
  simp only [Bool.and_eq_true, Bool.or_eq_true, beq_iff_eq, decide_eq_true_eq] at h
  rcases h.1 with h0 | hge
  · exact Nat.lt_irrefl 0 (h0 ▸ hbad.1)
  · exact Nat.not_lt.mpr hge hbad.2

theorem breakdownOKB_no_subminimum {Γ : Policy} {cells : List Cell}
    (h : breakdownOKB Γ (.shown cells) = true) :
    ∀ cell ∈ cells, ¬ (0 < cell.count ∧ cell.count < Γ.minCell) := by
  intro cell hmem hbad
  have hall : cells.all (fun c => shownCountOKB Γ c.count) = true := by
    simpa [breakdownOKB] using h
  have hc : shownCountOKB Γ cell.count = true :=
    (List.all_eq_true.mp hall) cell hmem
  exact shownCountOKB_no_subminimum hc hbad

/-- No shown positive cell is below `k`. -/
theorem export_no_subminimum (e : AirlockExport) :
    match e.candidate.breakdown with
    | .suppressed => True
    | .shown cells => ∀ cell ∈ cells, ¬ (0 < cell.count ∧ cell.count < e.policy.minCell) := by
  cases hbd : e.candidate.breakdown with
  | suppressed => simp
  | shown cells =>
      have hok : breakdownOKB e.policy (.shown cells) = true := by
        simpa [hbd] using export_breakdown_ok e
      exact breakdownOKB_no_subminimum hok

/-! Concrete decided examples (reviewer-facing; `decide` fails if the calculus drifts). -/

example : Policy.Valid ⟨10, 5⟩ := by decide
example : ¬ Policy.Valid ⟨4, 5⟩ := by decide
example : ¬ Policy.Valid ⟨10, 0⟩ := by decide
example : ¬ Policy.Valid ⟨10, 6⟩ := by decide

private def demoSubject : Subject := ⟨[⟨"10", 119669928, "C", "G"⟩], by decide⟩

private def demoShown70 : ReleaseCandidate :=
  { subject := demoSubject, total := .shown 70, breakdown := .suppressed }

private def demoBypass : ReleaseCandidate :=
  { subject := demoSubject, total := .shown 70
    breakdown := .shown [⟨.arrayDirectHighConfidence, 70⟩, ⟨.imputedSupportedConditional, 2⟩] }

example : ReleaseOK ⟨10, 5⟩ demoShown70 := by decide
example : ¬ ReleaseOK ⟨10, 5⟩ demoBypass := by decide

/-! Negative construction (kept as a comment — uncomment to confirm it FAILS to compile):

`def badExport : AirlockExport :=`
`  { policy := ⟨10, 5⟩, candidate := demoBypass, proof := by decide }`
`  -- ERROR: failed to prove ReleaseOK (it is False)` -/

end TreAirlock
