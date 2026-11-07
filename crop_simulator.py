#!/usr/bin/env python3
"""
CR-CNI Crop & Nutrition Season Simulator  (Comoros)
===================================================

Takes a household's / village's situation (rainfall forecast, rainfall history,
temperature, cyclone risk, land, slope, soil, labour, household size, goals)
and runs a Monte Carlo simulation of the coming season to produce:

  1.  Best crops this season (ranked, with yield, bad-season yield, failure risk)
  2.  "Best for ..." quick picks (nutrition, income, drought safety, soil, speed)
  3.  A recommended planting plan (land split + planting / first-harvest dates)
  4.  Expected nutrition coverage (energy, iron, vitamin A, protein) incl. a bad season
  5.  Food-gap days, food-security rating, expected income
  6.  Child (under-5) nutrition risk
  7.  Risk dashboard (drought, excess rain, cyclone)
  8.  Soil-erosion estimate and rating
  9.  Water plan (rainwater-tank sizing for a nutrition garden)
 10.  Agroforestry / tree recommendations (and windbreak advice)
 11.  Rainfall stress test (what happens if the season is 50% .. 150% of normal)
 12.  Climate-resilience index (0-100)
 13.  Plain-language alerts and recommendations
 14.  Which crops were excluded and why

IMPORTANT: every agronomic number below (rain ranges, yields, prices, nutrient
contents, erosion constants) is an approximate, literature-style value meant for
a planning *prototype*. Calibrate them with local extension-service data before
using results for real decisions.

Usage
-----
  python crop_simulator.py                 # interactive questions (Enter = default)
  python crop_simulator.py --demo          # run with the built-in example inputs
  python crop_simulator.py --config in.json [--json-out report.json]
  python crop_simulator.py --write-example-config in.json

Only the Python standard library is needed (Python 3.8+).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
NUTR = ("kcal", "iron", "vita", "protein")
NUTR_LABEL = {"kcal": "Energy", "iron": "Iron", "vita": "Vitamin A", "protein": "Protein"}

SLOPE_LS = {"flat": 0.4, "gentle": 1.0, "moderate": 2.5, "steep": 5.0}
FERTILITY = {"low": 0.70, "medium": 0.88, "high": 1.0}
LABOR_CAPACITY = {"low": 0.35, "medium": 0.60, "high": 0.85}
PRACTICE_P = {"contour": 0.6, "terraces": 0.35, "agroforestry": 0.7}

# Approximate daily needs per person (plant-based diets absorb less iron, so
# iron targets are set on the high side).
NEEDS_PER_DAY = {
    "adult": {"kcal": 2200, "iron": 18, "vita": 600, "protein": 55},
    "c514": {"kcal": 1800, "iron": 12, "vita": 500, "protein": 40},
    "cu5": {"kcal": 1200, "iron": 10, "vita": 400, "protein": 15},
}

WEIGHTS = {
    "nutrition": dict(nutrition=.40, resilience=.20, income=.10, erosion=.10, speed=.10, labor=.10),
    "income": dict(income=.40, resilience=.20, nutrition=.15, erosion=.05, speed=.10, labor=.10),
    "resilience": dict(resilience=.40, erosion=.20, nutrition=.20, income=.05, speed=.05, labor=.10),
    "balanced": dict(nutrition=.28, resilience=.25, income=.17, erosion=.10, speed=.10, labor=.10),
    "fast_food": dict(speed=.40, nutrition=.20, resilience=.20, income=.05, erosion=.05, labor=.10),
}

GROUP_STAPLE = {"roots_tubers", "cereals"}
GROUP_LEGUME = {"legumes", "nuts_seeds"}
GROUP_VIT = {"vit_a", "leafy_veg"}


# --------------------------------------------------------------------------
# Crop and tree databases
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Crop:
    name: str
    seasons: tuple          # seasons it is normally grown in: "rainy" / "dry"
    rain: tuple             # (min, opt_low, opt_high, max) seasonal rainfall in mm
    temp_hi: float          # temperature (C) above which heat stress starts
    heat_sens: float        # 0..1 sensitivity to heat
    yield_t_ha: float       # realistic smallholder potential yield (t/ha, edible product)
    days: int               # days from planting to first harvest
    price: float            # USD per kg (local market, rough)
    kcal: float             # per kg edible product
    iron: float             # mg per kg
    vita: float             # micrograms RAE per kg
    protein: float          # g per kg
    cover: float            # 0..1 ground cover (protects soil)
    cyclone_vuln: float     # 0..1 fraction of yield lost if a cyclone hits
    fert_sens: float        # 0..1 how much poor soil hurts it
    labor: float            # 0..1 labour intensity
    storability: float      # 0..1 how well the harvest keeps
    group: str
    n_fixer: bool = False
    tip: str = ""


CROPS = [
    Crop("Cassava", ("rainy", "dry"), (350, 600, 1500, 2500), 32, .10, 8.0, 300, .30,
         1600, 3, 0, 14, .45, .20, .30, .50, .70, "roots_tubers",
         tip="Plant cuttings at rain onset; leave in the ground as a famine reserve."),
    Crop("Banana", ("rainy",), (800, 1200, 2200, 3500), 33, .20, 10.0, 330, .25,
         890, 3, 30, 11, .85, .70, .60, .40, .30, "roots_tubers",
         tip="Plant suckers on gentle slopes or in mulched pits; prop stems before cyclone season."),
    Crop("Orange-fleshed sweet potato", ("rainy", "dry"), (300, 450, 1000, 1800), 32, .25, 8.0, 120, .35,
         860, 6, 7000, 16, .80, .15, .30, .50, .40, "vit_a",
         tip="Plant vine cuttings on ridges; the leaves are also edible. Best vitamin A crop for children."),
    Crop("Maize", ("rainy",), (350, 500, 900, 1500), 33, .50, 1.5, 110, .50,
         3650, 27, 0, 94, .35, .50, .80, .50, .90, "cereals",
         tip="Needs decent soil; intercrop with beans to build fertility."),
    Crop("Upland rice", ("rainy",), (600, 800, 1600, 2800), 33, .40, 1.5, 130, .90,
         3600, 8, 0, 70, .40, .40, .60, .80, .95, "cereals",
         tip="Labour heavy; best where land is flat or terraced."),
    Crop("Taro", ("rainy",), (900, 1300, 2600, 4000), 32, .20, 6.0, 240, .40,
         1120, 6, 40, 15, .75, .15, .50, .60, .50, "roots_tubers",
         tip="Thrives in wet, shaded spots; good under tree cover."),
    Crop("Common beans", ("rainy", "dry"), (250, 350, 600, 1000), 28, .70, 0.8, 90, 1.20,
         3400, 60, 0, 215, .50, .40, .60, .50, .90, "legumes", True,
         tip="Fixes nitrogen; intercrop with cassava or maize. Rich in iron and protein."),
    Crop("Pigeon pea", ("rainy", "dry"), (300, 500, 1000, 1800), 34, .15, 0.8, 150, 1.00,
         3430, 52, 5, 217, .60, .30, .30, .40, .90, "legumes", True,
         tip="Very drought tolerant; deep roots, good on poor soil and slopes."),
    Crop("Groundnut", ("rainy",), (400, 500, 800, 1300), 32, .40, 1.0, 110, 1.30,
         5670, 46, 0, 258, .55, .30, .50, .70, .70, "nuts_seeds", True,
         tip="Dry well and store airtight to avoid aflatoxin mould."),
    Crop("Amaranth leaves", ("rainy", "dry"), (200, 300, 600, 1300), 32, .30, 8.0, 45, .50,
         230, 27, 4690, 29, .80, .30, .70, .60, .05, "leafy_veg",
         tip="Sow in successions every 3 weeks; cut-and-come-again. Cheap micronutrient source."),
    Crop("Moringa leaves", ("rainy", "dry"), (250, 500, 1500, 2500), 36, .10, 6.0, 90, .50,
         640, 8, 4700, 94, .60, .35, .20, .40, .10, "leafy_veg",
         tip="Fast to first leaf harvest; also works as a living fence and agroforestry tree."),
    Crop("Tomato", ("rainy", "dry"), (300, 450, 700, 1100), 29, .70, 12.0, 100, .80,
         180, 3, 420, 9, .50, .60, .90, .90, .10, "other_fruit_veg",
         tip="Stake plants and mulch; avoid waterlogged beds (disease)."),
    Crop("Carrot", ("dry",), (250, 350, 600, 900), 26, .80, 10.0, 100, .70,
         410, 3, 8350, 9, .40, .30, .80, .70, .50, "vit_a",
         tip="Cool dry season crop on loose soil; needs steady watering."),
    Crop("Papaya", ("rainy", "dry"), (900, 1200, 2000, 3000), 33, .20, 15.0, 270, .40,
         430, 3, 470, 5, .55, .65, .60, .40, .10, "vit_a",
         tip="Fast-fruiting tree crop; plant in well-drained spots, away from standing water."),
]


@dataclass(frozen=True)
class Tree:
    name: str
    rain: tuple             # annual rainfall (min, opt_low, opt_high, max) mm
    cyclone_tol: float      # 0..1
    years_to_fruit: float
    nutrition: float        # 0..1 value for household nutrition
    income: float           # 0..1 value for income
    erosion: float          # 0..1 soil protection on slopes
    role: str


TREES = [
    Tree("Moringa", (300, 600, 2000, 3000), .6, 0.5, 1.0, .4, .5,
         "Iron/vitamin A/protein-rich leaves within months; live fence"),
    Tree("Papaya", (900, 1200, 2000, 3000), .35, 1.0, .8, .5, .3,
         "Vitamin A fruit within a year; short-lived, plant in clusters"),
    Tree("Mango", (600, 900, 2000, 3000), .5, 4.0, .7, .6, .6,
         "Vitamin A and C fruit, shade, strong roots on slopes"),
    Tree("Breadfruit", (1000, 1500, 2500, 4000), .6, 4.0, .8, .4, .7,
         "Starchy staple; deep roots stabilise steep ground; shade for taro/ginger"),
    Tree("Coconut", (900, 1400, 2500, 3500), .85, 6.0, .5, .7, .5,
         "Best cyclone resistance; windbreak, oil and income"),
    Tree("Clove", (1500, 2000, 3000, 4000), .4, 7.0, .1, .9, .6,
         "Traditional cash tree for humid uplands; slow to start"),
    Tree("Vanilla (on support trees)", (1500, 2000, 2800, 3800), .3, 3.0, .1, 1.0, .2,
         "High-value cash crop; needs shade/support trees and careful curing"),
]


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------
@dataclass
class Inputs:
    season: str = "rainy"                      # rainy | dry
    start_date: str = ""                       # ISO date, blank = today
    season_days: int = 180
    forecast_rain_mm: float | None = 1100.0    # seasonal total; None = use history only
    forecast_confidence: float = 0.6           # 0..1 trust in the forecast
    hist_rain_mm: list = field(default_factory=lambda: [980, 1240, 870, 1350, 760, 1100, 1020, 690, 1180, 820])
    mean_temp_c: float = 27.0
    temp_anomaly_c: float = 0.5                # expected warming vs normal this season
    cyclone_prob: float = 0.20                 # chance of a damaging storm this season
    land_ha: float = 0.6
    slope: str = "moderate"                    # flat | gentle | moderate | steep
    soil_fertility: str = "medium"             # low | medium | high
    labor: str = "medium"                      # low | medium | high
    adults: int = 2
    children_5_14: int = 2
    children_u5: int = 2
    priority: str = "nutrition"                # nutrition | income | resilience | balanced | fast_food
    sell_fraction: float = 0.30                # share of harvest sold rather than eaten
    irrigation_mm: float = 0.0                 # extra water available (mm over the season)
    mulch: bool = True
    compost: bool = False
    windbreak: bool = False
    conservation: list = field(default_factory=list)   # contour, terraces, agroforestry
    garden_m2: float = 200.0
    coverage_days: int = 180                   # days of household food one season's harvest should cover
    trials: int = 2000
    seed: int = 42

    @classmethod
    def from_dict(cls, d):
        base = cls()
        for k, v in d.items():
            if not hasattr(base, k):
                raise ValueError(f"Unknown input '{k}'. Valid inputs: {', '.join(asdict(base))}")
            setattr(base, k, v)
        return base

    def validate(self):
        def choice(name, value, options):
            v = str(value).strip().lower()
            if v not in options:
                raise ValueError(f"{name} must be one of {sorted(options)} (got '{value}')")
            return v

        self.season = choice("season", self.season, ("rainy", "dry"))
        self.slope = choice("slope", self.slope, SLOPE_LS)
        self.soil_fertility = choice("soil_fertility", self.soil_fertility, FERTILITY)
        self.labor = choice("labor", self.labor, LABOR_CAPACITY)
        self.priority = choice("priority", self.priority, WEIGHTS)
        self.conservation = [choice("conservation", c, PRACTICE_P) for c in (self.conservation or [])]
        self.hist_rain_mm = [float(x) for x in (self.hist_rain_mm or [])]
        if any(x < 0 for x in self.hist_rain_mm):
            raise ValueError("hist_rain_mm values must be >= 0")
        if self.forecast_rain_mm is not None:
            self.forecast_rain_mm = float(self.forecast_rain_mm)
            if self.forecast_rain_mm < 0:
                raise ValueError("forecast_rain_mm must be >= 0")
        if self.forecast_rain_mm is None and not any(x > 0 for x in self.hist_rain_mm):
            raise ValueError("Provide a rainfall forecast, a rainfall history, or both.")
        if self.land_ha <= 0:
            raise ValueError("land_ha must be > 0")
        if self.adults + self.children_5_14 + self.children_u5 <= 0:
            raise ValueError("The household needs at least one person.")
        self.forecast_confidence = min(1.0, max(0.0, float(self.forecast_confidence)))
        self.cyclone_prob = min(1.0, max(0.0, float(self.cyclone_prob)))
        self.sell_fraction = min(1.0, max(0.0, float(self.sell_fraction)))
        self.irrigation_mm = max(0.0, float(self.irrigation_mm))
        self.trials = max(200, int(self.trials))
        self.season_days = max(30, int(self.season_days))
        self.coverage_days = max(30, int(self.coverage_days))
        if self.start_date:
            date.fromisoformat(self.start_date)  # raises ValueError if malformed


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def pct(values, p):
    s = sorted(values)
    k = (len(s) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)


def trapezoid(x, lo, opt_lo, opt_hi, hi):
    """1.0 inside the optimum, falls to 0 below `lo`, and to a 5% floor above `hi`."""
    if x <= lo:
        return 0.0
    if x < opt_lo:
        return (x - lo) / (opt_lo - lo)
    if x <= opt_hi:
        return 1.0
    if x >= hi:
        return 0.05
    return 0.05 + 0.95 * (hi - x) / (hi - opt_hi)


def postharvest_loss(crop):
    return 0.25 - 0.17 * crop.storability


def lognorm_params(mean, sd):
    s2 = math.log(1 + (sd / mean) ** 2)
    return math.log(mean) - s2 / 2, math.sqrt(s2)


def cap_shares(raw, cap=0.40, floor=0.08):
    n = len(raw)
    cap = max(cap, 1.0 / n) + 1e-9
    total = sum(raw)
    s = [x / total for x in raw]
    for _ in range(100):
        s = [min(cap, max(floor, x)) for x in s]
        t = sum(s)
        s = [x / t for x in s]
        if all(floor - 1e-6 <= x <= cap + 1e-6 for x in s):
            break
    return s


# --------------------------------------------------------------------------
# Climate model
# --------------------------------------------------------------------------
def rainfall_model(inp):
    """Blend forecast and (trend-adjusted) history into a seasonal rainfall distribution."""
    h = inp.hist_rain_mm
    n = len(h)
    hm = hsd = hist_ref = None
    trend_pct = 0.0
    if n >= 1 and statistics.mean(h) > 0:
        hm = statistics.mean(h)
        hsd = statistics.stdev(h) if n >= 3 else 0.25 * hm
        hist_ref = hm
        if n >= 6:  # least-squares trend, applied at half weight and capped (+/-25%)
            xb = (n - 1) / 2
            sxx = sum((i - xb) ** 2 for i in range(n))
            slope = sum((i - xb) * (y - hm) for i, y in enumerate(h)) / sxx
            trend_pct = slope * 10 / hm * 100
            proj = hm + slope * (n - xb)
            adj = max(-0.25 * hm, min(0.25 * hm, proj - hm))
            hist_ref = hm + 0.5 * adj
    fc = inp.forecast_rain_mm
    w = 0.0 if fc is None else min(0.85, inp.forecast_confidence * 0.85)
    if hist_ref is None:
        mean, sd = fc, 0.25 * fc
    elif fc is None:
        mean, sd = hist_ref, hsd
    else:
        mean = w * fc + (1 - w) * hist_ref
        sd = hsd * (1 - 0.5 * w)
    sd = max(sd, 0.10 * mean)
    if mean <= 0:
        raise ValueError("Expected rainfall must be above zero.")
    return {"mean": mean, "sd": sd, "hist_mean": hm, "hist_sd": hsd, "hist_ref": hist_ref,
            "trend_pct_per_decade": trend_pct, "forecast_weight": w}


def water_factor(crop, rain, inp):
    eff = rain + inp.irrigation_mm
    if inp.mulch and rain < crop.rain[2]:
        eff += 0.12 * rain  # mulch conserves soil moisture when water is limiting
    return trapezoid(eff, *crop.rain)


def temp_factor(crop, temp):
    return max(0.2, 1 - crop.heat_sens * 0.12 * max(0.0, temp - crop.temp_hi))


def fert_factor(crop, inp):
    f = min(1.0, FERTILITY[inp.soil_fertility] + (0.08 if inp.compost else 0.0))
    return 1 - crop.fert_sens * (1 - f)


def det_yield(crop, rain, inp):
    """Deterministic yield (kg/ha) at a given seasonal rainfall (no storms, no noise)."""
    return (crop.yield_t_ha * 1000 * water_factor(crop, rain, inp)
            * temp_factor(crop, inp.mean_temp_c + inp.temp_anomaly_c) * fert_factor(crop, inp))


def practice_factor(inp):
    p = 1.0
    for c in inp.conservation:
        p *= PRACTICE_P[c]
    if inp.mulch:
        p *= 0.8
    return p


def household_needs(inp):
    return {k: inp.coverage_days * (inp.adults * NEEDS_PER_DAY["adult"][k]
                                    + inp.children_5_14 * NEEDS_PER_DAY["c514"][k]
                                    + inp.children_u5 * NEEDS_PER_DAY["cu5"][k]) for k in NUTR}


def simulate_crop(crop, draws, inp, rng):
    base = crop.yield_t_ha * 1000
    ff = fert_factor(crop, inp)
    storm_loss = crop.cyclone_vuln * (1 - (0.3 if inp.windbreak else 0.0))
    ys, wfs = [], []
    for rain, anom, cyc in zip(draws["rain"], draws["anom"], draws["cyc"]):
        wf = water_factor(crop, rain, inp)
        tf = temp_factor(crop, inp.mean_temp_c + anom)
        cy = (1 - storm_loss) if cyc else 1.0
        noise = max(0.5, rng.gauss(1.0, 0.10))  # pests, management, local variation
        ys.append(base * wf * tf * ff * cy * noise)
        wfs.append(wf)
    return ys, wfs


# --------------------------------------------------------------------------
# Portfolio logic
# --------------------------------------------------------------------------
def build_portfolio(ranked, max_crops=5):
    chosen = []
    top = ranked[0]["score"]

    def best(groups):
        for r in ranked:
            if r["crop"].group in groups and r not in chosen and r["score"] >= 0.5 * top:
                return r
        return None

    for g in (GROUP_STAPLE, GROUP_LEGUME, GROUP_VIT):  # staple + protein/iron + vitamin A
        r = best(g)
        if r:
            chosen.append(r)
    for r in ranked:
        if len(chosen) >= max_crops:
            break
        if r not in chosen:
            chosen.append(r)
    chosen = chosen[:max_crops]
    shares = cap_shares([r["score"] ** 1.5 for r in chosen])
    return chosen, shares


def portfolio_mc(items, yields, inp, needs):
    """items = [(crop, area_ha)] ; shares the same weather draws across crops."""
    n = len(next(iter(yields.values())))
    cov = {k: [] for k in NUTR}
    overall, income = [], []
    for t in range(n):
        tot = dict.fromkeys(NUTR, 0.0)
        inc = 0.0
        for crop, area in items:
            edible = yields[crop.name][t] * (1 - postharvest_loss(crop))
            eat = edible * (1 - inp.sell_fraction)
            for k in NUTR:
                tot[k] += area * eat * getattr(crop, k)
            inc += area * edible * inp.sell_fraction * crop.price
        caps = {k: min(1.0, tot[k] / needs[k]) for k in NUTR}
        for k in NUTR:
            cov[k].append(caps[k])
        overall.append(statistics.mean(caps.values()))
        income.append(inc)
    return cov, overall, income


def portfolio_det(items, rain, inp, needs):
    tot = dict.fromkeys(NUTR, 0.0)
    for crop, area in items:
        eat = det_yield(crop, rain, inp) * (1 - postharvest_loss(crop)) * (1 - inp.sell_fraction)
        for k in NUTR:
            tot[k] += area * eat * getattr(crop, k)
    return {k: min(1.0, tot[k] / needs[k]) for k in NUTR}


def best_crop_det(rain, candidates, inp):
    vals = {c.name: {k: det_yield(c, rain, inp) * (1 - postharvest_loss(c)) * getattr(c, k) for k in NUTR}
            for c in candidates}
    mx = {k: max(v[k] for v in vals.values()) or 1.0 for k in NUTR}
    idx = {n: statistics.mean(v[k] / mx[k] for k in NUTR) for n, v in vals.items()}
    name = max(idx, key=idx.get)
    return name if idx[name] > 0.01 else "none viable"


def soil_rating(t_ha):
    if t_ha < 5:
        return "Low (within tolerable limits)"
    if t_ha < 12:
        return "Moderate"
    if t_ha < 25:
        return "High"
    return "Severe"


# --------------------------------------------------------------------------
# The simulation
# --------------------------------------------------------------------------
def simulate(inp):
    inp.validate()
    rng = random.Random(inp.seed)
    rm = rainfall_model(inp)
    n = inp.trials
    mu, sg = lognorm_params(rm["mean"], rm["sd"])

    cycs = [rng.random() < inp.cyclone_prob for _ in range(n)]
    rains = [rng.lognormvariate(mu, sg) * (1.2 if c else 1.0) for c in cycs]  # storms add rain
    anoms = [rng.gauss(inp.temp_anomaly_c, 0.6) for _ in range(n)]
    draws = {"rain": rains, "anom": anoms, "cyc": cycs}

    start = date.fromisoformat(inp.start_date) if inp.start_date else date.today()
    ls = SLOPE_LS[inp.slope]
    pfac = practice_factor(inp)
    rain_term = statistics.mean(r ** 1.3 for r in rains)
    needs = household_needs(inp)
    ref_rain = rm["hist_ref"] or rm["mean"]

    # ---- per-crop Monte Carlo -------------------------------------------
    results, yields = [], {}
    for crop in CROPS:
        ys, wfs = simulate_crop(crop, draws, inp, rng)
        yields[crop.name] = ys
        potential = crop.yield_t_ha * 1000
        loss = postharvest_loss(crop)
        mean_y = statistics.mean(ys)
        edible = mean_y * (1 - loss)
        c_factor = 1 - 0.9 * crop.cover
        soil_loss = 0.0006 * rain_term * ls * c_factor * pfac
        r = {
            "crop": crop, "name": crop.name, "mean_yield_kg_ha": mean_y,
            "p10_yield_kg_ha": pct(ys, 10), "p90_yield_kg_ha": pct(ys, 90), "potential_kg_ha": potential,
            "fail_prob": sum(1 for y in ys if y < 0.35 * potential) / n,
            "mean_wf": statistics.mean(wfs), "income_ha": edible * crop.price, "soil_loss_t_ha": soil_loss,
            "excluded": None,
        }
        for k in NUTR:
            r[k + "_ha"] = edible * getattr(crop, k)
        if inp.season not in crop.seasons:
            r["excluded"] = f"not normally grown in the {inp.season} season"
        elif r["mean_wf"] < 0.15:
            r["excluded"] = ("too dry - needs irrigation or rainwater harvesting"
                             if rm["mean"] < crop.rain[1] else "too wet - waterlogging risk")
        results.append(r)

    elig = [r for r in results if not r["excluded"]]
    if not elig:
        raise RuntimeError("No crop is viable with these inputs. Add irrigation or check the rainfall figures.")

    mx = {k: (max(r[k + "_ha"] for r in elig) or 1.0) for k in NUTR}
    mx_inc = max(r["income_ha"] for r in elig) or 1.0
    wts = WEIGHTS[inp.priority]
    lab_cap = LABOR_CAPACITY[inp.labor]
    for r in elig:
        c = r["crop"]
        r["nutrition_idx"] = statistics.mean(r[k + "_ha"] / mx[k] for k in NUTR)
        r["income_idx"] = r["income_ha"] / mx_inc
        r["resilience_idx"] = max(0.0, min(1.0, 0.5 * (1 - r["fail_prob"]) + 0.5 * r["p10_yield_kg_ha"] / r["potential_kg_ha"]))
        r["erosion_idx"] = 1 - min(1.0, r["soil_loss_t_ha"] / 25.0)
        r["speed_idx"] = 1 - min(c.days, 365) / 365.0
        r["labor_idx"] = 1.0 if c.labor <= lab_cap else max(0.0, 1 - (c.labor - lab_cap) * 2)
        score = sum(wts[k] * r[k + "_idx"] for k in wts)
        if c.n_fixer and inp.soil_fertility != "high":
            score += 0.03  # soil-building bonus
        r["score"] = score
    ranked = sorted(elig, key=lambda r: r["score"], reverse=True)

    quick = {
        "Best for nutrition": max(elig, key=lambda r: r["nutrition_idx"]),
        "Best for income": max(elig, key=lambda r: r["income_idx"]),
        "Safest in a bad season": max(elig, key=lambda r: r["resilience_idx"]),
        "Best soil protection": max(elig, key=lambda r: r["erosion_idx"]),
        "Fastest food": max(elig, key=lambda r: r["speed_idx"]),
    }

    # ---- portfolio -------------------------------------------------------
    chosen, shares = build_portfolio(ranked)
    items = [(r["crop"], inp.land_ha * s) for r, s in zip(chosen, shares)]
    cov, overall, income = portfolio_mc(items, yields, inp, needs)
    cov_mean = {k: statistics.mean(cov[k]) for k in NUTR}
    cov_p10 = {k: pct(cov[k], 10) for k in NUTR}
    kcal_gap_mean = (1 - cov_mean["kcal"]) * inp.coverage_days
    kcal_gap_bad = (1 - cov_p10["kcal"]) * inp.coverage_days
    p_kcal_short = sum(1 for v in cov["kcal"] if v < 0.8) / n

    if cov_p10["kcal"] >= 0.9:
        food_rating = "Secure"
    elif cov_mean["kcal"] >= 0.9 and cov_p10["kcal"] >= 0.6:
        food_rating = "Watch - vulnerable in a bad season"
    elif cov_mean["kcal"] >= 0.6:
        food_rating = "At risk"
    else:
        food_rating = "Critical"

    # monoculture comparison (best single crop on all the land)
    mono = ranked[0]
    m_cov, m_overall, m_income = portfolio_mc([(mono["crop"], inp.land_ha)], yields, inp, needs)
    mono_p10_overall = pct(m_overall, 10)
    port_p10_overall = pct(overall, 10)

    groups = sorted({c.group for c, _ in items})
    micro_p10 = min(cov_p10["iron"], cov_p10["vita"], cov_p10["protein"])
    levels = ["Low", "Moderate", "High", "Severe"]
    lvl = 0 if micro_p10 >= 0.85 else 1 if micro_p10 >= 0.6 else 2 if micro_p10 >= 0.35 else 3
    if len(groups) < 4:
        lvl = min(3, lvl + 1)
    child_risk = levels[lvl]

    # ---- risks -------------------------------------------------------------
    risk = {
        "drought_prob": sum(1 for r in rains if r < 0.75 * ref_rain) / n,
        "excess_prob": sum(1 for r in rains if r > 1.35 * ref_rain) / n,
        "cyclone_prob": inp.cyclone_prob,
        "any_adverse_prob": sum(1 for r, c in zip(rains, cycs) if c or r < 0.75 * ref_rain or r > 1.35 * ref_rain) / n,
    }

    # ---- soil & water ------------------------------------------------------
    port_soil = sum(s * r["soil_loss_t_ha"] for r, s in zip(chosen, shares))
    bare_soil = 0.0006 * rain_term * ls * 1.0 * pfac
    rain_p10 = pct(rains, 10)
    deficits = []
    for r, s in zip(chosen, shares):
        c = r["crop"]
        eff = rain_p10 + inp.irrigation_mm + (0.12 * rain_p10 if inp.mulch and rain_p10 < c.rain[2] else 0)
        d = max(0.0, c.rain[1] - eff)
        deficits.append((s, d, d / c.rain[1]))
    water_ratio = sum(s * ratio for s, _, ratio in deficits)
    veg = [r["crop"] for r in chosen if r["crop"].group in ("leafy_veg", "other_fruit_veg")]
    if not veg:
        veg = [c for c in CROPS if c.name in ("Amaranth leaves", "Tomato")]
    garden_deficits = []
    for c in veg:
        eff = rain_p10 + inp.irrigation_mm + (0.12 * rain_p10 if inp.mulch and rain_p10 < c.rain[2] else 0)
        garden_deficits.append(max(0.0, c.rain[1] - eff))
    garden_def_mm = statistics.mean(garden_deficits)
    water = {
        "dry_scenario_rain_mm": rain_p10,
        "garden_deficit_mm": garden_def_mm,
        "garden_tank_liters_for_deficit": garden_def_mm * inp.garden_m2,
        "garden_tank_liters_one_week_buffer": 21.0 * inp.garden_m2,
        "garden_crops": [c.name for c in veg],
        "land_weighted_deficit_pct": water_ratio * 100,
    }

    # ---- agroforestry --------------------------------------------------------
    annual = rm["mean"] / (0.70 if inp.season == "rainy" else 0.30)
    wn, wi = {"income": (.3, .7), "balanced": (.5, .5), "resilience": (.5, .5)}.get(inp.priority, (.7, .3))
    trees = []
    for t in TREES:
        suit = trapezoid(annual, *t.rain)
        cyc = max(0.0, 1 - 2 * inp.cyclone_prob * (1 - t.cyclone_tol))
        value = wn * t.nutrition + wi * t.income
        sc = 0.40 * suit + 0.25 * cyc + 0.35 * value + (0.10 * t.erosion if ls >= 2.5 else 0.0)
        trees.append({"name": t.name, "score": sc, "rain_suitability": suit, "years_to_fruit": t.years_to_fruit, "role": t.role})
    trees.sort(key=lambda x: x["score"], reverse=True)

    # ---- stress test -----------------------------------------------------------
    cands = [c for c in CROPS if inp.season in c.seasons]
    stress = []
    for m in (0.5, 0.7, 0.85, 1.0, 1.15, 1.3, 1.5):
        rr = rm["mean"] * m
        pc = portfolio_det(items, rr, inp, needs)
        stress.append({"rain_pct_of_expected": round(m * 100), "rain_mm": rr,
                       "plan_overall_coverage": statistics.mean(pc.values()),
                       "plan_energy_coverage": pc["kcal"], "best_crop": best_crop_det(rr, cands, inp)})

    # ---- resilience index ----------------------------------------------------------
    legume_share = sum(s for r, s in zip(chosen, shares) if r["crop"].n_fixer)
    hedge = 1 - sum(s * r["fail_prob"] for r, s in zip(chosen, shares))
    parts = {
        "diversity": min(1.0, len(groups) / 5),
        "bad_season_protection": port_p10_overall,
        "failure_hedging": hedge,
        "erosion_control": 1 - min(1.0, port_soil / 25.0),
        "soil_building": min(1.0, legume_share / 0.2),
        "water_security": 1 - water_ratio,
    }
    rw = {"diversity": .25, "bad_season_protection": .25, "failure_hedging": .20,
          "erosion_control": .15, "soil_building": .05, "water_security": .10}
    res_index = 100 * sum(rw[k] * parts[k] for k in rw)
    res_label = "Strong" if res_index >= 75 else "Moderate" if res_index >= 55 else "Fragile"

    # ---- plan table --------------------------------------------------------------------
    plan = []
    for r, s in zip(chosen, shares):
        c = r["crop"]
        plan.append({
            "crop": c.name, "share": s, "area_ha": inp.land_ha * s, "area_m2": inp.land_ha * s * 10000,
            "plant_on": start.isoformat(), "first_harvest": (start + timedelta(days=c.days)).isoformat(),
            "days_to_harvest": c.days, "expected_kg": inp.land_ha * s * r["mean_yield_kg_ha"],
            "bad_season_kg": inp.land_ha * s * r["p10_yield_kg_ha"], "tip": c.tip,
            "harvest_after_season_end": c.days > inp.season_days,
        })

    # ---- alerts ----------------------------------------------------------------------------
    alerts = []
    if risk["drought_prob"] > 0.25:
        alerts.append(f"Drought risk is elevated ({risk['drought_prob']:.0%} chance of a season <75% of normal). "
                      "Favour drought-tolerant crops (pigeon pea, cassava, sweet potato), keep mulch on, and store rainwater.")
    if risk["excess_prob"] > 0.20 or port_soil >= 12:
        alerts.append("Heavy rain / erosion is a concern. Use contour planting, terraces or hedgerows and keep soil covered.")
    if inp.cyclone_prob >= 0.15:
        alerts.append("Cyclone risk is notable: stagger plantings, keep root crops (cassava, taro, sweet potato) as a storm buffer"
                      + ("." if inp.windbreak else ", and plant a windbreak (coconut, moringa hedge)."))
    if kcal_gap_bad > 30:
        alerts.append(f"In a bad season the household could be short of staple energy for about {kcal_gap_bad:.0f} days. "
                      "Consider selling less, adding cassava as in-ground storage, or seeking community/NGO support for that window.")
    if cov_mean["vita"] < 0.8:
        alerts.append("Vitamin A coverage is low: add orange-fleshed sweet potato, carrots, papaya or leafy greens.")
    if cov_mean["iron"] < 0.6:
        alerts.append("Iron coverage is low: add beans/pigeon pea and moringa or amaranth leaves; pair with vitamin C foods to boost absorption.")
    if cov_mean["protein"] < 0.7:
        alerts.append("Protein coverage is low: expand legumes/groundnut, or add fish/eggs where available.")
    if rm["trend_pct_per_decade"] < -5:
        alerts.append(f"Your rainfall history shows a declining trend ({rm['trend_pct_per_decade']:.1f}% per decade): plan for drier seasons.")
    if inp.forecast_rain_mm is not None and inp.forecast_confidence < 0.4:
        alerts.append("Forecast confidence is low, so the plan leans mostly on historical rainfall.")
    if inp.soil_fertility == "low" and legume_share < 0.2:
        alerts.append("Soil fertility is low: raise the legume share to ~20% and add compost.")
    if inp.labor == "low" and any(r["crop"].labor > LABOR_CAPACITY["low"] for r in chosen):
        alerts.append("Labour is limited: stage the work (plant the staple first, gardens after) or swap labour with neighbours.")
    if len(groups) < 4:
        alerts.append("The plan covers few food groups; aim for 5+ (staple, legume, vitamin A, leafy greens, fruit/veg).")
    excluded_dry = [r["name"] for r in results if r["excluded"] and "too dry" in r["excluded"]]
    if excluded_dry:
        alerts.append("With irrigation or rainwater harvesting these could become viable: " + ", ".join(excluded_dry) + ".")
    if inp.cyclone_prob >= 0.15 and not inp.windbreak:
        alerts.append("Agroforestry tip: a coconut/moringa windbreak cuts cyclone yield losses by roughly 30% in this model.")
    if not alerts:
        alerts.append("No major warning flags with these inputs. Re-run when the forecast updates.")

    return {
        "inputs": asdict(inp),
        "start_date": start.isoformat(),
        "rainfall": {**rm, "sim_p10": pct(rains, 10), "sim_p50": pct(rains, 50), "sim_p90": pct(rains, 90),
                     "reference_mm": ref_rain},
        "ranking": ranked, "quick_picks": quick, "excluded": [r for r in results if r["excluded"]],
        "plan": plan,
        "outcomes": {
            "coverage_mean": cov_mean, "coverage_bad_season_p10": cov_p10,
            "food_gap_days_typical": kcal_gap_mean, "food_gap_days_bad_season": kcal_gap_bad,
            "prob_energy_below_80pct": p_kcal_short, "food_security_rating": food_rating,
            "income_mean_usd": statistics.mean(income), "income_p10_usd": pct(income, 10),
            "food_groups": groups, "child_nutrition_risk": child_risk,
            "monoculture_crop": mono["name"], "monoculture_bad_season_overall": mono_p10_overall,
            "portfolio_bad_season_overall": port_p10_overall,
            "monoculture_income_p10_usd": pct(m_income, 10),
        },
        "risk": risk,
        "soil": {"portfolio_t_ha": port_soil, "bare_ground_t_ha": bare_soil, "rating": soil_rating(port_soil)},
        "water": water, "trees": trees, "stress_test": stress,
        "resilience": {"index": res_index, "label": res_label, "parts": parts},
        "alerts": alerts,
    }


# --------------------------------------------------------------------------
# Report rendering
# --------------------------------------------------------------------------
def table(headers, rows):
    cols = list(zip(*([headers] + rows)))
    widths = [max(len(str(c)) for c in col) for col in cols]
    out = ["  ".join(str(h).ljust(w) for h, w in zip(headers, widths)),
           "  ".join("-" * w for w in widths)]
    for r in rows:
        out.append("  ".join(str(c).ljust(w) for c, w in zip(r, widths)))
    return "\n".join(out)


def pc(x):
    return f"{x * 100:.0f}%"


def render(rep):
    I = rep["inputs"]
    R = rep["rainfall"]
    O = rep["outcomes"]
    out = []
    add = out.append

    def head(t):
        add("")
        add("=" * 78)
        add(t)
        add("=" * 78)

    add("CR-CNI CROP & NUTRITION SEASON SIMULATOR - COMOROS")
    add(f"Season: {I['season']}   Start: {rep['start_date']}   Land: {I['land_ha']} ha   "
        f"Slope: {I['slope']}   Priority: {I['priority']}")
    add(f"Household: {I['adults']} adults, {I['children_5_14']} children 5-14, {I['children_u5']} children under 5   "
        f"Simulations: {I['trials']}")

    head("1. RAINFALL OUTLOOK")
    add(f"Expected seasonal rainfall : {R['mean']:,.0f} mm  (likely range {R['sim_p10']:,.0f} - {R['sim_p90']:,.0f} mm, 80% interval)")
    if R["hist_mean"]:
        add(f"History average            : {R['hist_mean']:,.0f} mm  (trend {R['trend_pct_per_decade']:+.1f}% per decade)")
    add(f"Forecast weight in blend   : {R['forecast_weight']:.0%}")

    head("2. BEST CROPS THIS SEASON")
    rows = []
    for i, r in enumerate(rep["ranking"][:7], 1):
        c = r["crop"]
        rows.append([i, r["name"], f"{r['score']:.2f}", f"{r['mean_yield_kg_ha'] / 1000:.1f}",
                     f"{r['p10_yield_kg_ha'] / 1000:.1f}", pc(r["fail_prob"]), f"{r['nutrition_idx']:.2f}",
                     f"${r['income_ha']:,.0f}", f"{r['soil_loss_t_ha']:.1f}", c.days])
    add(table(["#", "Crop", "Score", "Yield t/ha", "Bad-yr t/ha", "Fail risk", "Nutr.idx", "Income/ha", "Soil loss", "Days"], rows))
    add("")
    add(f"==> BEST CROP THIS SEASON: {rep['ranking'][0]['name']}")
    add("")
    for label, r in rep["quick_picks"].items():
        add(f"  {label:<24}: {r['name']}")

    head("3. RECOMMENDED PLANTING PLAN")
    rows = [[p["crop"], pc(p["share"]), f"{p['area_m2']:,.0f}", p["plant_on"], p["first_harvest"] +
             (" *" if p["harvest_after_season_end"] else ""), f"{p['expected_kg']:,.0f}", f"{p['bad_season_kg']:,.0f}"]
            for p in rep["plan"]]
    add(table(["Crop", "Land", "Area m2", "Plant on", "First harvest", "Expected kg", "Bad-season kg"], rows))
    add("  * harvest continues after the end of the season")
    add("")
    for p in rep["plan"]:
        add(f"  - {p['crop']}: {p['tip']}")

    head("4. EXPECTED OUTCOMES FOR THE HOUSEHOLD")
    add(f"(Assumes {I['sell_fraction']:.0%} of the harvest is sold and the rest eaten; one season's food covers {I['coverage_days']} days.)")
    add("")
    rows = [[NUTR_LABEL[k], pc(O["coverage_mean"][k]), pc(O["coverage_bad_season_p10"][k])] for k in NUTR]
    add(table(["Nutrient need met", "Typical season", "Bad season (1 in 10)"], rows))
    add("")
    add(f"Food security rating        : {O['food_security_rating']}")
    add(f"Energy shortfall (days)     : ~{O['food_gap_days_typical']:.0f} typical, ~{O['food_gap_days_bad_season']:.0f} in a bad season")
    add(f"Chance energy is below 80%  : {pc(O['prob_energy_below_80pct'])}")
    add(f"Expected cash income        : ${O['income_mean_usd']:,.0f} (bad season: ${O['income_p10_usd']:,.0f})")
    add(f"Food groups grown           : {len(O['food_groups'])} ({', '.join(O['food_groups'])})")
    add(f"Diversification benefit     : bad-season overall nutrition {pc(O['portfolio_bad_season_overall'])} "
        f"with this mix vs {pc(O['monoculture_bad_season_overall'])} planting only {O['monoculture_crop']}")

    head("5. CHILD NUTRITION RISK (under-5s)")
    add(f"Risk level: {O['child_nutrition_risk']}")
    add("Based on the worst of iron / vitamin A / protein in a bad season, and number of food groups.")
    add("Note: iron from plants is poorly absorbed, so real iron status may be lower than shown.")

    head("6. RISK DASHBOARD")
    K = rep["risk"]
    add(f"Drought season (<75% of normal rain) : {pc(K['drought_prob'])}")
    add(f"Excess-rain season (>135% of normal) : {pc(K['excess_prob'])}")
    add(f"Damaging cyclone                     : {pc(K['cyclone_prob'])}")
    add(f"At least one adverse event           : {pc(K['any_adverse_prob'])}")

    head("7. SOIL & EROSION")
    S = rep["soil"]
    add(f"Estimated soil loss with this plan : {S['portfolio_t_ha']:.1f} t/ha/season  -> {S['rating']}")
    add(f"If the same land were bare soil    : {S['bare_ground_t_ha']:.1f} t/ha/season")
    add("(Indicative index in the spirit of RUSLE, not a field measurement.)")

    head("8. WATER PLAN")
    W = rep["water"]
    add(f"Dry-scenario (1 in 10) rainfall      : {W['dry_scenario_rain_mm']:,.0f} mm")
    add(f"Average water shortfall of the plan  : {W['land_weighted_deficit_pct']:.0f}% of crop optimum")
    add(f"Nutrition garden ({I['garden_m2']:.0f} m2: {', '.join(W['garden_crops'])})")
    add(f"  Seasonal shortfall: {W['garden_deficit_mm']:.0f} mm = {W['garden_tank_liters_for_deficit']:,.0f} litres of stored water")
    add(f"  Minimum one-week dry-spell buffer: {W['garden_tank_liters_one_week_buffer']:,.0f} litres")

    head("9. AGROFORESTRY / TREE RECOMMENDATIONS")
    rows = [[t["name"], f"{t['score']:.2f}", pc(t["rain_suitability"]), f"{t['years_to_fruit']:g}", t["role"]] for t in rep["trees"][:4]]
    add(table(["Tree", "Fit", "Rain fit", "Yrs to crop", "Role"], rows))

    head("10. RAINFALL STRESS TEST (does the plan hold if the season goes wrong?)")
    rows = [[f"{s['rain_pct_of_expected']}%", f"{s['rain_mm']:,.0f}", pc(s["plan_energy_coverage"]),
             pc(s["plan_overall_coverage"]), s["best_crop"]] for s in rep["stress_test"]]
    add(table(["Rain vs expected", "Rain mm", "Plan energy met", "Plan overall met", "Best crop at that rainfall"], rows))

    head("11. CLIMATE-RESILIENCE INDEX")
    Z = rep["resilience"]
    add(f"{Z['index']:.0f} / 100  ({Z['label']})")
    for k, v in Z["parts"].items():
        add(f"  {k.replace('_', ' '):<24}: {v * 100:.0f}")

    head("12. ALERTS & RECOMMENDATIONS")
    for a in rep["alerts"]:
        add(f"  * {a}")

    head("13. CROPS EXCLUDED THIS SEASON")
    for r in rep["excluded"]:
        add(f"  - {r['name']}: {r['excluded']}")
    add("")
    add("Parameters are approximate planning values - validate with local agronomic data.")
    return "\n".join(out)


def report_for_json(rep):
    """Strip non-serialisable crop objects."""
    def clean_row(r):
        return {k: v for k, v in r.items() if k != "crop"}
    d = dict(rep)
    d["ranking"] = [clean_row(r) for r in rep["ranking"]]
    d["excluded"] = [clean_row(r) for r in rep["excluded"]]
    d["quick_picks"] = {k: v["name"] for k, v in rep["quick_picks"].items()}
    return d


# --------------------------------------------------------------------------
# Input handling (interactive / config)
# --------------------------------------------------------------------------
def _float_or_none(s):
    return None if s.strip().lower() in ("none", "n", "-", "") else float(s)


def _float_list(s):
    return [float(x) for x in s.replace(";", ",").split(",") if x.strip()]


def _str_list(s):
    return [x.strip() for x in s.split(",") if x.strip() and x.strip().lower() != "none"]


def _bool(s):
    return s.strip().lower() in ("y", "yes", "true", "1")


def ask(prompt, default, cast=str, choices=None):
    shown = ",".join(str(x) for x in default) if isinstance(default, list) else ("none" if default is None else default)
    if isinstance(default, bool):
        shown = "y" if default else "n"
    while True:
        raw = input(f"{prompt} [{shown}]: ").strip()
        if raw == "":
            return default
        try:
            v = cast(raw)
            if choices and str(v).lower() not in choices:
                print(f"   Please choose one of: {', '.join(choices)}")
                continue
            return v.lower() if choices else v
        except ValueError:
            print("   Could not read that, please try again.")


def interactive_inputs():
    d = Inputs()
    print("CR-CNI Crop & Nutrition Season Simulator - press Enter to keep the [default].\n")
    d.season = ask("Season (rainy/dry)", d.season, str, ("rainy", "dry"))
    d.start_date = ask("Planting start date YYYY-MM-DD (blank = today)", d.start_date, str)
    d.season_days = ask("Season length in days", d.season_days, int)
    d.forecast_rain_mm = ask("Forecast seasonal rainfall in mm (none = unknown)", d.forecast_rain_mm, _float_or_none)
    if d.forecast_rain_mm is not None:
        d.forecast_confidence = ask("Forecast confidence 0-1", d.forecast_confidence, float)
    d.hist_rain_mm = ask("Past seasonal rainfall in mm, oldest to newest, comma-separated", d.hist_rain_mm, _float_list)
    d.mean_temp_c = ask("Average season temperature (C)", d.mean_temp_c, float)
    d.temp_anomaly_c = ask("Expected warm anomaly vs normal (C)", d.temp_anomaly_c, float)
    d.cyclone_prob = ask("Chance of a damaging cyclone this season 0-1", d.cyclone_prob, float)
    d.land_ha = ask("Land available (hectares)", d.land_ha, float)
    d.slope = ask("Slope (flat/gentle/moderate/steep)", d.slope, str, tuple(SLOPE_LS))
    d.soil_fertility = ask("Soil fertility (low/medium/high)", d.soil_fertility, str, tuple(FERTILITY))
    d.labor = ask("Labour available (low/medium/high)", d.labor, str, tuple(LABOR_CAPACITY))
    d.adults = ask("Adults in household", d.adults, int)
    d.children_5_14 = ask("Children aged 5-14", d.children_5_14, int)
    d.children_u5 = ask("Children under 5", d.children_u5, int)
    d.priority = ask("Priority (nutrition/income/resilience/balanced/fast_food)", d.priority, str, tuple(WEIGHTS))
    d.sell_fraction = ask("Share of harvest you will sell 0-1", d.sell_fraction, float)
    d.irrigation_mm = ask("Extra irrigation / stored water (mm over season)", d.irrigation_mm, float)
    d.mulch = ask("Will you mulch? (y/n)", d.mulch, _bool)
    d.compost = ask("Will you add compost? (y/n)", d.compost, _bool)
    d.windbreak = ask("Is there a windbreak / tree belt? (y/n)", d.windbreak, _bool)
    d.conservation = ask("Soil conservation in place (contour,terraces,agroforestry or none)", d.conservation, _str_list)
    d.garden_m2 = ask("Nutrition garden size (m2)", d.garden_m2, float)
    return d


def main(argv=None):
    ap = argparse.ArgumentParser(description="CR-CNI crop & nutrition season simulator for Comoros")
    ap.add_argument("--demo", action="store_true", help="run with the built-in example inputs")
    ap.add_argument("--config", help="JSON file with inputs")
    ap.add_argument("--json-out", help="also save the full report as JSON")
    ap.add_argument("--write-example-config", metavar="PATH", help="write a template inputs file and exit")
    ap.add_argument("--seed", type=int, help="random seed (default 42)")
    ap.add_argument("--trials", type=int, help="number of Monte Carlo trials (default 2000)")
    a = ap.parse_args(argv)

    if a.write_example_config:
        with open(a.write_example_config, "w", encoding="utf-8") as f:
            json.dump(asdict(Inputs()), f, indent=2)
        print(f"Wrote example inputs to {a.write_example_config}")
        return 0

    try:
        if a.config:
            with open(a.config, encoding="utf-8") as f:
                inp = Inputs.from_dict(json.load(f))
        elif a.demo or not sys.stdin.isatty():
            inp = Inputs()
        else:
            inp = interactive_inputs()
        if a.seed is not None:
            inp.seed = a.seed
        if a.trials is not None:
            inp.trials = a.trials
        rep = simulate(inp)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(render(rep))
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(report_for_json(rep), f, indent=2, default=str)
        print(f"\nFull report saved to {a.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
