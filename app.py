"""Web app entrypoint for Vercel (Flask).

  GET  /              -> the UI (index.html)
  GET  /api/simulate  -> default inputs
  POST /api/simulate  -> JSON report

The simulator itself (crop_simulator.py) is used unchanged.
"""
import os
import sys
import traceback
from dataclasses import asdict

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)  # make crop_simulator importable however the host loads this file

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

try:
    import crop_simulator as cs
    STARTUP_ERROR = None
except Exception as exc:  # shown on the page (and in the logs) instead of a blank 500
    traceback.print_exc()
    cs = None
    STARTUP_ERROR = f"{type(exc).__name__}: {exc}"


app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 20_000  # bytes

MAX_TRIALS = 3000  # keeps a request comfortably inside the function time limit


def build_inputs(payload):
    """Whitelist keys, coerce types and clamp values before handing to the simulator."""
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    inp = cs.Inputs.from_dict(payload)  # rejects unknown keys

    def num(name, lo, hi, cast=float):
        try:
            v = cast(getattr(inp, name))
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a number")
        if not (lo <= v <= hi):
            raise ValueError(f"{name} must be between {lo} and {hi}")
        setattr(inp, name, v)

    # fields the original validate() does not check
    num("adults", 0, 5000, int)
    num("children_5_14", 0, 5000, int)
    num("children_u5", 0, 5000, int)
    num("land_ha", 0.001, 1000)
    num("garden_m2", 0, 1_000_000)
    num("mean_temp_c", 5, 45)
    num("temp_anomaly_c", -5, 8)
    num("season_days", 30, 365, int)
    num("coverage_days", 30, 365, int)
    num("trials", 200, MAX_TRIALS, int)
    num("seed", 0, 2**31 - 1, int)
    if inp.forecast_rain_mm is not None:
        num("forecast_rain_mm", 0, 8000)
    if not isinstance(inp.hist_rain_mm, list) or len(inp.hist_rain_mm) > 60:
        raise ValueError("hist_rain_mm must be a list of at most 60 numbers")
    if not isinstance(inp.conservation, list):
        raise ValueError("conservation must be a list")
    for b in ("mulch", "compost", "windbreak"):
        setattr(inp, b, bool(getattr(inp, b)))
    return inp


def no_store(resp, code=200):
    resp.status_code = code
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.before_request
def check_startup():
    if STARTUP_ERROR:
        return Response("Startup error: " + STARTUP_ERROR + "\n(files in project root: "
                        + ", ".join(sorted(os.listdir(ROOT))) + ")", status=500, mimetype="text/plain")


@app.get("/")
def index():
    if os.path.exists(os.path.join(ROOT, "index.html")):
        return send_from_directory(ROOT, "index.html")
    return Response("index.html not found next to app.py", status=404, mimetype="text/plain")


@app.get("/api/simulate")
def defaults():
    return no_store(jsonify({"defaults": asdict(cs.Inputs()), "max_trials": MAX_TRIALS}))


@app.post("/api/simulate")
def simulate():
    try:
        payload = request.get_json(force=True, silent=False)
        inp = build_inputs(payload)
        full = cs.simulate(inp)
        text = cs.render(full)
        rep = cs.report_for_json(full)
        days = {c.name: c.days for c in cs.CROPS}
        for row in rep["ranking"] + rep["excluded"]:
            row["days"] = days.get(row["name"])
        rep["text_report"] = text
        return no_store(jsonify(rep))
    except HTTPException:
        raise  # let the 400/413 handlers below answer
    except (ValueError, RuntimeError) as e:
        return no_store(jsonify({"error": str(e)}), 400)
    except Exception as e:  # pragma: no cover
        return no_store(jsonify({"error": f"Internal error: {type(e).__name__}"}), 500)


@app.errorhandler(413)
def too_large(_):
    return no_store(jsonify({"error": "Request too large."}), 413)


@app.errorhandler(400)
def bad_request(_):
    return no_store(jsonify({"error": "Request body must be valid JSON."}), 400)


if __name__ == "__main__":
    app.run(port=3000, debug=False)
