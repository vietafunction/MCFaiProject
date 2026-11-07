# Comoros Crop & Nutrition Season Simulator (Vercel)

A static web UI plus one Python serverless function wrapping `lib/crop_simulator.py` (unchanged, standard library only).

```
crop-sim-vercel/
├── public/index.html      # the UI (no build step, no dependencies)
├── api/simulate.py        # POST /api/simulate -> JSON report; GET -> default inputs
├── lib/crop_simulator.py  # your simulator, untouched
├── vercel.json            # function timeout + bundles lib/ with the function
└── requirements.txt       # empty: stdlib only
```

## Deploy

### Option A: Vercel CLI (fastest)
```bash
npm i -g vercel
cd crop-sim-vercel
vercel          # first run: log in, accept the defaults (no framework, no build command)
vercel --prod   # publish to your production URL
```

### Option B: GitHub + Vercel dashboard
1. Push this folder to a new GitHub repo.
2. On vercel.com choose **Add New → Project**, import the repo.
3. Framework preset: **Other**. Leave build/output settings as they are (`vercel.json` sets the output directory). Deploy.

Every later `git push` redeploys automatically.

## Run locally
```bash
vercel dev      # serves the UI and the Python function together at http://localhost:3000
```
Or test the API alone:
```bash
curl -s -X POST http://localhost:3000/api/simulate -H 'Content-Type: application/json' -d '{"season":"rainy","land_ha":0.8}'
```

## API
`POST /api/simulate` with any subset of the simulator inputs (see `GET /api/simulate` for names and defaults). Unknown keys are rejected. Extra limits added by the API layer: `trials` 200–3000, household counts 0–50, `land_ha` ≤ 1000, request body ≤ 20 kB. Errors come back as `{"error": "..."}` with HTTP 400.

## Notes
- The function has a 30 s limit (`vercel.json`); a default run takes well under a second.
- Results are deterministic for a given input and `seed`.
- The planting start date defaults to the server's date (UTC) when left blank.
- All agronomic parameters are approximate planning values. Calibrate with local extension data before relying on results.
- Anyone with the URL can use it. If that is not wanted, enable **Deployment Protection** in the Vercel project settings.
