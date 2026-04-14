-- SPDX-License-Identifier: MIT
-- SPDX-FileCopyrightText: 2026 Anil Belur
--
-- Materialized view: daily_athlete_summary
-- Single source of truth joining daily metrics, advanced metrics,
-- readiness scores, and VO2max estimates by (user_id, date).
--
-- Refresh after each sync/compute cycle via:
--   SELECT refresh_daily_athlete_summary();

-- Drop and recreate to handle schema changes cleanly
DROP MATERIALIZED VIEW IF EXISTS daily_athlete_summary;

CREATE MATERIALIZED VIEW daily_athlete_summary AS
SELECT
    -- Join keys
    dm.user_id,
    dm.date,

    -- Daily metrics (from Garmin sync)
    dm.steps,
    dm.calories,
    dm.resting_hr,
    dm.max_hr,
    dm.total_sleep_minutes,
    dm.deep_sleep_minutes,
    dm.rem_sleep_minutes,
    dm.light_sleep_minutes,
    dm.awake_minutes,
    dm.sleep_score,
    dm.hrv,
    dm.stress_score,
    dm.body_battery_start,
    dm.body_battery_end,
    dm.floors_climbed,
    dm.intensity_minutes,
    dm.sleep_start_time,
    dm.sleep_end_time,
    dm.sleep_need_minutes,
    dm.sleep_debt_minutes,
    dm.spo2,
    dm.respiration_rate,
    dm.garmin_training_load,

    -- Advanced metrics (from metrics-compute.py EWMA)
    am.ctl,
    am.atl,
    am.tsb,
    am.acwr,
    am.ramp_rate,
    am.cp,
    am.w_prime,
    am.frc,
    am.mftp,
    am.tte,
    am.effective_vo2max,

    -- Readiness score (from app readiness engine)
    rs.score AS readiness_score,
    rs.zone AS readiness_zone,
    rs.hrv_component,
    rs.sleep_quantity_component,
    rs.sleep_quality_component,
    rs.training_load_component,
    rs.stress_component,
    rs.resting_hr_component,
    rs.explanation AS readiness_explanation,

    -- VO2max (best source per date: official > computed)
    ve.value AS vo2max_value,
    ve.source AS vo2max_source,

    -- Metadata for debugging / staleness detection
    dm.synced_at AS daily_metric_synced_at,
    am.computed_at AS advanced_metric_computed_at,
    rs.created_at AS readiness_computed_at

FROM daily_metric dm
LEFT JOIN advanced_metric am
    ON dm.user_id = am.user_id AND dm.date = am.date
LEFT JOIN readiness_score rs
    ON dm.user_id = rs.user_id AND dm.date = rs.date
LEFT JOIN LATERAL (
    -- Pick best VO2max source per date (official > computed)
    SELECT ve2.value, ve2.source
    FROM vo2max_estimate ve2
    WHERE ve2.user_id = dm.user_id AND ve2.date = dm.date
    ORDER BY CASE ve2.source
        WHEN 'garmin_official' THEN 1
        WHEN 'computed' THEN 2
        ELSE 3
    END
    LIMIT 1
) ve ON true

ORDER BY dm.date DESC;

-- Unique index required for REFRESH CONCURRENTLY
CREATE UNIQUE INDEX IF NOT EXISTS idx_das_user_date
    ON daily_athlete_summary (user_id, date);

-- Query performance indexes
CREATE INDEX IF NOT EXISTS idx_das_date
    ON daily_athlete_summary (date DESC);
CREATE INDEX IF NOT EXISTS idx_das_user_date_range
    ON daily_athlete_summary (user_id, date DESC);

-- Refresh function (safe to call repeatedly, uses CONCURRENTLY)
CREATE OR REPLACE FUNCTION refresh_daily_athlete_summary()
RETURNS void AS $$
BEGIN
    -- CONCURRENTLY allows reads during refresh (requires unique index)
    REFRESH MATERIALIZED VIEW CONCURRENTLY daily_athlete_summary;
END;
$$ LANGUAGE plpgsql;
