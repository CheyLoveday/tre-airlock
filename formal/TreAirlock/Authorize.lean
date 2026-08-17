import TreAirlock.Judgment

/-!
Runtime authorisation: the success branch constructs `AirlockExport` from a
decidable proof; refusal cannot.

The Python bridge (`ofh_feasibility.bridge.authorize`) invokes the CLI around
this function and writes the exact rendered bytes — and nothing else — to the
canonical egress-pending path.
-/

namespace TreAirlock

inductive Refusal where
  | invalidPolicy
  | releaseRejected
deriving Repr, DecidableEq

def Refusal.message : Refusal → String
  | .invalidPolicy => "invalid policy"
  | .releaseRejected => "release rejected"

/-- Construct a proof-indexed export, or refuse. Policy validity is diagnosed
separately from candidate failure so the CLI can return distinct reasons. -/
def authorize (Γ : Policy) (c : ReleaseCandidate) : Except Refusal AirlockExport :=
  if decide (Policy.Valid Γ) then
    if h : ReleaseOK Γ c then
      .ok { policy := Γ, candidate := c, proof := h }
    else
      .error .releaseRejected
  else
    .error .invalidPolicy

end TreAirlock
