/-!
Trusted release policy `Γ`. Authority sits here, not on the candidate: at runtime the bridge
loads Γ from the platform-owned deployment record (`platform/release_policy.json`) — the
analysis cannot choose the rule it is judged by. Protocol: `../AIRLOCK_RUNTIME.md`.
-/

namespace TreAirlock

/-- Smallest permitted minimum-cell floor. Matches the existing Python config bound. -/
def minAllowedCell : Nat := 5

/-- Independently supplied TRE policy. The analysis must not choose these values. -/
structure Policy where
  minCell : Nat
  roundTo : Nat
deriving Repr, DecidableEq, Inhabited

/-- `k ≥ 5`, `r > 0`, and `k` is a multiple of `r`. -/
def Policy.Valid (Γ : Policy) : Prop :=
  Γ.minCell ≥ minAllowedCell ∧
  Γ.roundTo > 0 ∧
  Γ.minCell % Γ.roundTo = 0

instance (Γ : Policy) : Decidable (Policy.Valid Γ) := by
  unfold Policy.Valid; infer_instance

end TreAirlock
