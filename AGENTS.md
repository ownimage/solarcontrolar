# SolarControlar: architecture and working notes

## Purpose and runtime
Python application managing overnight charging and peak discharge of a GivEnergy
battery using Solcast forecasts and historical household usage. Development is on
Windows; deployment uses Docker on Linux, /app as the working directory, cron,
and Europe/London time. See README.md, Dockerfile, crontab_file and
forecast_pipeline.md. The Python package uses a src layout; scripts run directly
from src so sibling imports work. Dependencies are pinned in requirements.txt.

## Main components and flow
- src/solarcontrolar/givenergymodbus.py: async local Modbus transport, register
  decoding, snapshot and legacy PlantWrapper; serialises inverter access using
  an OS file lock. Direct polling reads IR0-59, HR0-59 and HR96 at address 0x11,
  port 8899 by default. Only single-phase DC-hybrid 2xxx decoding is supported;
  other layouts must be implemented and tested before enabling them.
- src/minute_poller.py: cron every minute; reads the inverter, records cumulative
  energy in minute_totals.json and instantaneous power in minute_power.json;
  produces solar_actuals.json and usage_actuals.json half-hour energy estimates.
  minute_poller_state.json persists versioned previous sample/boundary state.
- src/forecast_pipeline.py: daily 20:30 orchestration of
  solar_forecast_generator.py -> calc_error.py -> config_generator.py.
  Solcast forecasts are retained in solar_forecast_history.json; recent actuals
  calibrate the forecast multiplier in settings.json. Historical usage and
  forecasts determine charge_to_percentage in config.json.
- src/config_apply.py: every minute, applies config/settings to charge/discharge
  flags. This writes to real hardware; never run it as a development test.
- src/flask_app.py with templates/ and static/: settings/control and monitoring
  interface; supports a /solar reverse-proxy prefix and API consumers.
- src/common/json_store.py: JSON persistence; relative paths resolve from the
  process working directory. src/filenames.py centralises script filenames.
  settings.py and common/dateHelper.py handle settings and dates.

## Energy and power contracts
- Power values are watts; cumulative totals and half-hour actuals are kWh.
  Solcast pv_estimate is kW, so a 30-minute forecast becomes kWh by dividing by 2.
- minute_totals.json is a series of cumulative readings, NOT energy used each
  minute. Differences are interval estimates. Do not sum cumulative readings.
- Solar total: unsigned 32-bit IR11/12 (library e_pv_total), high word first,
  divided by 10. Do NOT use IR45/46 for solar: the supplied history shows this
  counter increasing during battery discharge at zero PV power. Keep IR45/46
  separate for the existing usage balance below, regardless of the library's
  confusing e_pv_generation_total name.
- Usage estimate follows GivTCP's single-phase DC-hybrid load calculation:
  IR45/46 + grid import IR32/33 - grid export IR21/22 - AC charge IR27/28,
  each pair scaled by 0.1 kWh. Do not insert nominal battery capacity times SoC.
  See metering_review.md for evidence and important accuracy limits.
- Positive home power is consumption (IR42); positive grid power is import;
  positive battery power is discharge, negative is charging. Library grid-out
  has the opposite sign to the application's grid power.
- New minute entries carry usage_method=givtcp_dc_hybrid_v2 and
  solar_method=pv_ir11_12_v1. Existing entries
  have older/inconsistent semantics and are preserved for audit. Do not compute
  deltas across that transition. State version 3 automatically drops old anchors, including version 2
  anchors that used the old solar counter. Both counters need a new complete
  half-hour before publishing deltas after an upgrade.
- Half-hour keys identify interval START in inverter local wall time. Counters
  are interpolated at boundaries between polls at most 180 seconds apart. Only
  complete observed periods are published, rounded to 0.001 kWh (precision does
  not improve the counters' 0.1 kWh accuracy). Gaps/resets drop partial periods;
  invalid samples drop the anchor; duplicate/backwards timestamps are ignored.
- Local keys cannot distinguish the repeated autumn DST hour. Changing this
  requires a coordinated forecast/actual/UI schema migration.

## Development and verification
Run from the repository root with dependencies installed:

    python -m unittest discover -s tests -v

Tests use synthetic registers and isolated JSON stores; no network/hardware calls.
Do not start cron, the forecast pipeline, config_apply, or the Modbus module's
__main__ section during tests. The latter contacts hardware even for reads.

## Data and operational care
- envfile, .secret_key and API credentials are secrets; never print or commit
  them. envfile_template documents configuration names.
- Runtime JSON and log files can contain uncommitted user changes. Preserve them;
  do not reset, regenerate or bulk-format them as part of source changes.
- Old energy history cannot be reconstructed exactly from minute_totals.json:
  individual grid/AC charge counters and true PV IR11/12 were not retained.
  The old solar series cannot be converted exactly to the true PV series. Negative historical
  home-power readings also prevent a trustworthy automatic power-based rebuild.
- JsonStore currently performs whole-file, non-atomic writes without locking;
  simultaneous pollers can lose updates. Operate one poller writer. The Modbus
  lock protects device access, not the full poll-and-persist cycle.
- Source changes require deployment/rebuild of the running container before
  scheduled jobs use them. A local test pass is not live inverter validation.
