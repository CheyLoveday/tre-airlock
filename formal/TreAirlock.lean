import TreAirlock.Policy
import TreAirlock.Candidate
import TreAirlock.Judgment
import TreAirlock.Authorize
import TreAirlock.Parse
import TreAirlock.Render

/-!
Runtime Lean airlock core — the release authority invoked by the Python bridge.

Public surface for the formal runtime: policy, candidate, judgment, authorize,
strict parser, canonical renderer. The CLI lives in `TreAirlockMain`.

This library is **not** a product stopping point. The MVP exists only when the
Python bridge writes these exact rendered bytes to the pre-egress path.
-/
