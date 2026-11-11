# Metering review (2026-11-11)

## What the files mean
minute_poller.py runs each minute and stores generation_total and
consumption_total from InverterSnapshot, using the inverter's timestamp.
minute_totals.json holds cumulative kWh, not minute kWh or watts. The poller
then differences counters to produce half-hour solar_actuals/usage_actuals,
which feed forecasting and battery planning. minute_power.json holds W readings.

## Findings from the supplied historical snapshot
The five dates 2026-08-13 through 2026-08-17 contain 5,806 cumulative samples.
Usage decreases within those days 84, 118, 30, 30 and 0 times respectively
(tolerance 0.000001 kWh). usage_actuals.json contains 194 half-hours, including
9 negative entries, with a minimum of -1.4 kWh. solar_actuals contains 194
half-hours with no negatives. Historical fractional usage values are consistent
with a previous SoC correction; the source now checked out no longer uses that
correction, so the files contain more than one calculation regime.

For 2026-08-16, first-to-last cumulative usage rises 18.7 kWh. Trapezoidal
integration of recorded positive house power gives approximately 12.349 kWh
over 23.98 hours of adjacent samples (gaps over 180s excluded). This is an
independent estimate, not a calibrated meter comparison. Earlier days have
negative house power from the legacy wrapper's sign inversion and cannot be
blindly integrated as household consumption. No live inverter was contacted.

## Reference comparison and implemented correction
1. GivTCP processInverterInfo calculates DC-hybrid load energy as inverter
   energy minus AC charge minus export plus import. The local implementation
   omitted AC charge IR27/28, counting grid charging as household use.
   https://github.com/britkat1980/giv_tcp/blob/main/GivTCP/read.py
2. The installed givenergy-modbus 2.13.0 register definitions agree on the
   0.1 kWh scaling and register pairs. The upstream single-phase model also
   subtracts AC charging for its daily consumption estimate. It identifies
   IR45/46 as PV generation on DC hybrids, and assigns different semantics on
   AC/AIO models. However, that label does NOT agree with the supplied device's
   night-time behaviour; see the solar follow-up below. Actual solar now uses
   the separate e_pv_total at IR11/12, as GivTCP does. Direct polling now rejects non-2xxx models rather than
   silently labelling an incompatible counter solar.
   https://github.com/dewet22/givenergy-modbus/blob/main/givenergy_modbus/model/inverter.py
3. Home Assistant documents numerical integration of W readings to estimate
   kWh and its limitations with discrete samples. This was used as an
   independent diagnostic, not substituted into the production cumulative meter.
   https://www.home-assistant.io/integrations/integration/
   https://www.home-assistant.io/docs/energy/faq/

Both direct decoding and PlantWrapper now subtract the AC charging counter;
PlantWrapper no longer negates positive house demand. Missing clock/power
fields no longer trigger arithmetic/attribute failures before validation.

The old half-hour code attached a late first reading to a rounded-down boundary,
could publish a partial startup period, and could assign a gap spanning multiple
periods to one interval. New versioned state interpolates boundary counters only
between neighbouring readings at most 180s apart and publishes only complete
periods. Negative deltas are skipped rather than written as negative usage.
The first deployment discards legacy anchors to avoid a false delta from the
changed formula. New minute entries explicitly identify their calculation method.

## Accuracy and migration limits
This correction matches the referenced DC-hybrid estimate; it is not proof of
exact household energy. PV, grid and charging counters have 0.1 kWh resolution,
may update at different times, and describe different physical measurement points.
The upstream project itself labels consumption derived and documents conversion
loss bias. Battery storage and conversion losses mean a counter energy balance
must not be treated as a calibrated AC house-load meter. A future independent
house-load accumulator using IR42 could be added with explicit coverage and gap
handling; it must not be spliced into lifetime counters without a schema change.

Historical minute_totals, power, actuals, settings and configuration were left
unchanged. They lack the raw grid and AC-charge lifetime counters needed for an
exact retrospective fix. Existing negative actuals remain suspect and can still
influence planning; do not silently rewrite or treat them as validated data.
Use a separate verified meter export to backfill history if required. Applying
the source correction to the deployed container changes future samples only.

The regression suite covers synthetic register scaling, charge exclusion, SoC
independence, signs, missing fields, unsupported models, both adapters, cron
restarts, startup, boundary interpolation, gaps, invalid/reset counters,
legacy state, duplicate/backwards timestamps and midnight.


## Solar follow-up: separate PV from inverter energy
The initial review incorrectly retained IR45/46 as the solar source, relying on
the library's e_pv_generation_total name. This was wrong for the supplied data.
GivTCP publishes PV_Energy_Total_kWh from e_pv_total, while its load calculation
uses the distinct inverter-energy counter. The installed register map defines
e_pv_total as unsigned 32-bit IR11/12, scaled by 0.1 kWh. These two quantities
must not be conflated, even when library names suggest otherwise.

Evidence: on 2026-08-15 from 00:15:42 to 00:16:42, the saved solar total increased
by 0.1 kWh while both PV-power samples were 0 W and battery discharge was
255/256 W. Across the supplied 2026-08-16 data, increments during adjacent
zero-PV samples total 1.1 kWh. These observations contradict a PV-only counter.
That day's cumulative solar change is 16.6 kWh, versus approximately 13.385 kWh
from integration of PV power (a diagnostic estimate, not an exact meter).

The direct decoder now assigns generation_total from IR11/12; PlantWrapper
uses inv.e_pv_total. Consumption retains its existing IR45/46 input, so fixing
solar cannot accidentally alter the usage calculation the user has validated.
minute_totals entries carry solar_method=pv_ir11_12_v1. State version 3 rejects
all old anchors, including version 2, avoiding a false half-hour jump when the
solar lifetime baseline changes. The absolute solar lifetime number may change
substantially at deployment because it is a different physical counter.

Existing history is preserved: IR11/12 was not logged and cannot be recovered
exactly from the old series. The solar_actuals used to calibrate forecasts are
also affected historically; use newly collected or independently verified PV
data for assessing forecast accuracy. No automatic historical backfill was done.

Additional regression tests cover PV high-word/scaling, missing PV data, a
battery-only inverter-energy increase with unchanged solar, adapter parity,
and migration from version-2 solar anchors. All 18 tests pass without accessing
hardware. Deployment and a read-only comparison with the inverter's PV meter
are still needed for live validation.
