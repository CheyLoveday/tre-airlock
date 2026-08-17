# Feasibility — definition

A Recall-by-Genotype **feasibility** request asks ONE governed question: *can OFH identify a credible,
eligible, governable pool of carriers of the requested variant, in time?* It is a **go / no-go /
go-with-caveats service decision**, not a discovery analysis, an effect-size estimate, or a recruited
cohort.

## The five checks
**feasibility = identifiable + credible + eligible + governable + timely**

1. **identifiable** — the variant is correctly mapped and present in the genotype resources (array
   and/or imputed; OFH direct-assays rare clinical content, so the **array** list is the decisive check).
2. **credible** — carriers can be called with acceptable QC; array-direct = high confidence, imputed
   = conditional unless the imputation quality (dosage-r², DR2) is high.
3. **eligible** — a meaningful number likely remain after downstream ICD-10 phenotype filtering.
4. **governable** — the result can be expressed safely under SDC (minimum cell + secondary
   suppression) and cleared through the airlock.
5. **timely** — completable within the <5-business-day recontact-service window.

## It is NOT
Proving the variant causes disease; a publication-grade effect size; building the final recontact
cohort; or promising participants are contactable. Interpretive / translational tooling (enrichment
LRs, CardioBoost-style prioritisation) is a separate question and out of scope.

## The output
A decision-ready service note — short at the top, deep underneath — ending in an explicit
recommendation, plus the stakeholder handoffs (epidemiology, governance, client). See
`docs/service.md` for what the client does and does not receive.
