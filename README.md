# Comoros Crop & Nutrition Season Simulator (Vercel)

A small Flask app that wraps `crop_simulator.py` (unchanged, standard library only) and serves a web UI.

Five files, all at the top level (no folders):

```
app.py              # Vercel entrypoint: serves the UI and POST /api/simulate
crop_simulator.py   # the simulator, untouched
index.html          # the UI (no build step, no dependencies)
requirements.txt    # flask
vercel.json         # empty config (overwrites any older vercel.json)
```

## Deploy
1. Upload these files to the top level of a GitHub repo (replace any older copies).
2. On vercel.com: Add New > Project, import the repo, Framework Preset = Flask, leave build/output settings empty, Deploy.
Every later push to the repo redeploys automatically.

## Run locally
```bash
pip install -r requirements.txt
python app.py     # http://localhost:3000
```

## API
`POST /api/simulate` with any subset of the simulator inputs (`GET /api/simulate` lists names and defaults). Unknown keys are rejected. Limits: `trials` 200-3000, household counts 0-50, `land_ha` <= 1000, body <= 20 kB. Errors return `{"error": "..."}` with HTTP 400.

## Notes
- Results are deterministic for a given input and `seed`.
- The planting start date defaults to the server date (UTC) when blank.
- All agronomic parameters are approximate. Calibrate with local extension data before relying on results.
- If the app fails at startup, the page shows the error text instead of a generic 500.

## AI explainer
`POST /api/explain` takes the same inputs as `/api/simulate` plus `"language"` (`en`, `fr`, `ar`, `zdj` = Shikomori). The server re-runs the simulation, sends only a compact summary of its results to Claude, and returns a plain-language explanation. The AI never sees free-form user text, so it can only restate the simulator's numbers.

Setup: in Vercel > Project > Settings > Environment Variables add `ANTHROPIC_API_KEY` (optionally `AI_MODEL`, default `claude-sonnet-5-5`), then redeploy. Without the key the rest of the app works and the Explain button shows a "not configured" message.
Note: Shikomori output can contain mistakes; have a native speaker check it before real use.
