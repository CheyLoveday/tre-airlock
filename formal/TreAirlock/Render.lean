import TreAirlock.Judgment

/-!
Canonical renderer. Field order is fixed and documented; this is the only
client-facing byte sequence the Python bridge may write.
-/

namespace TreAirlock

/-- JSON-escape a string (quotes, backslash, controls). -/
def escapeString (s : String) : String :=
  s.toList.foldl (init := "") fun acc c =>
    if c == '"' then acc ++ "\\\""
    else if c == '\\' then acc ++ "\\\\"
    else if c == '\n' then acc ++ "\\n"
    else if c == '\r' then acc ++ "\\r"
    else if c == '\t' then acc ++ "\\t"
    else if c.val < 0x20 then
      let n := c.toNat
      let hex := Nat.toDigits 16 n
      let pad := String.ofList (List.replicate (4 - hex.length) '0') ++ String.ofList hex
      acc ++ "\\u" ++ pad
    else
      acc.push c

def quoted (s : String) : String :=
  "\"" ++ escapeString s ++ "\""

/-- Display token created from `Γ` + the structural total. -/
def renderTotal (Γ : Policy) : ReleasedTotal → String
  | .suppressed => "<" ++ toString Γ.minCell
  | .shown n => "~" ++ toString n

def renderCell (c : Cell) : String :=
  "{\"label\":" ++ quoted c.label.render ++ ",\"count\":" ++ toString c.count ++ "}"

def renderBreakdown : Breakdown → String
  | .suppressed => "null"
  | .shown cells =>
      "[" ++ String.intercalate "," (cells.map renderCell) ++ "]"

/-- Compact JSON, fixed key order:
`schema`, `status`, `policy`, `study_id`, `subject_id`, `total`, `breakdown`.
A single trailing newline is added by the CLI, not here. -/
def render (e : AirlockExport) : String :=
  let Γ := e.policy
  let c := e.candidate
  "{" ++
    "\"schema\":\"tre-airlock/v1\"," ++
    "\"status\":\"released\"," ++
    "\"policy\":{\"min_cell\":" ++ toString Γ.minCell ++
      ",\"round_to\":" ++ toString Γ.roundTo ++ "}," ++
    "\"study_id\":" ++ quoted c.studyId.val ++ "," ++
    "\"subject_id\":" ++ quoted c.subject.render ++ "," ++
    "\"total\":" ++ quoted (renderTotal Γ c.total) ++ "," ++
    "\"breakdown\":" ++ renderBreakdown c.breakdown ++
  "}"

end TreAirlock
