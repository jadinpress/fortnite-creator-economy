# Fortnite's creator economy: the money is concentrated, but the attention is worse

A concentration analysis of Fortnite's UEFN creator economy, built from a single snapshot of
**fortnite.gg** (unofficial, fan-run; not affiliated with Epic Games) — the only public source
that publishes what Epic itself doesn't: a full population breakdown of creator earnings, plus
ranked creator and map leaderboards. The question: if you were allocating a creator-partnership
budget on this platform, is money concentrated the same way attention is?

- **Dashboard:** [Tableau Public](https://public.tableau.com/app/profile/jadin.press/viz/FortnitesCreatorEconomy/FortniteCreatorEconomy) — build spec in [`docs/tableau-build.md`](docs/tableau-build.md)
- **Written readout:** [`docs/readout.md`](docs/readout.md)
- **Source audit:** [`docs/data-source-audit.md`](docs/data-source-audit.md)

---

## The question

Money and attention aren't the same thing, and platform-economics writing often treats them as
interchangeable. So this asks it directly, in three parts:

1. How concentrated are UEFN creator earnings, across the *full* creator population?
2. Among the visible "winners" — the leaderboards the site itself ranks — is concentration still
   climbing, or does it flatten out once you're already at the top?
3. Is attention concentrated at least as much as money, once the *entire* population (not just
   the visible leaderboard) is accounted for?

## Findings

Full write-up in [`docs/readout.md`](docs/readout.md). Snapshot taken 2026-08-09 03:17 UTC.

**1. Creator earnings are extremely concentrated, full population.** 75,854 creators, 8 grouped
buckets:

| Earnings | Creators | % of creators |
|---|---|---|
| < $1K | 66,642 | 87.86% |
| $1K – $10K | 6,139 | 8.09% |
| $10K – $100K | 2,218 | 2.92% |
| $100K – $300K | 484 | 0.64% |
| $300K – $1M | 255 | 0.34% |
| $1M – $3M | 81 | 0.11% |
| $3M – $10M | 20 | 0.03% |
| $10M+ | 15 | 0.02% |

95.95% of creators earn under $10K; 0.16% (116 creators) earn over $1M. **Gini at least 0.94,
plausibly approaching 0.99** (reported as a band, not one number — see Method. The low end of
the band is itself the sweep's most conservative single combination, not a safe center — see
below).

**2. Even among the visible winners, concentration doesn't stop.** Restricted to the top-ranked
creators and maps the site itself surfaces (Epic Games' own account and modes excluded — see
Method), the top 5 of 29 shown creators hold **45.4%** of that group's lifetime minutes played,
and the top 5 of 21 shown maps hold **45.6%** of that group's current players. Two different
metrics, two different populations — the near-match at the top-5 cut is close enough to be
suspicious, so it was checked at top-3 (28.1% creators vs. 31.3% maps) and top-10 (80.9% vs.
72.9%) too: both diverge by several points at both cuts. **The 45%-ish figures at top-5 are a
coincidence of this snapshot, not a discovered regularity** — reported as two separate numbers
that happen to be close, not as one shared structural finding. What both distributions do agree
on, at every cut checked, is that making the leaderboard doesn't end the inequality story.

**3. The strongest concentration number needs no binning or leaderboard at all.** Only **6,577
of 558,345** published maps — **1.18%** — have any current players whatsoever, right now. That's
a full-population statistic, immune to the top-N truncation problem that affects finding 2, and
it's more extreme than the earnings Gini. Attention on this platform isn't just concentrated at
the top; the overwhelming majority of published content has *zero* live audience at any given
moment.

## Method

### Source and its limits — read before trusting any number below

**Single snapshot, not a time series.** fortnite.gg's live counters were pulled once
(`scripts/scrape_fortnitegg.py`) and cannot be re-pulled to reproduce identical values later —
the raw HTML in `data/raw/` (committed, timestamped, with a manifest) is the reproducibility
record. No trend or causal claim is made anywhere in this project; everything here is a
description of one moment.

**Only the earnings distribution is full-population.** The creator-engagement and map-attention
leaderboards are capped at the first page (top ~30/~28 rows); further pages sit behind
`?page=N`, which the site's own `robots.txt` disallows crawling. See
[`docs/data-source-audit.md`](docs/data-source-audit.md) for the full check. This is why finding
2 is reported as a concentration ratio **within the shown slice**, not a population-wide Gini —
a Gini computed on an already-top-selected group is not comparable to the full-population
earnings Gini, and claiming otherwise would be the same selection-on-the-outcome error the
sibling `steam-retention` project rejected two candidate datasets over.

### A defect caught mid-build: Epic Games was inside its own leaderboards

Epic's own account and first-party modes (Battle Royale, Reload, etc.) rank inside both
leaderboards and initially dominated them — Epic alone was ~78% of shown creator engagement,
Epic-owned modes ~79% of shown map attention. Both distributions are filtered to exclude Epic
(`WHERE NOT is_epic` in [`sql/01_concentration.sql`](sql/01_concentration.sql)), matching the
earnings distribution, which structurally excludes Epic already (it doesn't pay itself a UEFN
creator payout). A first pass at this filter also missed Epic's creator row entirely, because
`/creators` marks Epic differently than `/creative` does — full account in the audit doc.

### The three judgment calls in the earnings Gini

Grouped/binned data needs an assumed representative value per bucket — there's no way around it
with only bucket counts, and no per-creator earnings appear anywhere else on the site (checked —
see audit). Marked `-- JUDGMENT CALL` in [`sql/01_concentration.sql`](sql/01_concentration.sql):

| # | Call | Why |
|---|---|---|
| 1a | Bottom bucket ("< $1K") representative value is swept from $10 to $500, not fixed | A geometric mean is undefined at a zero lower bound, and there's no way to know how much of this 66,642-creator bucket is clustered near zero (one map, a handful of plays) vs. near $1K. $500 (the arithmetic midpoint) turns out to be the sweep's own low-inequality outlier, not a safe center — see below |
| 1b | Top bucket ("$10M+") representative value is swept from $10M to $50M, not fixed at its lower bound | No data exists on how far above $10M this group runs |
| 1c | Every other bucket (~10x-wide ranges) uses the geometric mean of its bounds, not the arithmetic midpoint | Right-skewed quantities like earnings concentrate mass toward the low end of a wide bucket; an arithmetic midpoint overstates the typical value inside it |
| 2 | Epic Games excluded from engagement and map-attention distributions | See above — otherwise both measure "Epic is bigger than everyone," not concentration among third-party creators/maps |

Because 1a/1b are genuinely unknowable, the headline Gini is reported as a **band (0.94–0.99)**
swept across 9 combinations (bottom-bucket value $10/$100/$500 × top-bucket cap
$10M/$25M/$50M), not one falsely-precise number. The $500/$10M combination — used as the
"primary" assumption for the Lorenz curve chart itself — is the band's own **low end**, not its
center: pushing the bottom-bucket value down toward a more realistic near-zero assumption moves
the Gini up toward 0.99, not down. Read the headline as "at least 0.94, plausibly close to 0.99,"
not as "roughly 0.96."

### What this analysis cannot tell you

- **Not a trend.** One snapshot. Numbers move constantly on this site; nothing here claims a
  direction of change.
- **The earnings Gini is an estimate built on assumed within-bucket values**, not raw individual
  earnings — no source publishes those. The band communicates that uncertainty; a single point
  estimate would not.
- **The engagement/map-attention figures describe only the visible top of each leaderboard**,
  not the full creator or map population. The one full-population attention statistic available
  (finding 3) is reported separately and should not be confused with a population-wide Gini.
- **fortnite.gg is unofficial and fan-run.** Not Epic's own data, not audited, and there is no
  published methodology for how the site itself computes "earnings" or "minutes played." Treated
  here as the best publicly available proxy, not as ground truth.

## Reproducing this

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt

# 1. Pull a fresh snapshot (numbers WILL differ from the ones in this README — the site's
#    counters move continuously; this is expected, not a bug)
python scripts/scrape_fortnitegg.py

# 2. Parse, build the Lorenz curves (DuckDB), compute Gini/concentration figures
python scripts/run_analysis.py
```

`data/raw/` is committed (the snapshot itself is the only reproducibility record available for a
live site with no historical API). `data/processed/` is regenerated by `run_analysis.py` and not
committed.

## Sources

| Source | Use | Notes |
|---|---|---|
| [fortnite.gg](https://fortnite.gg) | Creator earnings buckets, creator/map leaderboards, Creative Stats totals | Unofficial, fan-run; not affiliated with Epic Games. No ToS page found; scraped conservatively — see audit for the full reasoning |

Not affiliated with Epic Games or Fortnite. All trademarks belong to their respective owners.
