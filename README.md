# Comoros Crop & Nutrition Season Simulator (Vercel)

A small Flask app that wraps `lib/crop_simulator.py` (unchanged, standard library only) and serves a web UI.

```
crop-sim-vercel/
├── app.py                 # Vercel entrypoint: serves the UI and POST /api/simulate
├── public/index.html      # the UI (no build step, no dependencies)
├── lib/crop_simulator.py  # your simulator, untouched
└── requirements.txt       # flask
```

## Deploy

### GitHub + Vercel dashboard
1. Put the *contents* of this folder at the top level of a new GitHub repo (`app.py` must be in the repo root, not inside a subfolder).
2. On vercel.com: **Add New → Project**, import the repo.
3. Leave **Framework Preset** on auto-detect (it should show **Flask**). If it says "Other", change it to **Flask**. Leave build and output settings empty. Deploy.

### Vercel CLI
```bash
npm i -g vercel
cd crop-sim-vercel
vercel --prod
```

## Run locally
```bash
pip install -r requirements.txt
python app.py          # http://localhost:3000
```

## API
`POST /api/simulate` with any subset of the simulator inputs (`GET /api/simulate` returns the names and defaults). Unknown keys are rejected. Limits added by the API layer: `trials` 200–3000, household counts 0–50, `land_ha` ≤ 1000, request body ≤ 20 kB. Errors come back as `{"error": "..."}` with HTTP 400.

## Notes
- Results are deterministic for a given input and `seed`.
- The planting start date defaults to the server's date (UTC) when left blank.
- All agronomic parameters are approximate planning values. Calibrate with local extension data before relying on results.
- Anyone with the URL can use it. To restrict access, enable **Deployment Protection** in the Vercel project settings.
