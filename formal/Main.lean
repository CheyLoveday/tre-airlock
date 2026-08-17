import Release

/-! Release-gate checker executable (the conformance ORACLE).

Reads one release candidate per stdin line in a simple pipe-delimited format and prints `true` /
`false` (the `ReleaseOK` decision) per line. The Python conformance test runs both this checker and
`airlock.release_ok` over the same battery and asserts they agree.

Line format:  minCell|roundTo|clientTotal|breakdownSuppressed|count1,count2,...
e.g.           10|5|~40|false|25,15      (the cell labels are irrelevant to the predicates). -/

open Feasibility

def parseLine (line : String) : Option ReleaseCandidate :=
  match line.splitOn "|" with
  | [mc, rt, total, supp, cells] => do
      let minCell ← mc.trim.toNat?
      let roundTo ← rt.trim.toNat?
      let cs := cells.trim
      let counts := if cs.isEmpty then [] else (cs.splitOn ",").filterMap (fun s => s.trim.toNat?)
      pure {
        clientTotal := total.trim,
        breakdownSuppressed := supp.trim == "true",
        reportedCells := counts.map (fun n => ⟨"x", n⟩),
        minCell := minCell,
        roundTo := roundTo
      }
  | _ => none

def main : IO Unit := do
  let input ← (← IO.getStdin).readToEnd
  for line in input.splitOn "\n" do
    let l := line.trim
    if l.isEmpty then continue
    match parseLine l with
    | some c => IO.println (if ReleaseOK c then "true" else "false")
    | none   => IO.println "parse_error"
