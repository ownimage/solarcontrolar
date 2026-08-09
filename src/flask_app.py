import argparse
import os
import json
import logging
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_wtf.csrf import CSRFProtect

app = Flask(
    __name__,
    static_url_path='/solar/static',
    static_folder='static'
)

# ⭐ Tell Flask it lives under /solar
app.config['APPLICATION_ROOT'] = '/solar'
app.logger.setLevel(logging.DEBUG)

csrf = CSRFProtect()
csrf.init_app(app)
app.secret_key = os.urandom(24)

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "settings.json")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config_apply.log")
POWER_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "minute_power.json")

SETTINGS = [
    {
        "key": "timezone",
        "label": "Timezone",
        "type": "string",
        "readonly": True,
        "description": "Timezone used for date/time calculations (determining tomorrow's date, current time)"
    },
    {
        "key": "battery_capacity_kWh",
        "label": "Battery Capacity (kWh)",
        "type": "number",
        "readonly": True,
        "description": "Total battery capacity in kWh, used to compute charge-to percentages"
    },
    {
        "key": "battery_min_kWh",
        "label": "Battery Min (kWh)",
        "type": "number",
        "readonly": True,
        "description": "Minimum safe battery level in kWh (not to discharge below)"
    },
    {
        "key": "solar_forecast_multiplier",
        "label": "Solar Forecast Multiplier",
        "type": "number",
        "readonly": True,
        "description": "Calibration factor applied to Solcast forecast based on historical forecast-vs-actual comparison (calc_error.py)"
    },
    {
        "key": "tolerance_percent",
        "label": "Tolerance (%)",
        "type": "number",
        "readonly": False,
        "description": "Tolerance band (pp) around a target battery level before triggering a state change, avoids flapping",
        "slider": {"min": 0, "max": 5, "step": 0.1}
    },
    {
        "key": "start_discharge_target",
        "label": "Start Discharge Target (%)",
        "type": "number",
        "readonly": False,
        "description": "Battery % target at the start of the evening discharge window (16:00)",
        "slider": {"min": 0, "max": 100, "step": 1}
    },
    {
        "key": "last_30mins_discharge_target",
        "label": "Last 30min Discharge Target (%)",
        "type": "number",
        "readonly": False,
        "description": "Battery % target at 18:30; the discharge target interpolates linearly from start_discharge_target to this value between 16:00–18:30",
        "slider": {"min": 0, "max": 100, "step": 1}
    },
    {
        "key": "holiday_cutoff_kwh",
        "label": "Holiday Cutoff (kWh)",
        "type": "number",
        "readonly": False,
        "description": "Threshold (defined in settings but currently unused in code) — likely intended to detect holiday vs. weekday based on usage levels"
    },
    {
        "key": "min_charge_to_bias_kwh",
        "label": "Min Charge To Bias (kWh)",
        "type": "number",
        "readonly": False,
        "description": "Initial baseline for tracking the minimum battery level needed during daylight hours",
        "slider": {"min": -5, "max": 5, "step": 0.1}
    },
    {
        "key": "max_charge_to_bias_kwh",
        "label": "Max Charge To Bias (kWh)",
        "type": "number",
        "readonly": False,
        "description": "Initial baseline for tracking the maximum battery level reached during daylight hours",
        "slider": {"min": -5, "max": 5, "step": 0.1}
    },
    {
        "key": "usage_multiplier",
        "label": "Usage Multiplier",
        "type": "number",
        "readonly": False,
        "description": "Safety factor applied to historical usage when estimating how much energy is needed",
        "slider": {"min": 0.5, "max": 2, "step": 0.05}
    }
]

def load_settings():
    with open(SETTINGS_FILE, "r") as f:
        return json.load(f)

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_latest_power():
    try:
        if not os.path.exists(POWER_FILE):
            return None, None, None
        with open(POWER_FILE, "r") as f:
            data = json.load(f)
        latest_date = None
        latest_time = None
        latest_data = None
        for date_key in sorted(data.keys(), reverse=True):
            day_data = data[date_key]
            if day_data:
                latest_date = date_key
                latest_time = list(day_data.keys())[-1]
                latest_data = day_data[latest_time]
                break
        return latest_date, latest_time, latest_data
    except Exception:
        return None, None, None

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        settings = load_settings()
        try:
            for field in SETTINGS:
                if field["readonly"]:
                    continue
                key = field["key"]
                value = request.form.get(key)
                if value is None:
                    continue
                if field["type"] == "number":
                    try:
                        value = float(value)
                        if value == int(value) and "." not in request.form.get(key, ""):
                            value = int(value)
                    except ValueError:
                        value = 0
                settings[key] = value
            save_settings(settings)
            flash("Settings saved successfully.")
        except Exception as e:
            flash(f"Error saving settings: {str(e)}", "error")
        return redirect(url_for("index"))

    settings = load_settings()
    config = load_config()
    power_date, power_time, power_data = get_latest_power()
    return render_template("index.html", settings=settings, fields=SETTINGS, config=config, power_date=power_date, power_time=power_time, power_data=power_data)

@app.route("/api/config", methods=["POST"])
def update_config():
    config = load_config()
    try:
        value = request.form.get("charge_to_percentage")
        if value is not None:
            value = int(value)
            config["charge_to_percentage"] = value
        save_config(config)
        flash("Config saved successfully.")
    except Exception as e:
        flash(f"Error saving config: {str(e)}", "error")
    return redirect(url_for("index"))

@app.route("/api/logs")
def api_logs():
    count = request.args.get('count', 200, type=int)
    try:
        if not os.path.exists(LOG_FILE):
            return "Log file not found.", 404
        with open(LOG_FILE, "r", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-count:])
    except Exception as e:
        return f"Error reading log: {str(e)}", 500

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=int, default=5000, help="Port to run the Flask app on")
    args = parser.parse_args()
    app.run(host="0.0.0.0", port=args.port, debug=True)
