/-!
Closed aggregate release candidate — closed at the VALUE level, not just the field level.

Policy is *not* a field — `Γ` is supplied separately so the analysis cannot choose the rule it
is judged by. The released representation carries NO free-form string field: breakdown labels
are a finite inductive vocabulary and the subject is a parsed list of CPRA variant references
(study identity stays in INTERNAL evidence only). Counts and list lengths are capped at the
parser. Display tokens such as `<10` / `~70` are created by the renderer, not stored here.

Residual representational capacity — stated, not hidden: the numerical values themselves and
the CPRA components remain information-bearing; numerical steganography and upstream derivation
soundness are out of scope — see `applySDC_sound` (post-MVP).
-/

namespace TreAirlock

/-- Finite approved breakdown vocabulary. An unlisted label is unrepresentable, not just
rejected: `String` never reaches the released cell type. -/
inductive CellLabel where
  | arrayDirectHighConfidence
  | imputedSupportedConditional
deriving Repr, DecidableEq, BEq, Inhabited

def CellLabel.fromString : String → Option CellLabel
  | "array_direct_high_confidence" => some .arrayDirectHighConfidence
  | "imputed_supported_conditional" => some .imputedSupportedConditional
  | _ => none

def CellLabel.render : CellLabel → String
  | .arrayDirectHighConfidence => "array_direct_high_confidence"
  | .imputedSupportedConditional => "imputed_supported_conditional"

/-! Representation caps (parser-enforced): bounded numerals and list cardinalities. -/

def maxCount : Nat := 1000000000
def maxPos : Nat := 1000000000000
def maxCells : Nat := 16
def maxSubjectVariants : Nat := 16
def maxAlleleLen : Nat := 64

/-- The finite canonical chromosome vocabulary (no leading zeros by construction). -/
def chromNames : List String :=
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
   "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "X", "Y", "MT"]

def ValidChrom (s : String) : Bool :=
  chromNames.contains s

def ValidAllele (s : String) : Bool :=
  !s.isEmpty && s.length ≤ maxAlleleLen &&
  s.toList.all (fun c => c == 'A' || c == 'C' || c == 'G' || c == 'T')

/-- A parsed CPRA variant reference — chrom/pos/ref/alt, not free text. -/
structure Cpra where
  chrom : String
  pos : Nat
  ref : String
  alt : String
deriving Repr, DecidableEq, Inhabited

def Cpra.validB (v : Cpra) : Bool :=
  ValidChrom v.chrom && decide (0 < v.pos) && decide (v.pos ≤ maxPos) &&
  ValidAllele v.ref && ValidAllele v.alt

def Cpra.render (v : Cpra) : String :=
  s!"{v.chrom}:{v.pos}:{v.ref}:{v.alt}"

/-- One-or-more parsed variant references (a batch subject joins several), capped. -/
def ValidSubject (vs : List Cpra) : Bool :=
  !vs.isEmpty && decide (vs.length ≤ maxSubjectVariants) && vs.all Cpra.validB

/-- Refined subject reference: only validated CPRA lists inhabit it. -/
abbrev Subject := {vs : List Cpra // ValidSubject vs = true}

instance : Repr Subject := ⟨fun s n => reprPrec s.val n⟩

def Subject.render (s : Subject) : String :=
  String.intercalate "+" (s.val.map Cpra.render)

structure Cell where
  label : CellLabel
  count : Nat
deriving Repr, DecidableEq, Inhabited

/-- Released total: withheld, or a shown natural (already rounded by the producer). -/
inductive ReleasedTotal where
  | suppressed
  | shown (n : Nat)
deriving Repr, DecidableEq, Inhabited

/-- Subgroup breakdown: withheld entirely, or an explicit shown cell list. -/
inductive Breakdown where
  | suppressed
  | shown (cells : List Cell)
deriving Repr, DecidableEq, Inhabited

/-- Aggregate-only proposal over the closed value language. The candidate carries NO free-form
string field: study identity lives in the INTERNAL evidence (audit events, manifests), never in
the released representation. -/
structure ReleaseCandidate where
  subject : Subject
  total : ReleasedTotal
  breakdown : Breakdown
deriving Repr

/-- Linear duplicate-label check. Used by the parser (refuse) and by `ReleaseOK`. -/
def hasDupLabels : List CellLabel → Bool
  | [] => false
  | x :: xs => xs.contains x || hasDupLabels xs

end TreAirlock
