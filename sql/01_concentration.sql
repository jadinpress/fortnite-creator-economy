-- ===========================================================================
-- Fortnite creator economy — concentration model
-- DuckDB. Run against the CSVs in place; no server, no load step.
--
--     duckdb -c ".read sql/01_concentration.sql"
--
-- Builds a Lorenz curve (cumulative population % vs cumulative value %) for
-- each of three distributions pulled from the same fortnite.gg snapshot, then
-- unions them into one output table. Gini coefficients are computed from this
-- output in Python (scripts/run_analysis.py), not here — the trapezoidal
-- integration is the same three lines either way, and doing it in Python
-- makes it unit-testable against synthetic reference distributions before
-- it's trusted on real data.
--
-- Every judgment call is marked -- JUDGMENT CALL and restated in the README.
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- 0. Sources
-- ---------------------------------------------------------------------------

-- Full population: 8 grouped/binned buckets of UEFN creator earnings. This is
-- the ONLY distribution here with full population coverage - see
-- docs/data-source-audit.md for why the other two are top-N only.
CREATE OR REPLACE VIEW earnings_raw AS
SELECT
    bucket,
    TRY_CAST(bucket_lower AS DOUBLE) AS bucket_lower,
    TRY_CAST(bucket_upper AS DOUBLE) AS bucket_upper,   -- NULL for the open '$10M+' bucket
    CAST(creator_count AS BIGINT)    AS creator_count
FROM read_csv_auto('data/processed/creators_by_earnings.csv', header = true);

-- Top 30 only, ranked by Players Now on /creators. minutes_played is a
-- lifetime cumulative figure - the closest thing on this site to a total
-- "attention volume" measure, which makes it the better match for earnings
-- (also a lifetime cumulative figure) than a point-in-time count would be.
--
-- Epic's own "epic" account is EXCLUDED (WHERE NOT is_epic below). It ranks
-- #1 with 1.6T lifetime minutes against ~0.45T for the other 29 rows
-- combined - roughly 78% of the shown total. Leaving it in would make this
-- "Epic Games is bigger than every third-party creator combined," which is
-- true and uninteresting, not a statement about inequality AMONG creators,
-- which is the actual question. The earnings distribution is inherently
-- third-party-only (Epic doesn't take a UEFN creator payout from itself),
-- so leaving Epic in the comparison distributions would also break the
-- like-for-like comparison the whole project is built around.
CREATE OR REPLACE VIEW engagement_raw AS
SELECT
    handle,
    TRY_CAST(minutes_played AS DOUBLE) AS minutes_played
FROM read_csv_auto('data/processed/creator_engagement.csv', header = true)
WHERE minutes_played IS NOT NULL
  AND NOT is_epic;                                              -- JUDGMENT CALL 2

-- Top 28 only, ranked by Players Now on /creative. Players Now (not
-- all_time_peak) is used here because it's the metric the site itself ranks
-- by, and it is the live-attention analogue to "who's getting played right
-- now" the same way minutes_played is "who's been played the most, ever."
--
-- Epic-owned modes (Battle Royale, Reload, OG, Blitz Royale, Save the World,
-- LEGO Fortnite Odyssey, Festival Main Stage - 7 of the 28 shown rows) are
-- EXCLUDED for the same reason: Battle Royale alone is ~59% of shown
-- players-now, and all seven Epic modes together are ~79%. That measures
-- "Epic's first-party modes dominate the Discover page," not concentration
-- among UGC maps, which is the third-party population the earnings figure
-- describes.
CREATE OR REPLACE VIEW map_attention_raw AS
SELECT
    map_id,
    title,
    TRY_CAST(players_now AS DOUBLE) AS players_now
FROM read_csv_auto('data/processed/map_attention.csv', header = true)
WHERE players_now IS NOT NULL
  AND NOT is_epic;                                               -- JUDGMENT CALL 2


-- ---------------------------------------------------------------------------
-- 1. Representative value for the grouped earnings buckets
-- ---------------------------------------------------------------------------
-- A Lorenz curve needs a value per unit of population. The other two
-- distributions have one (a real number per creator/map); earnings only has
-- a count per bucket, so a representative value has to be assumed per
-- bucket. Three sub-cases, because one formula doesn't fit all of them:
CREATE OR REPLACE VIEW earnings_repvalue AS
SELECT
    *,
    CASE
        -- JUDGMENT CALL 1a — bottom bucket ('< $1K', lower bound 0): a
        -- geometric mean is undefined at zero, so this falls back to the
        -- arithmetic midpoint of the bucket instead.
        WHEN bucket_lower = 0 THEN bucket_upper / 2.0

        -- JUDGMENT CALL 1b — top bucket ('$10M+', no upper bound): no data
        -- exists on how far above $10M this group runs, so the bucket's own
        -- lower bound is used as a floor. This is DELIBERATELY conservative:
        -- it treats all 15 creators in this bucket as earning exactly $10M,
        -- when in reality at least some earn more. The true earnings Gini is
        -- therefore at least as high as the one computed here, likely higher.
        WHEN bucket_upper IS NULL THEN bucket_lower

        -- JUDGMENT CALL 1c — every other bucket spans roughly a 10x range
        -- ($1K-$10K, $10K-$100K, ...). An arithmetic midpoint of a 10x-wide
        -- bucket sits far higher than where most of that bucket's mass
        -- actually is for a right-skewed quantity like earnings, so the
        -- geometric mean of the bounds is used instead (e.g. $1K-$10K ->
        -- ~$3,162, not the arithmetic midpoint of $5,500).
        ELSE SQRT(bucket_lower * bucket_upper)
    END AS rep_value
FROM earnings_raw;


-- ---------------------------------------------------------------------------
-- 2. Lorenz curves — cumulative population % vs cumulative value %,
--    ordered from the least valuable unit to the most valuable
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW earnings_lorenz AS
WITH totals AS (
    SELECT SUM(creator_count) AS n, SUM(rep_value * creator_count) AS total_value
    FROM earnings_repvalue
)
SELECT
    'earnings' AS distribution,
    SUM(creator_count) OVER (ORDER BY rep_value ROWS UNBOUNDED PRECEDING) * 1.0
        / t.n                                                      AS cum_pop_pct,
    SUM(rep_value * creator_count) OVER (ORDER BY rep_value ROWS UNBOUNDED PRECEDING) * 1.0
        / t.total_value                                             AS cum_value_pct
FROM earnings_repvalue, totals t
ORDER BY cum_pop_pct;

CREATE OR REPLACE VIEW engagement_lorenz AS
WITH totals AS (
    SELECT COUNT(*) AS n, SUM(minutes_played) AS total_value FROM engagement_raw
)
SELECT
    'engagement_ex_epic' AS distribution,
    ROW_NUMBER() OVER (ORDER BY minutes_played) * 1.0 / t.n         AS cum_pop_pct,
    SUM(minutes_played) OVER (ORDER BY minutes_played ROWS UNBOUNDED PRECEDING) * 1.0
        / t.total_value                                             AS cum_value_pct
FROM engagement_raw, totals t
ORDER BY cum_pop_pct;

CREATE OR REPLACE VIEW map_attention_lorenz AS
WITH totals AS (
    SELECT COUNT(*) AS n, SUM(players_now) AS total_value FROM map_attention_raw
)
SELECT
    'map_attention_ex_epic' AS distribution,
    ROW_NUMBER() OVER (ORDER BY players_now) * 1.0 / t.n            AS cum_pop_pct,
    SUM(players_now) OVER (ORDER BY players_now ROWS UNBOUNDED PRECEDING) * 1.0
        / t.total_value                                             AS cum_value_pct
FROM map_attention_raw, totals t
ORDER BY cum_pop_pct;


-- ---------------------------------------------------------------------------
-- 3. Combined output
-- ---------------------------------------------------------------------------
-- The (0, 0) origin point is prepended per distribution so the curve starts
-- at the corner of the unit square - required for both the trapezoidal Gini
-- integration in Python and for the Tableau chart to render a proper Lorenz
-- curve rather than one that starts mid-air at the first data point.
CREATE OR REPLACE VIEW lorenz_curves AS
SELECT distribution, 0.0 AS cum_pop_pct, 0.0 AS cum_value_pct
FROM (SELECT DISTINCT distribution FROM (
    SELECT distribution FROM earnings_lorenz
    UNION ALL SELECT distribution FROM engagement_lorenz
    UNION ALL SELECT distribution FROM map_attention_lorenz
))
UNION ALL
SELECT * FROM earnings_lorenz
UNION ALL
SELECT * FROM engagement_lorenz
UNION ALL
SELECT * FROM map_attention_lorenz
ORDER BY distribution, cum_pop_pct;
