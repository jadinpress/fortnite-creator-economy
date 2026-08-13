#!/usr/bin/env python3
"""
Parse the fortnite.gg snapshot, build the Lorenz curves in DuckDB, compute Gini coefficients,
and write the Tableau extract.

Reads the most recent snapshot in data/raw/ (or --snapshot <id> for a specific one) and writes:
  data/processed/creators_by_earnings.csv   - full population, 8 grouped buckets
  data/processed/creator_engagement.csv     - top 30 only (see docs/data-source-audit.md)
  data/processed/map_attention.csv          - top 28 only (see docs/data-source-audit.md)
  data/processed/lorenz_curves.csv          - cumulative-population-% vs cumulative-value-%, all 3
  data/processed/gini_summary.csv           - one Gini (or concentration ratio) per distribution

Usage:
    python scripts/run_analysis.py
    python scripts/run_analysis.py --snapshot 20260809T031736Z
"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from bs4 import BeautifulSoup
    import pandas as pd
    import duckdb
except ImportError:
    sys.exit("Missing dependencies. Run:  pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
SQL = ROOT / "sql" / "01_concentration.sql"

SUFFIX_MULT = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_number(text):
    """'1,094,967' / '823.1K' / '1.6T' / '61%' -> float. None if unparseable."""
    if text is None:
        return None
    t = text.strip().replace(",", "").replace("%", "").strip("()")
    if t in ("", "-"):
        return None
    m = re.match(r"^([\d.]+)\s*([KMBT])$", t, re.I)
    if m:
        return float(m.group(1)) * SUFFIX_MULT[m.group(2).upper()]
    try:
        return float(t)
    except ValueError:
        return None


def parse_bucket_bounds(label):
    """'$1K - $10K' -> (1_000, 10_000). '< $1K' -> (0, 1_000). '$10M+' -> (10_000_000, None)."""
    label = label.strip()

    m = re.match(r"^<\s*\$([\d.]+)([KMB])$", label, re.I)
    if m:
        return 0.0, float(m.group(1)) * SUFFIX_MULT[m.group(2).upper()]

    m = re.match(r"^\$([\d.]+)([KMB])\s*-\s*\$([\d.]+)([KMB])$", label, re.I)
    if m:
        lo = float(m.group(1)) * SUFFIX_MULT[m.group(2).upper()]
        hi = float(m.group(3)) * SUFFIX_MULT[m.group(4).upper()]
        return lo, hi

    m = re.match(r"^\$([\d.]+)([KMB])\+$", label, re.I)
    if m:
        return float(m.group(1)) * SUFFIX_MULT[m.group(2).upper()], None

    raise ValueError(f"Could not parse bucket label: {label!r}")


def latest_snapshot_id():
    manifests = sorted(RAW.glob("manifest_*.json"))
    if not manifests:
        sys.exit(f"No manifest_*.json found in {RAW}. Run scripts/scrape_fortnitegg.py first.")
    return json.loads(manifests[-1].read_text(encoding="utf-8"))["snapshot_id"]


def load_page(snapshot_id, page):
    path = RAW / f"{page}_{snapshot_id}.html"
    if not path.exists():
        sys.exit(f"Missing {path}. Snapshot {snapshot_id} is incomplete.")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Page-specific parsers
# ---------------------------------------------------------------------------

def parse_earnings(html):
    """The 8-bucket 'Creator count by earnings' chart on /player-count. Full population."""
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find(string=re.compile(r"^Creator count by earnings$", re.I))
    if heading is None:
        raise ValueError("'Creator count by earnings' heading not found - page layout changed?")
    chart_wrap = heading.parent.parent  # div.chart-wrap-wrap
    chart = chart_wrap.find("div", style=re.compile("margin-top:18px"))

    rows = []
    for row in chart.find_all("div", recursive=False):
        cells = row.find_all("div", recursive=False)
        if len(cells) != 2:
            continue
        count_cell, label_cell = cells
        span = count_cell.find("span")
        pct = parse_number(span.get_text()) if span else None
        count_match = re.match(r"\s*([\d,]+)", count_cell.get_text())
        count = int(parse_number(count_match.group(1))) if count_match else None
        label = label_cell.get_text(strip=True)
        lo, hi = parse_bucket_bounds(label)
        rows.append({
            "bucket": label,
            "bucket_lower": lo,
            "bucket_upper": hi,
            "creator_count": count,
            "pct_of_total": pct,
        })

    if len(rows) != 8:
        raise ValueError(f"Expected 8 earnings buckets, parsed {len(rows)} - page layout changed?")
    return rows


def parse_creative_stat(html, label):
    """One figure from the 'Creative Stats' overview block on /player-count, by its label
    (e.g. 'Creators', 'Maps', 'Currently played maps'). Used both for the earnings
    cross-check and for the honest full-population attention-concentration statement."""
    soup = BeautifulSoup(html, "html.parser")
    for title_div in soup.select("div.stats-overview-title"):
        if title_div.get_text(strip=True) == label:
            num_div = title_div.find_next_sibling("div", class_="stats-overview-number")
            return int(parse_number(num_div.get_text()))
    return None


def parse_ranked_islands(html):
    """Shared structure behind /creators (creator engagement) and /creative (map attention):
    a.island rows, a div.rank, a div.column-2 of <span>label</span> value metric divs."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for a in soup.select("a.island"):
        rank_div = a.select_one("div.rank")
        rank = int(rank_div.get_text(strip=True)) if rank_div else None
        href = a.get("href", "")
        entity_id = href.rsplit("/", 1)[-1]
        is_epic = "byepic" in (a.get("class") or [])

        title_tag = a.select_one("h3.island-title")
        if title_tag:
            name = title_tag.get_text(strip=True)
        else:
            col1 = a.select_one("div.column-1")
            name = "".join(col1.find_all(string=True, recursive=False)).strip()

        metrics = {}
        col2 = a.select_one("div.column-2")
        for m in col2.find_all("div", recursive=False):
            label_tag = m.find("span")
            if not label_tag:
                continue
            label = label_tag.get_text(strip=True)
            full_text = m.get_text(" ", strip=True)
            value_text = full_text.replace(label, "", 1).strip()
            metrics[label] = value_text

        rows.append({
            "rank": rank, "id": entity_id, "name": name, "is_epic": is_epic, **metrics,
        })
    return rows


def build_creator_engagement(html):
    raw = parse_ranked_islands(html)
    out = []
    for r in raw:
        out.append({
            "rank": r["rank"],
            "handle": r["id"],
            # On /creators, unlike /creative, there is no CSS class marking Epic's own
            # account - the 'byepic' class only appears on Epic-owned MAPS. Epic's
            # official creator account has the reserved handle "epic" (rank 1, 1.6T
            # lifetime minutes vs ~0.45T for the other 29 rows combined), so it's
            # detected by handle instead. Caught by spot-checking row 1 against the
            # is_epic column after the first pipeline run - it was silently False.
            "is_epic": r["is_epic"] or r["id"] == "epic",
            "players_now": parse_number(r.get("Players Now")),
            "minutes_played": parse_number(r.get("Minutes Played")),
            "followers": parse_number(r.get("Followers")),
            "favorites": parse_number(r.get("Favorites")),
            "maps": parse_number(r.get("Maps")),
        })
    return out


def build_map_attention(html):
    raw = parse_ranked_islands(html)
    out = []
    for r in raw:
        out.append({
            "rank": r["rank"],
            "map_id": r["id"],
            "title": r["name"],
            "is_epic": r["is_epic"],
            "players_now": parse_number(r.get("Players Now")),
            "all_time_peak": parse_number(r.get("All-Time Peak")),
            "minutes_played": parse_number(r.get("Minutes Played")),
        })
    return out


# ---------------------------------------------------------------------------
# Gini from a Lorenz curve, via trapezoidal integration
# ---------------------------------------------------------------------------

def gini_from_lorenz(points):
    """points: [(cum_pop_pct, cum_value_pct), ...], already sorted, starting at (0,0)
    and ending at (1,1). Returns Gini = 1 - 2 * (area under the Lorenz curve).

    Perfect equality is the diagonal (area = 0.5, Gini = 0). Maximal inequality is the
    curve hugging the x-axis then jumping to 1 (area -> 0, Gini -> 1).
    """
    area = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        area += (x1 - x0) * (y0 + y1) / 2.0   # trapezoid
    return 1 - 2 * area


def _self_test_gini():
    """Sanity check the calculation BEFORE trusting it on real data - same discipline as
    the sibling project's launch-detection checks. Run on every invocation; cheap and it
    is exactly the kind of silent-wrong-math bug that would otherwise reach the dashboard."""
    n = 100
    # Perfect equality: everyone holds an identical share -> Lorenz curve is the diagonal.
    equal_points = [(0.0, 0.0)] + [((i + 1) / n, (i + 1) / n) for i in range(n)]
    gini_equal = gini_from_lorenz(equal_points)
    assert abs(gini_equal) < 1e-9, f"equal-distribution Gini should be ~0, got {gini_equal}"

    # Maximal inequality: one holder has everything -> curve hugs the x-axis, then jumps.
    unequal_points = [(0.0, 0.0)] + [((i + 1) / n, 0.0) for i in range(n - 1)] + [(1.0, 1.0)]
    gini_unequal = gini_from_lorenz(unequal_points)
    # With n=100 discrete steps this converges close to but not exactly 1 (the last
    # trapezoid still has finite width); require it well above any real-world Gini.
    assert gini_unequal > 0.97, f"maximally-unequal Gini should be close to 1, got {gini_unequal}"

    print(f"Gini self-test OK (equal={gini_equal:.4f}, maximally unequal={gini_unequal:.4f})")


def top_n_share(values_ascending, top_n):
    """Share of total value held by the top `top_n` entries of an ascending-sorted list."""
    total = sum(values_ascending)
    if total == 0:
        return None
    return sum(values_ascending[-top_n:]) / total


def earnings_rep_value(bucket_lower, bucket_upper, bottom_rep, top_cap):
    """Same three-case logic as sql/01_concentration.sql's earnings_repvalue view, but
    parameterized on the bottom-bucket representative value and the top-bucket cap, so it
    can be swept across a small grid for the sensitivity band below. bottom_rep and top_cap
    default to $500 / $10M, matching the SQL's primary (JUDGMENT CALL 1a/1b) assumptions."""
    if bucket_lower == 0:
        return bottom_rep
    if bucket_upper is None:
        return top_cap
    return (bucket_lower * bucket_upper) ** 0.5


def earnings_gini_sensitivity(earnings_rows):
    """The single 0.9373-style figure is suspiciously precise for grouped data built on two
    genuinely unknowable assumptions (what the top bucket really earns, and where the mass
    sits inside the bottom bucket). Sweep both across a small defensible grid instead of
    reporting one number, and report the range - see docs/data-source-audit.md.

    $500 (the bottom bucket's arithmetic midpoint) turns out to be the grid's OWN low-end
    outlier, not a safely-conservative center: 66,642 creators sit in that bucket, and it is
    entirely plausible many of them earn near zero (one map, a handful of plays) rather than
    ~$500. Sweeping bottom_rep down to $100 and $10 pushes the Gini from 0.94 toward 0.99, not
    away from it - so the honest framing is "at least 0.94, plausibly approaching 0.99," not a
    band centered on $500."""
    bottom_reps = [500, 100, 10]
    top_caps = [10_000_000, 25_000_000, 50_000_000]
    ginis = []
    for bottom_rep in bottom_reps:
        for top_cap in top_caps:
            valued = [
                (earnings_rep_value(r["bucket_lower"], r["bucket_upper"], bottom_rep, top_cap),
                 r["creator_count"])
                for r in earnings_rows
            ]
            valued.sort(key=lambda t: t[0])
            n = sum(c for _, c in valued)
            total_value = sum(v * c for v, c in valued)
            points = [(0.0, 0.0)]
            cum_pop = cum_val = 0
            for v, c in valued:
                cum_pop += c
                cum_val += v * c
                points.append((cum_pop / n, cum_val / total_value))
            ginis.append(gini_from_lorenz(points))
    return min(ginis), max(ginis)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None, help="snapshot id, e.g. 20260809T031736Z")
    args = ap.parse_args()

    snapshot_id = args.snapshot or latest_snapshot_id()
    print(f"Using snapshot: {snapshot_id}")

    player_count_html = load_page(snapshot_id, "player_count")
    creators_html = load_page(snapshot_id, "creators")
    creative_html = load_page(snapshot_id, "creative")

    earnings = parse_earnings(player_count_html)
    engagement = build_creator_engagement(creators_html)
    map_attn = build_map_attention(creative_html)

    PROCESSED.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(earnings).to_csv(PROCESSED / "creators_by_earnings.csv", index=False)
    pd.DataFrame(engagement).to_csv(PROCESSED / "creator_engagement.csv", index=False)
    pd.DataFrame(map_attn).to_csv(PROCESSED / "map_attention.csv", index=False)

    # Cross-check: bucket counts must sum to the independently-displayed Creators total.
    # This is the same internal-consistency check used during planning, re-run against
    # whatever this specific snapshot actually contains (the number moves; the identity
    # between the two figures on the same page should not).
    bucket_sum = sum(r["creator_count"] for r in earnings)
    independent_total = parse_creative_stat(player_count_html, "Creators")
    print(f"Earnings buckets sum to: {bucket_sum:,}")
    print(f"Creative Stats 'Creators' total: {independent_total:,}")
    if independent_total is not None and bucket_sum != independent_total:
        diff = bucket_sum - independent_total
        print(f"WARNING: mismatch of {diff:,} - counters are live and can drift a few seconds "
              f"apart between the two page sections. Investigate if the gap is large.")
    else:
        print("Cross-check OK: bucket sum matches the independent total exactly.")

    print(f"\nWrote {len(earnings)} earnings buckets, {len(engagement)} ranked creators, "
          f"{len(map_attn)} ranked maps to {PROCESSED}")

    # -----------------------------------------------------------------
    # Lorenz curves (DuckDB) + Gini coefficients (Python)
    # -----------------------------------------------------------------
    # Epic Games' own account/modes are excluded inside the SQL (engagement_raw,
    # map_attention_raw) - see the JUDGMENT CALL 2 comments there. Left in, Epic alone is
    # ~78% of shown creator-engagement and Epic-owned modes are ~79% of shown map
    # players-now, which would make both distributions measure "Epic is bigger than
    # everyone else," not concentration AMONG third-party creators/maps - the thing the
    # earnings distribution (which structurally excludes Epic; it doesn't pay itself a
    # UEFN creator payout) is actually about.
    _self_test_gini()

    con = duckdb.connect()
    con.execute(SQL.read_text(encoding="utf-8"))
    lorenz_df = con.execute("SELECT * FROM lorenz_curves ORDER BY distribution, cum_pop_pct").df()
    lorenz_df.to_csv(PROCESSED / "lorenz_curves.csv", index=False)

    # Earnings: full population (75,854 creators from a live snapshot), so its Gini is
    # the headline number - but the grouped-bucket assumptions (bottom-bucket rep value,
    # top-bucket cap) are genuinely unknowable, so it is reported as a band, not one
    # suspiciously precise figure. See earnings_gini_sensitivity() docstring.
    earnings_pts = list(lorenz_df.loc[lorenz_df["distribution"] == "earnings",
                                       ["cum_pop_pct", "cum_value_pct"]]
                         .itertuples(index=False, name=None))
    earnings_gini_primary = gini_from_lorenz(earnings_pts)
    earnings_gini_low, earnings_gini_high = earnings_gini_sensitivity(earnings)

    # Engagement / map attention: NOT full population (top 29 / top 21 after excluding
    # Epic - see docs/data-source-audit.md). A Gini computed on an already-top-selected
    # slice is not comparable to a full-population Gini and is not reported as one here.
    # Instead: a concentration ratio WITHIN the visible slice (top5_share_of_shown_pct),
    # explicitly labeled as such.
    engagement_ex_epic = [r for r in engagement if not r["is_epic"] and r["minutes_played"] is not None]
    map_ex_epic = [r for r in map_attn if not r["is_epic"] and r["players_now"] is not None]
    engagement_vals = sorted(r["minutes_played"] for r in engagement_ex_epic)
    map_vals = sorted(r["players_now"] for r in map_ex_epic)

    # The honest full-population attention statement, which needs no top-N truncation at
    # all: what share of ALL published maps have any current players whatsoever, right
    # now. This is a stronger concentration signal than any top-N Gini could honestly
    # claim, and it comes straight from the Creative Stats block already on the page.
    maps_total = parse_creative_stat(player_count_html, "Maps")
    maps_currently_played = parse_creative_stat(player_count_html, "Currently played maps")
    pct_maps_played = (maps_currently_played / maps_total * 100) if maps_total else None

    summary_rows = [
        {
            "distribution": "earnings", "metric": "gini",
            "value_low": round(earnings_gini_low, 2), "value_mid": round(earnings_gini_primary, 2),
            "value_high": round(earnings_gini_high, 2),
            "n_shown": bucket_sum, "n_total_population": bucket_sum,
            "notes": "Full population. Grouped-bucket Gini; band swept across bottom-bucket "
                     "rep value $10/$100/$500 and top-bucket cap $10M/$25M/$50M (9 combinations). "
                     "$500/$10M (the most conservative single combination) is the band's own low "
                     "end, not its center - see docs/data-source-audit.md.",
        },
        {
            "distribution": "creator_engagement_ex_epic", "metric": "top5_share_of_shown_pct",
            "value_low": None, "value_mid": round(top_n_share(engagement_vals, 5) * 100, 1),
            "value_high": None,
            "n_shown": len(engagement_vals), "n_total_population": bucket_sum,
            "notes": f"Top {len(engagement_vals)} non-Epic creators by lifetime minutes played, "
                     "shown on /creators page 1 (robots.txt blocks further pages - NOT the full "
                     "75,854-creator population). Concentration WITHIN this visible slice only.",
        },
        {
            "distribution": "map_attention_ex_epic", "metric": "top5_share_of_shown_pct",
            "value_low": None, "value_mid": round(top_n_share(map_vals, 5) * 100, 1),
            "value_high": None,
            "n_shown": len(map_vals), "n_total_population": maps_total,
            "notes": f"Top {len(map_vals)} non-Epic maps by players-now, shown on /creative "
                     "page 1 (robots.txt blocks further pages - NOT the full map population). "
                     "Concentration WITHIN this visible slice only.",
        },
        {
            "distribution": "map_attention_full_population", "metric": "pct_maps_with_any_players",
            "value_low": None, "value_mid": round(pct_maps_played, 2) if pct_maps_played else None,
            "value_high": None,
            "n_shown": maps_total, "n_total_population": maps_total,
            "notes": f"{maps_currently_played:,} of {maps_total:,} published maps have ANY "
                     "current players at all. Full population, no pagination or top-N "
                     "truncation involved - the strongest concentration statement this "
                     "snapshot supports.",
        },
    ]

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(PROCESSED / "gini_summary.csv", index=False)

    print()
    print(summary_df.drop(columns=["notes"]).to_string(index=False))
    print(f"\nWrote {PROCESSED / 'lorenz_curves.csv'} and {PROCESSED / 'gini_summary.csv'}")


if __name__ == "__main__":
    main()
