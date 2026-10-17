# Original-study identification: diagnosis of the 44 remaining misses

Tag `core_eval_20261015_doifix` (core extractor, Sonnet, prompt 8.10-core, with
the 2026-10-15 DOI-mismatch fix), scored by `harness.py originals` against human
labels on 458 papers. After the blind adjudication of 47 disputes, 44 papers
remained misses. Evidence: `remaining_misses.json` (inputs, extracted rows,
enrichment log), Crossref lookups of both sides' DOIs, and blind Opus verdicts on
the 14 no-replication papers in `noreps/adjudication/`.

## The extractor named an original, but not the labelled one (30)

| Cause | Papers | Extractor at fault? |
|---|---|---|
| **Fabricated DOI**: title, authors, year right; DOI not in Crossref, usually a near-miss of the real one (`…45520` → `…45529`, `…9325-5` → `…9325-y`, `…778810` → `…778take`) | 14 | yes, fixable |
| **Label names another record of the same work**: PsycEXTRA dataset (2), SSRN (2), NBER (2), JSTOR alias (3), ICPSR dataset, conference abstract vs the paper, a label DOI pointing at an unrelated journal (Caspi 2003) | 11 | no: scoring needs work-level equivalence |
| **No DOI found**: title lookup failed because the model reworded the title ("Anchor precision influences…" for "Precision of the anchor influences…"; Ellison's title without its "The Benefits of Facebook Friends" prefix) or the work is not in Crossref (German pedocs) | 3 | partly |
| **Different study** (confirmed by blind adjudication) | 2 | yes |

The fabricated DOIs survive because the 2026-10-15 fix only drops a DOI that
*resolves* to a different title; a DOI that resolves to nothing is kept.

## The extractor found no replication (14)

Blind Opus verdicts:

| Cause | Papers | Extractor at fault? |
|---|---|---|
| **Not a replication paper; label wrong**: a review, a reply by the original authors, within-paper discovery→replication designs (2), single-case "replication series" terminology, original research citing the labelled study as background | 6 | no |
| **Wrong document on disk**: supplementary material (2), an APA open-practices disclosure form, and an entirely different paper filed under the DOI (`10.1002/smj.2579` holds a 2025 *Accounting* article). The wrong-document check flagged none of them | 4 | no: input |
| **Missed**: a prostate-cancer replication of 8q24 GWAS hits whose XML rendition lacks the abstract (where the replication framing is) while `abstract.md` holds only the journal header | 1 | input |
| **Borderline**: a public-health programme carried to a new setting; a close extension that never calls itself a replication; an aggregate report of 176 student replications that does not name the individual originals | 3 | debatable |

## Net picture

Excluding the 4 wrong-document papers and the 6 non-replications from the
denominator, and counting the 11 same-work-different-record cases as correct:

- the right original **with a matching DOI**: 425 of 448 = **94.9%**;
- the right original **study** (also counting the 14 fabricated-DOI cases): 439 of 448 = **98.0%**.

Genuine extractor errors left: 2 wrong studies, 3 titles too reworded to look
up, 1 input-driven miss, 3 borderline eligibility calls.

## Fixes, in order of payoff

1. **Verify unresolvable DOIs** (14 papers): when a DOI resolves nowhere, look the
   study up by title and use the matching DOI. Same place as the 2026-10-15 fix
   (`extract.enrich_metadata`).
2. **Work-level equivalence in scoring** (11 papers): treat a PsycEXTRA/SSRN/NBER/
   ICPSR/JSTOR record and the published article as one work (same normalized title
   and year), in `originals.py` / `matching.canonical_doi`. Prefer the publisher DOI
   over a JSTOR `10.2307` alias in title lookup.
3. **Wrong-document detection** (4 papers): flag supplements, disclosure forms and
   a different paper's text (title/DOI mismatch with the folder) before extraction.
4. **Abstract fallback** (1 paper): when the rendition has no abstract and
   `abstract.md` is a husk, take the abstract from GROBID's `body.md` / the XML.
5. **Fuzzier title lookup** (3 papers): retry with the reference-list title from
   `references.json` when the model's title finds nothing.
