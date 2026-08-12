# Introduction

I have solar panels and a GivEnergyInverter and battery.  

My tariff means that it is better to charge my battery during the day with excess PV energy (which I could sell at about 9p/unit)
rather than from the Grid overnight (where it costs me 15p/unit).

But I also want my battery to be 100% full at the start of the peak discharge price time where it can cost me 36p per unit to use
and I can sell for 26p.

So this project aims to get a solar forcast for the next day, and charge the battery overnight to the right level based on my typical usage.

## Prerequisites

You need to have a solar panels, a GivEnergy inverter and battery and either
1. a https://givenergy.cloud/ login (but you now need the premium account), or
2. a givlocal install  

We are going to get our solar prediction from https://solcast.com/
You need to create a login and define your solar installation there to get a forcast.
API documentation https://docs.solcast.com.au/

# Overview

## Development process
Develop in on PC in PyCharm, deploy to docker on a Linux machine.

This limits the number of times I need to do clean builds and pull cards out of RPis etc.

## Doing the stuff
Every 5 mins we will apply the values from the config.json to limit the charging and discharging of the battery.

Once the discharge period is over in the evening we will:
1) fetch a new solar forcast
2) generate a config file

# Running the Container

## First time configuration
```shell
copy envfile_template envflie
```
**Edit the values of docker-compose.yml to reflect your environment.**  
DO NOT CHECK THIS INTO SOURCE CONTROL - unless you know what you are doing.

## Start the container and exec into it
```shell
docker login
```
```shell
docker compose up -d
```

```shell
docker exec -it -u user -w /app solarcontrolar bash
```
Note this is cmd not PowerShell

## Install crontabs
```shell
crontab crontab_file
```

## Run tests
```shell
python -m unittest discover -s tests
```

## Getting a Forcast

```shell
python solar_forecast_generate.py
```






## Files

| File                        | Description                                                                                                                             |
|-----------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| usage_baseline.json         | .This gives a day of week and holiday baseline usage as a fallback if there is no specific usage_forecast.json entry                    |
| usage_forcast.json          | .This allows for variations to be made, e.g. mark day as holiday, or mark extra/less kWh.                                               |
| solar_forecast.json         | This is the forcast from solcast.  It will be updated on a running basis for the history too. This will be based on half hourly values. |
| settings.json               | The battery size, min charge, how much to multiply the solar forecast by etc.                                                           |
| config_generator.py         | Will run daily at 20:30 and use the above json files to generate a config.json (see below)                                              |
| config.json                 | Stores the charge/discharge values for the battery                                                                                      |
| solar_forecast_generate.py  | Logs into solcast and fetched the forecast                                                                                              |
| config_apply.py             | Runs every minute and turns the givenergy battery charge from mains, or discharge to grid on or off.                                    |
| config_apply.log            | Stores the result of the config_apply.py                                                                                                |
| crontab_file                | The time shedule file for running stuff                                                                                                 |
| envfile_template            | Used to generate envfile                                                                                                                |
| requirements.txt            | The pip requirements                                                                                                                    |
| solarcontrolar/givenergy.py | This is the interface to the givenergy API for actuals and                                                                              |
| solarcontrolar/solcast.py   | This is the interface to the solcast API for solar forecasts.                                                                           |
| solarcontrolar/config.py    | This an accessor/manager for the config.json file                                                                                       |   
| Dockerfile                  | The build script for our development image                                                                                              |
Samples

### usage_daily_averages.json
```json lines
{
    "Monday": 12.12,
    "Tuesday": 9.5,
    "Sunday": 9.99,
    "Holiday": 4.5
}
```

### usage_forcast.json
```json lines
{
    "2025-05-01": { "holiday": false, "kWh_adjustment": -1 },
    "2025-05-02": { "holiday": false, "kWh_adjustment": 1 }
}
```

### config.json
```json lines
{
  "morning_percentage": 20,
  "evening_percentage": 25
}
```
Meaning: 

morning_percentage between 02:00 and 05:00 charge the battery to a max of 20%.  This is the pre-fill so solar should get you to 100% by 16:00 the next day. During the winter this could be 100%.  

evening_percentage between 16:00 and 19:00 discharge the battery to a min of 25%. This is the evening reserve so that you dont need to buy from the grid later that evening.  STILL WORK IN PROGRESS.


### config-generator.py
This will be run on a daily basis at 20:00 ?  
It will fetch the solar forecast from solcast and update the solar_forecast.json
It will get the solar forecast for tomorrow
Ingest the usage estimate for 


## Other junk

We are going to get our solar prediction from toolkit.solcast.com.au
API documentation https://docs.solcast.com.au/


set SOLCAST_API_KEY=<your-api-key>
set SOLCAST_SITE_ID=<your-site-id>
```shell
docker run -it --rm -e SOLCAST_API_KEY=%SOLCAST_API_KEY% -e SOLCAST_SITE_ID=%SOLCAST_SITE_ID% -v "%cd%":/app -w /app solarcontrolar:latest bash
```

```
python main.py
```

What I need is a way to get forecasts and historic data.  I will compare the historic data with the GivEnergy
historic actuals to adjust the forcast to get a better result.

```shell
curl -X GET "https://api.givenergy.cloud/v1/inverter/FD2325G412/data?start=2024-01-01T00:00:00Z&end=2024-01-31T23:59:59Z" \
     -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiI5NTc3MDIxOS1jYWE2LTRmOTctOTE3Ni0zNDBlZGMzZDQxNTgiLCJqdGkiOiI4ZGRjYjQxNzEwYzViOTY5YzdhOTI2M2E4M2IzNTU2M2I4ZDU3YmVlOTRiOTU0ZjQ4ZDM0YTYzOTdhY2FiMGFiNjMyYTM0ZDk2MzcxYjAxNiIsImlhdCI6MTc0NTY4MjkyMy4zOTcsIm5iZiI6MTc0NTY4MjkyMy4zOTcwMDQsImV4cCI6MTc0NjI4NzcyMy4zODY2ODEsInN1YiI6Ijc1MTE4Iiwic2NvcGVzIjpbImFwaSJdfQ.hCQ9cKQwIFv2IUvJdmEA0o1XQc908zxRkXYg76q0dBfAaWDBDr4lg0PDcj_YCt2YpTYJHRy2NpqSKiXvT-sRx7tTw06YhXsbfvercQODwMzj9s4LqvWvGQIvGYatx3DDpz_hXJH7jqdApLlb5k9z0BwYD8YnoTUxiXWtc9_6h9sB3V7L-2f6VHV6tSmBdcayiV41AFxqKpBWRXqhb-6ucjBIgFIBhKj0vkbE-EYKp083oSPNr8YbN4XuFZ2rL-8PQgEzijrsY5ngAFYSPkGMgWe_fAw9qB32ZJBUNBi0kQmijSCSUaHWNnCKWAFlLLtU7Gpg-9TqW_Sw9_9irOO7-hGCX1-Y2CvFIFQhVVqzm5SztVp2bJAExI_nXbNI0rxhwUefSiQtdUmwPIfkcExZ8NWkt0zpdC_m1d7OlJ4gVCwE2CN8BTAE_pbewVEIB0TiUfdVS1IJqTLs_FME3klp2BiwiE4angTR1B3p5Gs91yKcRl5dOnKRTJmmkPOPOKUqKe8jppu4-L8tgngyeWPyDmtw-dJ_IcbrmyAePXd_K5ZpO0uliSDbf1N_zjlXp15Tbv7i8z9DucmhlqDL-bFp8s5rtSOIir3K09ZbpYfSHNCz9VSkxYV66MfX4ThsLxalNwCxUg_FCNBCw6fZs8yl8VlQlzp9O9WXaYhAoPiZxmc" \
     -H "Accept: application/json"
```

# Data Format
{
  "generation": "gen3",
  "serialNumber": "FD2325G412",
  "modelCode": 8193,
  "solarPower": 1979,
  "pvString1Power": 926,
  "pvString2Power": 1053,
  "batteryPower": -157,
  "gridPower": 1190,
  "loadPower": 517,
  "inverterOutputPower": 1707,
  "gridApparentPower": 1239,
  "epsBackupPower": 0,
  "pvString1Voltage": 183.7,
  "pvString2Voltage": 217.9,
  "pvString1Current": 5,
  "pvString2Current": 4.8,
  "stateOfCharge": 5,
  "batteryVoltage": 48.2,
  "batteryCurrent": -3.36,
  "gridVoltage": 241,
  "gridFrequency": 50,
  "inverterCurrent": 7.2,
  "epsBackupVoltage": 244.1,
  "epsBackupFrequency": 50.04,
  "inverterHeatsinkTemp": 57.8,
  "chargerTemperature": 60.5,
  "batteryTemperature": 24,
  "pvEnergyTotalKwh": 10870.2,
  "batteryChargeEnergyTotalKwh": 0,
  "batteryDischargeEnergyTotalKwh": 2261.6,
  "gridImportEnergyTotalKwh": 7152.2,
  "gridExportEnergyTotalKwh": 8810.9,
  "consumptionEnergyTotalKwh": 7644.5,
  "batteryThroughputTotalKwh": 13674.6,
  "hoursOfOperation": 18355,
  "pvEnergyTodayKwh": 27.4,
  "pvString1EnergyTodayKwh": 12.7,
  "pvString2EnergyTodayKwh": 14.7,
  "batteryChargeEnergyTodayKwh": 1.2,
  "batteryDischargeEnergyTodayKwh": 2.5,
  "gridImportEnergyTodayKwh": 3.6,
  "gridExportEnergyTodayKwh": 23.3,
  "consumptionEnergyTodayKwh": 8,
  "chargeSlots": [
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    }
  ],
  "dischargeSlots": [
    {
      "start": "16:00",
      "end": "18:30",
      "targetStateOfCharge": 0
    },
    {
      "start": "18:30",
      "end": "19:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    },
    {
      "start": "00:00",
      "end": "00:00",
      "targetStateOfCharge": 0
    }
  ],
  "ecoMode": true,
  "timedExport": true,
  "timedCharge": false,
  "chargeTargetStateOfCharge": 0,
  "batteryReservePercent": 0,
  "chargeRatePercent": 0,
  "dischargeRatePercent": 0,
  "batteryPauseMode": "disabled",
  "timedDischargeSlot": {
    "start": "00:00",
    "end": "00:00"
  },
  "systemTime": "2026-08-11T18:10:17.000Z",
  "powerFlows": {
    "solarToHouse": 517,
    "solarToBattery": 272,
    "solarToGrid": 1190,
    "batteryToHouse": 0,
    "batteryToGrid": 0,
    "gridToHouse": 0,
    "gridToBattery": 0
  },
  "batteries": [],
  "meters": []
}
