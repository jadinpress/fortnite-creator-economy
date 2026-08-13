# Data Source Audit — Fortnite Creator Economy Project

**Run:** 2026-08-08, via direct HTTP checks (curl + browser inspection) against fortnite.gg.
**Purpose:** confirm crawl scope, rendering mode, and actual data depth before writing the scraper —
same discipline as `../steam-retention/docs/data-source-audit.md`, applied to a different site.

**Outcome: the site is a viable, single-pass source, but the three distributions are NOT equally
deep. Earnings is full-population; the other two are top-N only. This changes how they can be
compared and is stated up front rather than discovered after the dashboard is built.**

---

## robots.txt

```
User-agent: *
Disallow: /stats?*page=*
Disallow: /*-stats?*page=*
Disallow: /wrapped?*page=*
Disallow: /creative?*
Disallow: /creators?*
Disallow: /player-count?*
Disallow: /player-count-graph?*
Disallow: /player-count-discovery?*
```

Only query-string variants of these paths are disallowed. The base pages this project needs
(`/player-count`, `/creators`, `/creative`) are not disallowed and are fetched as single, unpaged
requests. No pagination is crawled — see "Depth" below for why that's a hard stop, not just a
courtesy.

## Terms of Service

No ToS page exists — `/terms` returns 404, and the footer "Terms" text does not resolve to a
working link. Same posture as the sibling project's steamcharts.com audit: absence of a stated
prohibition is not explicit permission. This scrape stays single-pass, low-volume (3 GET requests
total for the core pull), with an honest User-Agent identifying the project and a contact email,
and real delay between requests. No scheduled or repeated polling.

## Rendering mode

Checked by fetching `/player-count` with a plain `curl` (no JS execution) and searching the raw
response for values also visible in-browser:

- The page is fully server-rendered. "Creator count by earnings," the 8 bucket labels, and large
  comma-formatted figures (14,343,880 / 9,581,154 / 1,062,338, matching the browser-observed
  all-time-peak figures) are all present in the raw HTML.
- `<script src='/js/player-count.js?...'>` is what drives the live-ticking counter animation
  in-browser, but the snapshot values needed for this analysis are already in the initial response.

**Conclusion: plain `requests` + `BeautifulSoup` works, same as `scrape_steamcharts.py`. No
headless-browser rendering needed.**

## Depth per distribution — the finding that matters most

| Distribution | Page | Population coverage | Why |
|---|---|---|---|
| Creator earnings | `/player-count` → "Creator count by earnings" | **Full population.** 8 buckets sum to the site's live creator-count total exactly (verified twice, ~6 hours apart: 75,808 during the original browser check, 75,854 during this audit — consistent with a live-updating total, and the bucket sum matched the stated total both times). | It's a distribution table, not a ranked list — no pagination involved. |
| Creator engagement | `/creators` (ranked by Players Now) | **Top 30 only.** The page shows ranks 1–30 and no more; further rows live behind `?page=N`, which `robots.txt` explicitly disallows. | Pagination is blocked at the crawl-policy level, not just UI-limited — going around it via direct query-string requests would violate the one explicit rule the site does publish. |
| Map attention | `/creative` (ranked by Players Now) | **Top 28 only.** Same `?page=N` pagination, same `Disallow: /creative?*` rule. | Same reasoning as above. |

Individual creator pages exist (`/creator/<name>`) and individual map pages exist
(`/island/<code>`) — checked one of each (`/creator/epic`). Neither exposes a per-entity earnings
figure; the 8-bucket table on `/player-count` is the only place earnings appear anywhere on the
site. So there is no way to get a finer-grained or individual-level earnings distribution, and the
grouped-data Gini estimator (Judgment Call 1) isn't a shortcut — it's the only option.

## Consequence for the analysis

The three distributions are **not directly comparable Ginis**:

- **Earnings** — a real full-population Gini, computed from grouped/binned data (approximation
  from bucket bounds, not raw values — Judgment Call 1).
- **Engagement and map attention** — Gini (or a simpler concentration ratio) computed on the
  **visible top 30 / top 28 only**. This measures concentration *within the head of the
  distribution*, not concentration across the whole creator or map population. A Gini computed on
  a top-N slice is mechanically different from a population-wide Gini and will typically read
  differently for reasons that have nothing to do with the underlying platform economics.

This gets stated plainly in the README and readout, not smoothed over, and the top-N "Gini" is
dropped from the final output entirely in favor of a plain concentration ratio (top-5-of-shown
share) — see `scripts/run_analysis.py`. Reporting a Gini on an already-top-selected slice invites
a reader to compare it directly against the full-population earnings Gini, and that comparison
runs backwards: a full-population Gini for engagement or map attention — if it could be computed —
would almost certainly be *higher* than the earnings figure, not lower, because the excluded
population (nearly all creators, nearly all maps) sits at or near zero. The site's own numbers
support this directly without needing the blocked pagination: only 6,577 of 558,345 published maps
(1.18%) have *any* current players at all. That full-population statistic, not a top-N Gini, is
the honest way to say "attention is concentrated," and it is reported instead — see
`map_attention_full_population` in `data/processed/gini_summary.csv`.

## Defect found during the build: Epic Games is IN both leaderboards

Both `/creators` and `/creative` rank everyone who publishes content, including Epic itself.
Epic's own account (`/creator/epic`) ranks #1 on `/creators` with 1.6T lifetime minutes played -
roughly 78% of the combined total across all 30 shown rows. On `/creative`, Epic-owned modes
(Battle Royale, Reload, Fortnite OG, Blitz Royale, Save the World, LEGO Fortnite Odyssey, Festival
Main Stage - 7 of 28 shown rows) are collectively ~79% of shown players-now, with Battle Royale
alone at ~59%.

Left in, both distributions would measure "Epic Games/Epic's own modes are bigger than everyone
else," which is true and says nothing about inequality **among** creators or **among** UGC maps -
the actual question, and the one the earnings distribution is structurally scoped to (Epic
doesn't pay itself a UEFN creator payout, so it never appears in the earnings buckets at all).
Caught by eyeballing the parsed CSVs before trusting the numbers, the same discipline as the
sibling project's launch-detection defects.

**A second, related gotcha:** the two pages don't mark "this is Epic" the same way. `/creative`
tags Epic-owned map rows with a `byepic` CSS class; `/creators` has no such class anywhere on the
page — Epic's creator row looks like any other row except for its handle (`epic`) and its
obviously-platform-scale numbers. A detector that only checked the CSS class would silently pass
Epic through on `/creators` while correctly excluding it on `/creative` — which is exactly what
happened on the first pipeline run (`creator_engagement_ex_epic`'s top-5 share came out at 87.2%,
identical to the unfiltered number). Fixed by also matching on the reserved handle `epic`, and
re-verified: filtered engagement dropped to 30 -> 29 rows and the top-5 share fell to 45.4%.

## Structural consequence: Epic-owned-content Gini vs. third-party Gini are different questions

Independent of the top-N truncation issue above, `is_epic` is filtered out of both the engagement
and map-attention distributions everywhere in this project (`WHERE NOT is_epic` in
`sql/01_concentration.sql`), so every reported engagement/map figure describes third-party
creators and maps only - matching the population the earnings figure describes.

## Politeness parameters adopted for the scraper

Copied from the vetted `scrape_steamcharts.py` precedent:

- One request at a time, never concurrent.
- ≥1 second delay between requests, with jitter.
- Honest `User-Agent` naming the project and a contact address.
- Raw response cached to disk (timestamped) — this project has no larger population to page
  through, so the cache exists for reproducibility of *this exact pull*, not for resuming an
  interrupted multi-hour job.
- Total request volume for the core pull: 3 (`/player-count`, `/creators`, `/creative`).
