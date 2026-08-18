import argparse
import os
import json
import logging

_ACCESS_LOG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "flask_app.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
# The dev server's built-in per-request lines are replaced by the access log
# emitted in log_access() below.
logging.getLogger("werkzeug").setLevel(logging.DEBUG)

import subprocess
import sys
from datetime import datetime
import pytz
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_wtf.csrf import CSRFProtect


app = Flask(__name__, static_folder='static')

# ⭐ Tell Flask it lives under /solar
app.config['APPLICATION_ROOT'] = '/solar'
# Session cookie must apply to all paths (/, /solar/*, /api/*) or it won't
# be sent on POST, leaving the CSRF session token "missing".
app.config['SESSION_COOKIE_PATH'] = '/'
app.logger.setLevel(logging.DEBUG)

_FILE_HANDLER = logging.FileHandler(_ACCESS_LOG)
_FILE_HANDLER.setFormatter(
    logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
)
app.logger.addHandler(_FILE_HANDLER)
app.logger.info("flask_app started, access logging enabled")



@app.after_request
def log_access(response):
    log_time = datetime.now(pytz.timezone("Europe/London")).strftime("%d/%b/%Y:%H:%M:%S %z")
    client_ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "-").split(",")[0].strip()
    request_line = f"{request.method} {request.full_path.rstrip('?')} {request.environ.get('SERVER_PROTOCOL', 'HTTP/1.1')}"
    content_length = response.content_length if response.content_length is not None else "-"
    app.logger.info(f'{client_ip} - - [{log_time}] "{request_line}" {response.status_code} {content_length}')
    return response

class PrefixMiddleware:
    """Make the app prefix-aware so it works behind the Traefik proxy.

    Sets SCRIPT_NAME so url_for generates /solar/... links, and strips the
    /solar prefix from incoming paths so Flask's routes still match. Uses the
    X-Forwarded-Prefix header when the proxy sends one, otherwise /solar.
    """

    def __init__(self, wsgi_app, prefix="/solar"):
        self.wsgi_app = wsgi_app
        self.prefix = prefix.rstrip("/")

    def __call__(self, environ, start_response):
        script_name = self.prefix
        forwarded = environ.get("HTTP_X_FORWARDED_PREFIX", "").strip().rstrip("/")
        if forwarded:
            script_name = forwarded
        if script_name:
            environ["SCRIPT_NAME"] = script_name
            path_info = environ.get("PATH_INFO", "")
            if path_info == script_name:
                environ["PATH_INFO"] = "/"
            elif path_info.startswith(script_name + "/"):
                environ["PATH_INFO"] = path_info[len(script_name):]
        return self.wsgi_app(environ, start_response)


app.wsgi_app = PrefixMiddleware(app.wsgi_app, "/solar")


csrf = CSRFProtect()
csrf.init_app(app)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))


def _load_secret_key():
    key_file = os.path.join(BASE_DIR, ".secret_key")
    try:
        with open(key_file, "r") as f:
            key = f.read().strip()
            if key:
                return key
    except FileNotFoundError:
        pass
    key = os.urandom(24).hex()
    try:
        with open(key_file, "w") as f:
            f.write(key)
    except Exception:
        pass
    return key


app.secret_key = _load_secret_key()

SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
POWER_FILE = os.path.join(BASE_DIR, "minute_power.json")
FORECAST_SCRIPT = os.path.join(BASE_DIR, "src", "forecast_pipeline.py")

FILES = {
    "config_apply": os.path.join(BASE_DIR, "config_apply.log"),
    "minute_poller": os.path.join(BASE_DIR, "minute_poller.log"),
    "forecast_pipeline": os.path.join(BASE_DIR, "forecast_pipeline.log"),
    "minute_poller_state": os.path.join(BASE_DIR, "minute_poller_state.json"),
    "minute_power": os.path.join(BASE_DIR, "minute_power.json"),
    "minute_totals": os.path.join(BASE_DIR, "minute_totals.json"),
    "solar_actuals": os.path.join(BASE_DIR, "solar_actuals.json"),
    "usage_actuals": os.path.join(BASE_DIR, "usage_actuals.json"),
}

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
    },
    {
        "key": "forecast_error_window",
        "label": "Forecast Error Window (days)",
        "type": "number",
        "readonly": False,
        "description": "Number of days that the solar forecast and history are compared to generate the solar_forecast_multiplier",
        "slider": {"min": 1, "max": 14, "step": 1}
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

def _render_index(forecast_output=None, forecast_status="not_run"):
    settings = load_settings()
    config = load_config()
    power_date, power_time, power_data = get_latest_power()
    server_timestamp = datetime.now(pytz.timezone("Europe/London")).strftime("%Y-%m-%dT%H:%M:%S")
    return render_template("index.html", settings=settings, fields=SETTINGS, config=config,
                           power_date=power_date, power_time=power_time, power_data=power_data,
                           server_timestamp=server_timestamp, forecast_output=forecast_output,
                           forecast_status=forecast_status)

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

    return _render_index()

@app.route("/api/run_forecast", methods=["POST"])
def run_forecast():
    output = ""
    try:
        result = subprocess.run(
            [sys.executable, FORECAST_SCRIPT],
            capture_output=True,
            text=True,
            cwd=BASE_DIR,
            timeout=180
        )
        output = result.stdout + result.stderr
        if result.returncode == 0:
            flash("Forecast pipeline completed.")
        else:
            flash(f"Forecast pipeline exited with code {result.returncode}.", "error")
    except subprocess.TimeoutExpired as e:
        output = f"Forecast pipeline timed out after 180 seconds.\n\n{e.stdout}{e.stderr}"
        flash("Forecast pipeline timed out after 180 seconds.", "error")
    except Exception as e:
        output = str(e)
        flash(f"Error running forecast pipeline: {e}", "error")
    return _render_index(forecast_output=output, forecast_status="ran")

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

@app.route("/api/power_data")
def api_power_data():
    date_param = request.args.get("date", '', type=str)
    try:
        data = json.loads(open(POWER_FILE, "r").read())
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify({"dates": []}) if not date_param else (jsonify({"error": f"Power data file not found: {POWER_FILE}"}), 404)

    dates = sorted(data.keys(), reverse=True)

    if not date_param:
        return jsonify({"dates": dates})

    if date_param not in data:
        return jsonify({"error": f"No data for date: {date_param}"}), 404

    day = data[date_param]
    times = list(day.keys())
    return jsonify({
        "date": date_param,
        "times": times,
        "solar": [day[t].get("solar") for t in times],
        "grid": [day[t].get("grid") for t in times],
        "home": [day[t].get("home") for t in times],
        "battery": [day[t].get("battery") for t in times],
        "battery_level": [day[t].get("battery_level") for t in times],
    })

@app.route("/api/files")
def api_files():
    file = request.args.get('file', 'config_apply', type=str)
    if file not in FILES:
        return f"Unknown file: {file}.", 400
    file_path = FILES[file]
    count = request.args.get('count', 200, type=int)
    try:
        if not os.path.exists(file_path):
            return "File not found.", 404
        with open(file_path, "r", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-count:])
    except Exception as e:
        return f"Error reading file: {str(e)}", 500

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=int, default=5000, help="Port to run the Flask app on")
    args = parser.parse_args()
    app.run(host="0.0.0.0", port=args.port, use_reloader=False)
