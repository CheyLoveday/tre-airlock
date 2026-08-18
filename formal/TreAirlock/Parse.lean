import Lean.Data.Json
import TreAirlock.Policy
import TreAirlock.Candidate

/-!
Strict fail-closed parser. Unknown fields, missing fields, wrong types, unknown schema
versions, out-of-vocabulary labels, malformed identifiers, and over-cap values are refusals.
No `filterMap`, no silent drops: this is the ONLY runtime constructor path into the closed
candidate value language, so nothing outside it can inhabit `ReleaseCandidate`.
-/

namespace TreAirlock

open Lean

def schemaVersion : String := "tre-airlock/v2"

/-- Object keys must be exactly `expected` (order irrelevant). -/
def expectKeys (obj : Std.TreeMap.Raw String Json compare) (expected : List String) :
    Except String Unit := do
  let keys := obj.keys
  let extra := keys.filter (fun k => !expected.contains k)
  if !extra.isEmpty then
    throw s!"unknown field: {extra[0]!}"
  let missing := expected.filter (fun k => !keys.contains k)
  if !missing.isEmpty then
    throw s!"missing field: {missing[0]!}"

def asObj (j : Json) : Except String (Std.TreeMap.Raw String Json compare) :=
  j.getObj?

def field (obj : Std.TreeMap.Raw String Json compare) (k : String) : Except String Json :=
  match obj.get? k with
  | some v => pure v
  | none => throw s!"missing field: {k}"

def parsePolicy (j : Json) : Except String Policy := do
  let obj ← asObj j
  expectKeys obj ["min_cell", "round_to"]
  let minCell ← (← field obj "min_cell").getNat?
  let roundTo ← (← field obj "round_to").getNat?
  pure { minCell := minCell, roundTo := roundTo }

/-- A bounded shown count: negatives are unrepresentable (`Nat`), over-cap refuses. -/
def parseCount (j : Json) : Except String Nat := do
  let n ← j.getNat?
  if n > maxCount then
    throw s!"count exceeds representation cap: {n}"
  pure n

def parseCell (j : Json) : Except String Cell := do
  let obj ← asObj j
  expectKeys obj ["label", "count"]
  let raw ← (← field obj "label").getStr?
  let count ← parseCount (← field obj "count")
  match CellLabel.fromString raw with
  | some label => pure { label := label, count := count }
  | none => throw s!"unknown cell label: {raw}"

def parseCells (j : Json) : Except String (List Cell) := do
  let arr ← j.getArr?
  if arr.size > maxCells then
    throw s!"too many cells: {arr.size}"
  arr.toList.mapM parseCell

def parseTotal (j : Json) : Except String ReleasedTotal := do
  let obj ← asObj j
  let tag ← (← field obj "tag").getStr?
  match tag with
  | "suppressed" =>
      expectKeys obj ["tag"]
      pure .suppressed
  | "shown" =>
      expectKeys obj ["tag", "n"]
      let n ← parseCount (← field obj "n")
      pure (.shown n)
  | other =>
      throw s!"unknown total tag: {other}"

def parseBreakdown (j : Json) : Except String Breakdown := do
  let obj ← asObj j
  let tag ← (← field obj "tag").getStr?
  match tag with
  | "suppressed" =>
      expectKeys obj ["tag"]
      pure .suppressed
  | "shown" =>
      expectKeys obj ["tag", "cells"]
      let cells ← parseCells (← field obj "cells")
      if hasDupLabels (cells.map (·.label)) then
        throw "duplicate cell label"
      pure (.shown cells)
  | other =>
      throw s!"unknown breakdown tag: {other}"

def parseCpra (s : String) : Except String Cpra := do
  match s.splitOn ":" with
  | [chrom, posStr, refA, altA] =>
      let pos ←
        match posStr.toNat? with
        | some n => pure n
        | none => throw s!"invalid CPRA position: {posStr}"
      if posStr ≠ toString pos then
        throw s!"non-canonical CPRA position: {posStr}"
      let v : Cpra := { chrom := chrom, pos := pos, ref := refA, alt := altA }
      if v.validB then
        pure v
      else
        throw s!"invalid CPRA component in: {s}"
  | _ => throw s!"invalid CPRA (expected chrom:pos:ref:alt): {s}"

def parseSubject (s : String) : Except String Subject := do
  let parts := s.splitOn "+"
  let vs ← parts.mapM parseCpra
  if h : ValidSubject vs = true then
    pure ⟨vs, h⟩
  else
    throw s!"invalid subject_id (1-{maxSubjectVariants} CPRAs joined by '+'): {s}"

def parseCandidate (j : Json) : Except String ReleaseCandidate := do
  let obj ← asObj j
  expectKeys obj ["subject_id", "total", "breakdown"]
  let subject ← parseSubject (← (← field obj "subject_id").getStr?)
  let total ← parseTotal (← field obj "total")
  let breakdown ← parseBreakdown (← field obj "breakdown")
  pure {
    subject := subject
    total := total
    breakdown := breakdown
  }

structure Request where
  policy : Policy
  candidate : ReleaseCandidate

/-- Parse a whole stdin document. Trailing/leading whitespace is allowed; junk is not. -/
def parseRequest (raw : String) : Except String Request := do
  let j ← Json.parse raw.trimAscii.toString
  let obj ← asObj j
  expectKeys obj ["schema", "policy", "candidate"]
  let schema ← (← field obj "schema").getStr?
  if schema ≠ schemaVersion then
    throw s!"unknown schema/version: {schema}"
  let policy ← parsePolicy (← field obj "policy")
  let candidate ← parseCandidate (← field obj "candidate")
  pure { policy := policy, candidate := candidate }

end TreAirlock
