# Tableau Public build spec

**Not built here.** Tableau Public is a GUI authoring tool (shelf drag-drop, calculated-field
dialogs, dual-axis setup) with no scriptable interface available in this environment, and the
underlying numbers changed twice during analysis (the Epic-exclusion fix below moved the
engagement figure from 87.2% to 45.4%). Building it blind via pixel automation against numbers
that were still moving would be exactly the kind of unverified "looks right in a screenshot" work
the rest of this project has tried hard to avoid. What follows is precise enough to build in
Tableau Public in about 20–30 minutes, the same way `steam_retention.twbx` was authored directly.

Data sources (Data > New Data Source > Text File):
- `data/processed/lorenz_curves.csv`
- `data/processed/gini_summary.csv`

---

## Sheet 1 — Lorenz Curves

**Mark type:** Line

- **Columns:** `cum_pop_pct` (continuous, format as percentage)
- **Rows:** two measures, both on the same axis (drag the second onto the first's axis until
  it highlights, to get a single combined axis rather than dual-axis):
  1. `cum_value_pct`
  2. A new calculated field, **`Equality Line`** = `[cum_pop_pct]` — plots the perfect-equality
     diagonal as a fourth "distribution."
- **Color:** `distribution` (from `lorenz_curves.csv`). Give `Equality Line`'s row a distinct
  flat grey/dashed treatment (Format > Lines, or duplicate the field as `"Equality (reference)"`
  and set it manually) so it doesn't compete visually with the three real curves.
- **Format Y-axis and X-axis** both as percentages, 0–100%, synchronized.
- Rename the three real distributions in the legend via aliasing if the raw values
  (`earnings`, `engagement_ex_epic`, `map_attention_ex_epic`) read as too technical — suggested
  aliases: "Creator earnings (full population)", "Creator engagement, top 29 ex-Epic",
  "Map attention, top 21 ex-Epic".

This is the chart that carries the finding: the earnings curve should visibly hug the axis
harder than the other two before jumping toward the top — that's the "money is more concentrated
than the visible attention leaderboard" claim, made visually rather than asserted.

## Sheet 2 — KPI tiles

Four text tiles, one per row of `gini_summary.csv`, built as simple big-number text marks (Sheet
> Text mark, large font for the number, small caption below):

| Tile | Source row (`distribution` / `metric`) | Display |
|---|---|---|
| Earnings concentration | `earnings` / `gini` | **"Gini 0.94–0.99"** using `value_low`–`value_high`, caption "Full population, 75,854 creators — 0.94 is the band's conservative low end, not a center" |
| Top creators (ex-Epic) | `creator_engagement_ex_epic` | **"45.4%"** (`value_mid`), caption "held by the top 5 of the top 29 non-Epic creators shown" |
| Top maps (ex-Epic) | `map_attention_ex_epic` | **"45.6%"** (`value_mid`), caption "held by the top 5 of the top 21 non-Epic maps shown" |
| Map attention, full population | `map_attention_full_population` | **"1.18%"** (`value_mid`), caption "of all 558,345 published maps have ANY current players" |

The fourth tile is the strongest number in the whole piece and should be the largest/most
prominent — it's the one full-population attention statistic that needed no top-N truncation to
produce, and it's more extreme than the earnings Gini.

## Sheet 3 — Top-5 concentration comparison (creators vs. maps only)

**Mark type:** Bar. **Do not include the earnings Gini or the full-population map stat on this
chart** — they are on different scales and answer different questions (a 0–1 Gini across a full
population vs. a 0–100% share within an already-selected top slice). Putting all four on one axis
is the exact comparability error this project spent time correcting; keep this chart to the two
figures that genuinely are comparable:

- **Rows:** `distribution` filtered to `creator_engagement_ex_epic` and `map_attention_ex_epic`
- **Columns:** `value_mid`
- Label each bar with its value and a one-line subtitle: "top 5 of N shown, Epic excluded"
- These two bars land close (45.4% vs. 45.6%) but checked at top-3 (28.1%/31.3%) and top-10
  (80.9%/72.9%) they diverge by several points — don't caption this chart as revealing a shared
  "~45% rule," it's this snapshot's coincidence at exactly n=5. Caption it as two independently
  concentrated groups, not one pattern.

## Dashboard assembly

One dashboard, `fortnite_creator_economy.twbx`:

- **Title:** "Fortnite's Creator Economy: Is Money More Concentrated Than Attention?"
- **Top:** Sheet 1 (Lorenz Curves), full width
- **Middle:** four KPI tiles from Sheet 2, in a row
- **Bottom:** Sheet 3 (comparison bar), left-aligned, with a text caption to its right stating
  the headline finding in one sentence (pull from `docs/readout.md` once written)
- **Footer text box** (small, grey): data source and snapshot timestamp (from
  `data/raw/manifest_*.json`), a one-line note that fortnite.gg is unofficial/fan-run and not
  affiliated with Epic Games, and "grouped-bucket earnings estimate; engagement/map figures are
  top-N leaderboard snapshots, not full-population statistics — see README for method."

## Formatting notes

- Keep the palette simple — Tableau's default categorical palette is fine for the three Lorenz
  curves; there's no pass/fail or good/bad semantic here, so avoid red/green.
- All percentages to 1 decimal place; the earnings Gini band to 2 decimals (matches the
  precision the grouped-data method actually supports — the pipeline deliberately stopped
  reporting a 4-decimal Gini for exactly this reason).
- Published to Tableau Public at public visibility:
  [Fortnite's Creator Economy](https://public.tableau.com/app/profile/jadin.press/viz/FortnitesCreatorEconomy/FortniteCreatorEconomy),
  linked from the README's "Dashboard" line.
