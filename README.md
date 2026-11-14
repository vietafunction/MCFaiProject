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
`POST /api/simulate` with any subset of the simulator inputs (`GET /api/simulate` lists names and defaults). Unknown keys are rejected. Limits: `trials` 200-3000, people counts 0-5000, `land_ha` <= 1000, body <= 20 kB. Errors return `{"error": "..."}` with HTTP 400.

## Notes
- Results are deterministic for a given input and `seed`.
- The planting start date defaults to the server date (UTC) when blank.
- All agronomic parameters are approximate. Calibrate with local extension data before relying on results.
- If the app fails at startup, the page shows the error text instead of a generic 500.

## Simple mode
The form opens in **Simple** mode: about 15 plain questions (rain this year, farm location, land size, family, goals, ...). Each answer is translated into the simulator's technical inputs (rainfall mm, temperature, cyclone chance, hectares, etc.) in the browser, with no extra server code or AI. The **Detailed** tab shows and lets you edit the technical values it filled in. The mapping is in `applySimple()` in `index.html`.
