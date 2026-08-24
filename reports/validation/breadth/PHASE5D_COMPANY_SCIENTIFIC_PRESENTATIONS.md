# Phase 5d — Company Scientific-Presentation Source

Per `reports/validation/BREADTH_PLAN.md` Phase 5 Part 7. Fourth increment
after Phase 5a (conference-text candidates), Phase 5b (modality taxonomy),
and Phase 5c (target x indication table) -- this one, unlike those three,
adds a genuinely NEW acquisition source, following the reviewer's own
guidance after Phase 5c's APPROVE to prioritize this over Phase 6's delta
system.

## 1. Reuse/verification search done first (Part 7's own discipline)

Before writing any code, every one of the 8 companies in
`configs/company_registry.yaml` was checked LIVE for a genuine, scrapable
scientific-presentations page -- not assumed from any company's existing
`press_release_url`/`investor_relations_url` entry, since an IR newsroom
covers corporate announcements, not necessarily actual congress
presentations/posters.

| Company | Result |
|---|---|
| **Sutro Biopharma** | Real page found: `sutrobio.com/news/presentations/`, WordPress/Divi blog category, real AACR/ASCO/World ADC Summit/R&D-Day content. **Registered.** |
| **ADC Therapeutics** | Real page found: `adctmedical.com/congresses/` -- a SEPARATE medical-affairs microsite (not `adctherapeutics.com`/`ir.adctherapeutics.com`), 115 direct-PDF entries, no pagination. **Registered.** |
| **Zymeworks** | Real page found: `zymeworks.com/publications/`, ~96 entries across 8 pages -- **deferred**, see Section 4. |
| **AbbVie** | Main domain (`abbvie.com`) is behind the same Cloudflare JS challenge already documented for its pipeline page (confirmed live again 2026-08-24); no separate public microsite found. **Not registered.** |
| **Pfizer** | No distinct presentations archive; `pfizer.com/news/press-kits/oncology` has only stale 2018-2020 blog-post assets, not real congress content. **Not registered.** |
| **Seagen / ImmunoGen / Mersana** | Acquired/absorbed; domains still redirect to their respective acquirers (Pfizer / AbbVie / Day One Biopharmaceuticals), confirmed live again 2026-08-24, no standalone page of their own. **Not registered.** |

## 2. Registry extension

`adc_acquisition/company_registry.py`'s `Company` dataclass gains
`presentations_url`/`presentations_template` (tolerant addition, same
"unknown YAML keys are dropped" mechanism every prior field addition
used). **Critically, the domain-trust anchor is `presentations_url`'s OWN
host, never `official_domain`** -- ADC Therapeutics' presentations
microsite (`adctmedical.com`) is a genuinely different domain from its
registered `official_domain` (`adctherapeutics.com`), confirmed to be ADC
Therapeutics' own official medical-affairs site (not a third party) via
its own page branding. Checking against `official_domain` would have
incorrectly excluded every item this source finds.

## 3. Two genuinely different pagination shapes (new territory vs. Job 12)

Job 12 (press releases)'s three templates all share one query-string
`?param=N` pagination shape. This phase's two templates do not:

- **`single_page`** (ADC Therapeutics) -- fetched EXACTLY ONCE, no cursor
  at all. All ~115 entries load on the one page (confirmed live: no
  pagination controls exist).
- **`wordpress_path`** (Sutro) -- standard WordPress `/page/N/` PATH-based
  pagination, not a query-string parameter. Confirmed live that pages
  past the real end parse to zero items (a static, always-present
  "page"-type post, `post-3163`, appears on every paginated URL but does
  NOT match the real-entry pattern), so the same "stop when this page
  contributes zero NOT-already-known items" rule Job 12 established
  applies here too, and is a genuine empty-page stop for this template.

`jobs/company_scientific_presentations/job.py` mirrors Job 12's fully-
hardened materialization design (checkpoint-based skip/version-bump,
query_id/query_text provenance consistency, per-company discovery-failure
isolation) UNMODIFIED -- proactively applied from the start, per this
project's established "don't re-derive a hardened pattern and risk the
same review rounds" precedent.

## 4. Zymeworks: found, but deliberately deferred

`www.zymeworks.com/publications/` is real and has genuine AACR/ESMO/PEGS
poster PDFs (confirmed live, 8 pages, ~96 entries). Not registered this
phase because its markup is Elementor page-builder-generated with
per-instance auto-generated element IDs (e.g. `elementor-element-500f815`)
that differ per widget instance -- a genuinely higher parsing-fragility
risk than either template registered this phase (both hand-authored,
semantically-classed markup). Zymeworks' current pipeline is also more
multispecific-antibody-focused than ADC-focused. A candidate for a future
round, not attempted here rather than rushed with a fragile regex.

## 5. Real numbers (live run against the real internet, not fixtures)

```
$ python -m adc_acquisition company_scientific_presentations --dry-run
records_discovered=304 (115 ADC Therapeutics + 189 Sutro Biopharma)

$ python -m adc_acquisition company_scientific_presentations --limit 6
records_downloaded=6, records_failed=0
  (ADC Therapeutics: real PDFs -- EHA 2022, ICML 2019, ASCO 2016, ASH 2022,
   AACR 2024, ASH 2025 -- congress+year preserved, no fabricated date)

$ python -m adc_acquisition company_scientific_presentations --company sutro_biopharma --limit 5
records_downloaded=5, records_failed=0
  (Sutro: real HTML detail pages, real dates from 2014-12-16 through 2025-05-01)
```

Sutro's listing goes back to at least 2014 (189 total items discovered)
-- confirming this is a genuinely deep historical source, not just recent
announcements.

Full materialization (no `--limit`), run against the real internet for
every discovered item, completed with zero failures:

```
$ python -m adc_acquisition company_scientific_presentations
records_discovered=293, records_downloaded=293, records_failed=0
  (293 = 304 total minus the 11 already materialized by the --limit smoke
  tests above, correctly fast-skipped as already-successful)

DATA/manifests/company_scientific_presentations.parquet: 304 rows total
  (189 Sutro Biopharma + 115 ADC Therapeutics), 304 unique
  source_record_id, 0 failed downloads.
```

## 6. What Phase 5d does and does not establish

- Adds the first genuinely NEW acquisition source since Phase 4
  (conference abstracts) -- distinct from, and complementary to, that
  corpus: company-published presentations often predate or supplement
  what appears in AACR/ASCO's own indexed abstracts.
- Does **not** chase a Sutro item's detail page one hop deeper to find an
  embedded PDF -- same "acquisition preserves raw evidence, it does not
  chase every embedded asset" principle as Job 12's press-release detail
  pages. The detail page's own raw HTML is the acquisition artifact.
- Does **not** extract target/payload/candidate entities from this new
  corpus's content -- that is a future increment (the same Phase 3/5a
  extraction mechanism could, in principle, later be extended to this
  source's title/detail-page text, analogous to Phase 5a's extension to
  conference abstracts).
- Does **not** attempt Zymeworks or any of the 5 companies with no
  scrapable page found -- both explicitly disclosed, not silently
  narrowed.

## Reproduction

```bash
python -m adc_acquisition company_scientific_presentations --output DATA
```
