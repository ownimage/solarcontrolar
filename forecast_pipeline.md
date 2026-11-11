# forecast_pipeline.py — design

## Overview

`src/forecast_pipeline.py` is the daily planning job for the battery. It is run once per
day, in the evening (see `crontab_file`, `30 20 * * *`), and does three things in order:

1. **Fetch the solar forecast for tomorrow** from the SolCast API and store it.
2. **Compare recent forecasts against what actually happened** (solar actuals) and
   derive an error factor (a multiplier) that is applied to future forecasts.
3. **Work out how much the battery should be charged tonight** so that tomorrow's
   solar generation covers usage, and write that target to `config.json`.

Stage 2 also relies on the data recorded every minute by `minute_poller.py`
(`solar_actuals.json` and `usage_actuals.json`).

```
forecast_pipeline.py
        |
        | stage 1
        v
SolarForecastGenerator.run()  ── SolCast API (forecast for tomorrow)
        |                     ── writes solar_forecast_history.json
        | stage 2
        v
CalcError.run()               ── reads solar_forecast_history.json + solar_actuals.json
        |                     ── multiplier = actual / forecast (last 4 days)
        |                     ── writes settings.json: solar_forecast_multiplier
        | stage 3
        v
ConfigGenerator.run()        ── reads usage_actuals.json, settings.json, forecasts
                              ── writes config.json: charge_to_percentage
```

Downstream, `config_apply.py` (every minute) reads `config.json` and turns timed
charging on/off on the GivEnergy inverter until the battery reaches
`charge_to_percentage`.

---

## Environment variables

There is no `.env`/python-dotenv loader in this project. Configuration is provided
to the process through environment variables set by sourcing `envfile` (see
`crontab_file` where each job runs `. /app/envfile` before the Python script).

| Variable                 | Required | Used by          | Purpose                                        |
|--------------------------|----------|------------------|------------------------------------------------|
| `SOLCAST_API_KEY`        | yes      | forecast stage 1 | SolCast API key for solar forecasts            |
| `SOLCAST_SITE_ID`        | yes      | forecast stage 1 | SolCast rooftop site id                        |
| `GIVENERGY_API_KEY`      | yes      | forecast stage 2 | GivEnergy cloud API key for actuals/bookkeeping |
| `GIVENERGY_INVERTER_ID`  | yes      | forecast stage 2 | GivEnergy inverter id                          |
| `GIVENERGY_LOCAL_URL`    | no (dep.)| givlocal path    | Local inverter URL if using givlocal           |
| `GIVENERGY_RETRY_DELAYS` | no       | givlocal path    | Comma-separated seconds between date-fix refetches, e.g. `1,2,5,10` (default if unset/empty). Any number of values allowed. |
| `GIVENERGY_USAGE_MAX_KWH_PER_HOUR` | no | minute poller | Usage sanity ceiling (kWh/h) for the minute poller's meter reading. Default `50`. |
| `DEBUG`                  | no       | logging          | `1`, `true`, `yes` or `on` enables debug       |
| `LOG_LEVEL`              | no       | logging          | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`|

If neither `DEBUG` nor `LOG_LEVEL` is set, the pipeline logs exactly as before
(INFO level, message only). To turn debugging on for a cron job, add e.g.
`export LOG_LEVEL="DEBUG"` to `envfile` (or run `DEBUG=1 python forecast_pipeline.py`
interactively).

`GIVENERGY_RETRY_DELAYS` controls the GivLocal corruption-refetch: if
`meter-data-latest` or `system-data-latest` returns an empty/unparseable time, or
one starting `2000-01-01`, the fetch is re-run after each delay in the comma
separated list (default `1,2,5,10` — any number of values works). If every retry
still returns a bad time, the timestamp is patched with `datetime.now()`.

The minute poller applies a second sanity check to the same `meter-data-latest`
reading before writing its minute totals: the cumulative usage must not regress
against the last anchor reading, and the implied rate must not exceed
`GIVENERGY_USAGE_MAX_KWH_PER_HOUR` (default `50`). A failing reading is refetched
with the same `GIVENERGY_RETRY_DELAYS` schedule; if all retries still fail, the
reading is rejected (nothing written) and the anchor is kept, so the next good
reading recovers automatically.

---

## Data files and formats

All files live in the project root (the cron job runs with `cd /app`).

### `solar_forecast_history.json`
Written by stage 1, read by stage 2 & 3. One entry per date; each entry holds a
half-hourly list with SolCast's estimate and 10th/90th percentile power (kW,
covering the period *starting* at that time).

```json
{
  "2026-08-10": {
    "06:00": {"pv_estimate": 0.0183, "pv_estimate10": 0.0073, "pv_estimate90": 0.0256},
    "06:30": {"pv_estimate": 0.1101, "pv_estimate10": 0.0514, "pv_estimate90": 0.1156},
    ...
  }
}
```

### `solar_actuals.json`
Written by `minute_poller.py`, read by stage 2. Format
`{ date: { "HH:MM": { "0": kWh, "1": kWh, "2": kWh } } }` — the three energy-flow
types GivEnergy reports (e.g. PV, battery, grid export). The stage sums them.

### `usage_actuals.json`
Written by `minute_poller.py`, read by stage 3. Format:
`{ date: { "HH:MM": kWh } }` (flat list of half-hour consumption values).

### `settings.json`
Read/written by all stages. Of interest to the pipeline:
`solar_forecast_multiplier` (stage 2 output, stage 3 input) and the battery bias
levels `min_charge_to_bias_kwh` / `max_charge_to_bias_kwh`, `usage_multiplier`,
`battery_capacity_kWh`, `battery_min_kWh`.

### `config.json`
Stage 3 output, consumed by `config_apply.py`:

```json
{ "charge_to_percentage": 9 }
```

---

## Stage 1 — fetch tomorrow's forecast (`SolarForecastGenerator`)

Class: `src/solar_forecast_generator.py`

1. Compute tomorrow's date in the configured timezone (`Europe/London`).
2. Read `solar_forecast_history.json`. If a key for tomorrow already exists,
   **skip the API call** (the job runs daily; SolCast free tier limits calls).
3. Otherwise call SolCast:
   `GET https://api.solcast.com.au/rooftop_sites/{site}/forecasts?format=json`.
4. Convert each entry: the SolCast payload is a UTC date interval, `period_end`,
   half hour wide. Subtract 30 minutes to get the period start, then keep only
   the entries that fall on tomorrow's calendar date (in the local time zone).
5. Extract `pv_estimate` / `pv_estimate10` / `pv_estimate90` for each period and
   write `{ date: { "HH:MM": {...} } }` into the history file (merging, not
   replacing).
6. If the resulting entry would be empty (no periods on tomorrow date), a
   warning is logged but the write still happens (keeps future predictions
   available).

Debug: logged periods for tomorrow, raw kW total, skip/fetch decision.

## Stage 2 — derive the error factor (`CalcError`)

When: `src/calc_error.py`

Purpose: produce `solar_forecast_multiplier` — the correction applied in stage 3
to tomorrow's raw forecast.

1. Compare window: the **last 4 full days** — `[today − 4 days, today − 1 day]`
   inclusive, computed with the settings timezone.
2. **Forecast total** (`calculate_forecast_total`): for each history entry whose
   date is in the window, sum `0.5 × pv_estimate` per half hour. (pv_estimate is
   a power in kW; × 0.5 h converts to kWh per period.)
   Count periods; a clean 4-day window gives 4 × 48 = **192 periods**.
   Entries outside the window are skipped and logged at debug.
3. **Actual total** (`calculate_actual_total`): for each `solar_actuals.json`
   date in the window, sum the three flow types in each period’s dict.
   Count *periods* (not days) — fixes the old bug that counted one per day.
   192 periods = 48 × 4 days is the required completeness check.
4. Compute `multiplier = actual_total / forecast_total`.
5. **Sanity checks before writing** to `settings.json`:
   - `forecast_total > 0` must hold;
   - `actual_count == forecast_count == 192` (both sides complete);
   - `0.5 <= multiplier <= 1.5` (guards against mad corrections).
   If any check fails the multiplier is **not** written — old value remains
   (with a warning) and the reason is logged.
6. Write `settings.json → solar_forecast_multiplier`.

The printed `forecast total …`, `actual total …`, `solar forecast multiplier …`
lines are the historic console output and are deliberately kept as `print()`,
separate from the (switchable) structured logging.

A conservative multiplier like this slowly absorbs systematic error
(orientation, shading, seasonal bias) while refusing large/scrambled corrections.

Example: forecast 4-day total 30.0 kWh (192 periods), actual 36.5 kWh →
multiplier 1.217 is within bounds and is applied to every half-hour of tomorrow's
forecast in stage 3 (e.g. 0.12 kW × 1.217 ≈ 0.146 kW).

## Stage 3 — battery charge target (`ConfigGenerator`)

When: `src/config_generator.py`

Purpose: decide `charge_to_percentage` — how full the battery should be by the
morning, assuming tomorrow's generation fills it to 100% during sunshine hours.

1. Gather inputs:
   - `usage1` = usage actuals from 6 days ago, `usage2` from 13 days ago
     (two weeks back, same weekday type — Monday samples Monday).
     Missing days are tolerated: missing date → treated as all-zero with a
     warning; each period missing star → 0.
   - `solar` = forecast history for tomorrow. Missing entirely → treated as
     zero generation with a warning.
2. For each half-hour with `05:00 <= time <= 16:00`:
   - expected usage (kWh) = `(usage1[t] + usage2[t]) / 2 × usage_multiplier`;
   - delta (kWh) = `solar[t] × solar_forecast_multiplier × 0.5 − usage`;
   - accumulator `min_total`/`max_total` runs through the day, tracking the
     battery level bias; `min_level` = lowest running level, `max_level` =
     highest running level (starting from `min_charge_to_bias_kwh`,
     `max_charge_to_bias_kwh`).
   Debug prints each half-hour: solar kWh, usage, delta, running min/max.
3. Compute charge target:
   - `kwh_for_100_peak` = `capacity − max_level` (so the battery can reach 100%
     by 16:00 at the latest);
   - `kwh_for_before_sun` = `battery_min_kwh − min_level` (so the level never
     drops below the floor before sunrise);
   - `kwh_requirement = max(kwh_for_100_peak, kwh_for_before_sun)`;
4. Convert to percent and clamp between `battery_min_percentage`
   (`100 × min_kWh / capacity`) and 100:

```
charge_to_percentage = int(max(min_pct, min(requirement × 100 / capacity, 100)))
```

5. Write `config.json → charge_to_percentage`.

Example (from the stored settings): capacity 9.6 kWh, min 0.4 kWh; if
`max_level ≈ −1.0`, `kwh_for_100_peak ≈ 10.6` → requirement > capacity →
clamped to 100 (winter all-day charge). If `min_level ≈ +2.0`,
`kwh_for_before_sun = 0.4 − 2.0 = −1.6` → requirement from the small side →
charge only to `min_pct ≈ 4%`, letting solar do the rest.

---

## How the config is applied downstream

`config_apply.py` runs every minute and:
- reads `config.json` → `charge_to_percentage`;
- reads the current battery % and, with the tolerance in `settings.json`,
  enables or disables timed AC charging via the inverter’s setting 66
  (`set_timed_charge`).

Thus the pipeline computes tomorrow's target once, and constant application
polishes against reality all night.

---

## Debugging

### Enabling debug

| Method | Command |
|---|---|
| Interactive | `DEBUG=1 python src/forecast_pipeline.py` |
| Interactive | `LOG_LEVEL=DEBUG python src/forecast_pipeline.py` |
| Cron/deploy | add `export LOG_LEVEL="DEBUG"` (or `export DEBUG="1"`) to `envfile` |

Debug output goes to stdout with timestamps and the logger’s module name, e.g.

```
2026-08-09 10:17:03,708 DEBUG   solar_forecast_generator - Extracted 48 half-hour periods for 2026-08-10
```

The historic `print()` lines in `calc_error.py` remain unchanged; they always
appear whether or not debug is on.

### What the debug messages show

- Stage 1: fetch decision, SolCast response size, periods extracted for
  tomorrow, raw daily kW total, file written.
- Stage 2: the comparison window (timezone shown), how many periods each side
  contributed per day, totals in kWh, the raw multiplier, the outcome of the
  completeness/range checks and why a multiplier was rejected.
- Stage 3: sample usage days and their period counts, the forecast periods
  available for tomorrow, per half hour (solar, usage, delta, running min/max),
  the charging derived value and each component of the formula, and the final
  `charge_to_percentage` written.

### Common failure modes

- **Multiplier not written.** Look for `Multiplier NOT written: complete=…,
  in_range=…`. Typically the forecast history or solar actuals are incomplete
  (fewer than 192 periods), or the ratio fell outside 0.5–1.5 (very unusual
  weather). The old multiplier remains in effect.
- **Empty forecast written** — warning `Forecast for <date> is empty`. Check the
  SolCast site settings and that the account has forecast credits.
- **No solar forecast for tomorrow (stage 3)** — warning and zero generation.
  Check stage 1 ran (the crontab `30 20` entry) and the store is not corrupt.
- **Usage days missing** — warnings logged; those half-hours are treated as 0
  consumption. Check `minute_poller.py` is running (filenames) and has wrote
  the right dates.

---

## Assumptions and known limits

- The pipeline assumes `settings.json` exists and has the documented keys; if
  not, `Settings()` raises on first access.
- Half-hour coupling SolCast's `period_end` timestamps to the local timezone;
  `Europe/London` (DST handling through pytz, not `datetime.today()`).
- The 192-period check requires **both** stores to have complete full days in
  the window; a partial day anywhere in the window quietly shrinks the window
  (count < 192 → no update).
- The comparison uses the full SolCast estimate. `pv_estimate10/90` are stored
  for future filtering of bad days (not yet used).
- The pipeline never fetches **usage** forecasts itself — it uses `usage1[-6]`
  and `usage2[-13]` for tomorrow’s profile, which assumes weekday
  self-similarity with a week apart.
- `usage_multiplier` (1.45 in `settings.json`) scales expected usage upward;
  tune it to match a home's evening usage.

## Future work (not implemented here)

- Filter-outlier days from the actual/forecast comparison (e.g. comparing
  `pv_estimate10/90` coverage).
- Fallback baselines when usage/solar actuals are missing too often
  (quarterly-day averages).
- A sanity range for `charge_to_percentage` (e.g. never write 100 on a single
  90% sunny day) via config.