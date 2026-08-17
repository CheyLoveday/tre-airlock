import TreAirlock

/-!
`airlock` executable.

stdin: one strict JSON request (`schema` + `policy` + `candidate`).
stdout on success: canonical release JSON + one newline. Nothing else.
stderr + non-zero exit on any refusal. Empty stdout on refusal.

Exit codes: 0 released · 1 candidate rejected · 2 malformed · 3 invalid policy.

This executable is the runtime release authority: the Python bridge
(`ofh_feasibility.bridge`) writes its exact stdout bytes — and nothing else —
to the canonical egress-pending path.
-/

open TreAirlock

/-- 0 = released, 1 = rejected, 2 = malformed, 3 = invalid policy. -/
def main : IO UInt32 := do
  let raw ← (← IO.getStdin).readToEnd
  match parseRequest raw with
  | .error msg =>
      IO.eprintln s!"malformed input: {msg}"
      return 2
  | .ok req =>
      match authorize req.policy req.candidate with
      | .error .invalidPolicy =>
          IO.eprintln (Refusal.message .invalidPolicy)
          return 3
      | .error .releaseRejected =>
          IO.eprintln (Refusal.message .releaseRejected)
          return 1
      | .ok exp =>
          IO.print (render exp)
          IO.print "\n"
          return 0
