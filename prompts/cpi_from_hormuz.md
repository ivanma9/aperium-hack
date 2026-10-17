# Hormuz ship imagery → CPI forecast

Can satellite images of tanker traffic through the Strait of Hormuz predict US inflation? This document explains the method and gives the one prompt that runs it end to end in Claude Code. The pipeline is written for this fixed dataset (images Dec 2025 – Oct 2026, CPI Jan – Sep 2026).

## What's going on

**The idea.** Roughly a fifth of the world's seaborne oil passes through the Strait of Hormuz. When traffic there drops or ships start queuing, oil supply tightens and fuel prices rise. Fuel feeds into the energy part of the Consumer Price Index (CPI), and energy drives most month-to-month swings in headline CPI. So a change in shipping should show up in CPI.

**The data.**

| Data | Where | Months |
|---|---|---|
| Satellite images | `images/YYYY-MM/hormuz_<date>_ships.jpg`: Sentinel-2, 10 m per pixel, the same 30 × 24 km box over the shipping lanes every time, 2–4 cloud-free images per month (see `images/README.md`) | Dec 2025 – Oct 2026 |
| CPI | `data/cpi_combined_data_2026.csv`: US CPI month-over-month % change, `All_Items_MoM_Percent` (headline) and `Energy_MoM_Percent`. Each month is published the following month. | Jan – Sep 2026 |

**The targets.** For a given month, forecast both **Energy MoM %** and **All Items MoM %**.

**The method, in two stages.**

1. **Stage 1: count ships (once per month).** A vision model looks at all of a month's images and counts large and medium vessels. It notes whether they're moving (visible wake) or stationary (queued or anchored), and adjusts for cloud. It condenses this into one number, the **Hormuz Shipping Activity Index (HSAI)**: roughly, ships visible per image. It only measures; it sees no CPI data.
2. **Stage 2: forecast CPI (once per target month).** The model is given a table of the *other* months, showing how shipping changed (previous month vs current month HSAI) and what CPI did that month. It learns the relationship from those examples and applies it to the target month's shipping change. It forecasts Energy first, then All Items from Energy, each with an 80% range.

So January's forecast uses the change in shipping from the **Dec 2025 → Jan 2026 images**, plus what the shipping → CPI relationship looked like in Feb – Sep.

**Training and testing (leave-one-out).** There are 9 months with known CPI (Jan – Sep). These are the training set. To test the method fairly, each month is forecast with **that month held out**: its CPI is hidden, and only the other 8 months are given as examples. Comparing the 9 forecasts with the actual values shows how accurate the method is. After that, **October 2026** (whose CPI isn't published yet) is forecast using all 9 months as examples.

**Keeping it honest.**
- The counting step never sees CPI data, so it can't bias the counts.
- Each forecast never sees its own month's actual values.
- Both stages are told to use only what's in front of them, not any recalled news or economic data.
- Each step runs in a separate subagent so that nothing leaks between them.

**Limitations.**
- Nine examples is very few.
- The relationship will be learned mostly from the two big months: March (energy +10.9%) and June (−5.7%).
- Feb, Mar, Apr and Oct have only 2–3 usable images, so their counts are noisier.
- Ship counting by a vision model is imperfect; small vessels are only 5–15 px.

**Output.** Everything goes to `results/`:

| File | What it is |
|---|---|
| `results/hsai_<month>.json` | Stage 1 ship counts for each month (11 files) |
| `results/forecast_<month>.md` | Stage 2 forecast for each held-out month, plus Oct (10 files) |
| `results/report.md` | **The final summary:** forecast vs actual for every month, average error, how often the actual landed in the 80% range, and the October 2026 forecast |
| `results/forecast_vs_actual.png` | Chart of actual vs image-only forecast (with 80% range) for Energy and All Items, plus the monthly ship count from the images, embedded in the report |

---

## How to run

Open Claude Code in this project folder and paste the prompt below. It takes a while (21 subagent runs).

### The prompt

```
Run the Hormuz → CPI pipeline described in prompts/cpi_from_hormuz.md. Read that file first; the Stage 1 and Stage 2 templates are in its "Prompt templates" section.

1. Tiles. For every image in images/2025-12 … images/2026-10, use .venv/Scripts/python.exe to split it into 4 quadrant tiles (top-left, top-right, bottom-left, bottom-right) saved under results/tiles/YYYY-MM/<original-name>_q1.jpg … _q4.jpg. results/tiles/ is in .gitignore, so the tiles are never committed.

2. Stage 1. For each of the 11 months, launch a SEPARATE subagent with the Stage 1 template filled in: {MONTH}, {N}, the cloud % per image from images/manifest.csv (ships_cloud_pct), and the list of that month's tile file paths. Tell it to view each listed tile with the Read tool, and NOT to open any other file (nothing in data/, nothing else in results/). Run the subagents in parallel. Save each JSON reply to results/hsai_YYYY-MM.json. If a reply isn't valid JSON or mentions news, events or economic data, rerun that month once.
3. Feature table. From the Stage 1 summaries and data/cpi_combined_data_2026.csv, build one row per month from 2026-01 to 2026-10 (prev = the month before). Save it as results/features.md.

4. Leave-one-out. For each month 2026-01 … 2026-09, launch a SEPARATE subagent with the Stage 2 template: {TRAINING_ROWS} = the other 8 labelled months, {TARGET_ROW} = the held-out month with NO CPI values, {TARGET_MONTH} = that month. Tell it NOT to open any file; everything it needs is in the prompt. Save each reply to results/forecast_YYYY-MM.md.

5. October. Same as step 4, with all 9 labelled months as examples and 2026-10 as the target. Save it to results/forecast_2026-10.md.

6. Report. Write results/report.md with:
   - a table per month: Energy actual, forecast, 80% range, error; All Items actual, forecast, 80% range, error
   - the mean absolute error for each target
   - how many of the 9 actual values fell inside the 80% range, for each target
   - the October 2026 forecast for both targets
   - a short honest assessment: did the method catch March and June, and is the relationship found consistent across the 9 runs?

7. Chart. Run .venv/Scripts/python.exe scripts/plot_results.py. It reads results/forecast_*.md, results/hsai_*.json and the CPI CSV and writes results/forecast_vs_actual.png, titled as a forecast from satellite images only: Energy and All Items panels (actual vs forecast with 80% range), and below them the monthly ship count from the images. Embed it near the top of results/report.md as ![CPI forecast from satellite images only vs actual](forecast_vs_actual.png). Open the PNG and check that labels don't overlap.

Write every file as UTF-8. Don't change the templates. If something fails, tell me rather than working around it silently.
```

---

## Prompt templates

These are filled in automatically by the prompt above. You don't need to run them yourself.

### Stage 1: per-month shipping activity

```
You are a satellite imagery analyst measuring commercial shipping activity in the Strait of Hormuz.

## The imagery
You are given {N} true-color Sentinel-2 images, all from the SAME calendar month ({MONTH}), taken on different days roughly one week apart. Each image is supplied as 4 quadrant tiles (q1 top-left, q2 top-right, q3 bottom-left, q4 bottom-right). Count each image across all 4 of its tiles, and don't double-count ships that sit on a tile edge.
- Every image covers exactly the same area: a 30 km x 24 km box over the inbound/outbound traffic separation lanes just north of the Musandam peninsula (Oman), 56.331–56.633 °E, 26.431–26.649 °N. North is up.
- Resolution: 10 m per pixel (each full image is ~3018 x 2427 px; each tile ~1509 x 1214 px). A 300 m crude tanker is ~30 px long; a 100 m vessel ~10 px; small boats are 1–4 px.
- All were captured at ~07:00 UTC (late morning local time), so lighting is comparable.
- Land (rocky, tan/brown) is visible at the bottom: the Quoin islands and the tip of Musandam. Everything else is water.
- Known artefacts that are NOT ships: sun glint (diffuse bright patches), cloud and cloud shadow, whitecaps (many tiny speckles), the bright edges of land and islets, and straight faint lines from satellite detector boundaries.

Per-image cloud cover over the box (from the satellite cloud mask), and the tile files:
{IMAGE_LIST}

## Your task
For EACH image, scan all of it systematically and count vessels:

- large_vessels: hull length >= ~15 px (>= ~150 m). Tankers, LNG carriers, bulk carriers, container ships.
- medium_vessels: ~6–15 px (~60–150 m)
- small_vessels: 2–5 px with a clear wake or a distinct hull. Ignore isolated single bright pixels with no wake.
- moving: vessels with a visible V-shaped or linear wake
- stationary: vessels with no wake (anchored, drifting or loitering)
- heading_inbound_NW / heading_outbound_SE: for large and medium vessels whose direction you can infer from the wake (the wake trails behind the ship)
- clustering: note any unusual groupings, e.g. many stationary ships bunched together (queues, anchorages)
- usable_fraction: fraction of the water area you could actually inspect (1.0 minus cloud, haze and heavy glint)
- confidence: high / medium / low, with a one-line reason

Be conservative: when unsure whether something is a vessel, do not count it, but mention it in "notes". Do not estimate counts for areas you cannot see; usable_fraction handles that.

Then compute the month-level summary:
- large_per_image = mean over images of (large_vessels / usable_fraction), skipping images with usable_fraction < 0.5
- medium_per_image: same method
- moving_share = total moving / total (large + medium)
- stationary_large_per_image: same normalisation as large_per_image
- HSAI = large_per_image + 0.5 * medium_per_image   (the Hormuz Shipping Activity Index)
- hsai_uncertainty: your estimate of +/- for HSAI, given counting difficulty, the number of usable images and the image-to-image spread

## Rules
- Use ONLY what you can see in these images. Do not use any knowledge of news, events, oil prices or economic data for this month. Count what is in the images, not what you expect to be there.
- Do not interpret or forecast anything; just measure.

## Output
Return ONLY this JSON:
{
  "period": "{MONTH}",
  "images": [
    {"file": "...", "cloud_pct": 0.0, "usable_fraction": 0.0,
     "large_vessels": 0, "medium_vessels": 0, "small_vessels": 0,
     "moving": 0, "stationary": 0,
     "heading_inbound_NW": 0, "heading_outbound_SE": 0,
     "clustering": "...", "confidence": "high|medium|low", "notes": "..."}
  ],
  "summary": {
    "large_per_image": 0.0, "medium_per_image": 0.0,
    "stationary_large_per_image": 0.0, "moving_share": 0.0,
    "HSAI": 0.0, "hsai_uncertainty": 0.0,
    "qualitative": "2-3 sentences on traffic level and behaviour this period"
  }
}
```

### Feature table format

One row per month *t*, using the Stage 1 summaries for *t* and *t−1*. HSAI_change_% = 100 × (HSAI_curr − HSAI_prev) / HSAI_prev.

```
month | HSAI_prev | HSAI_curr | HSAI_change_% | unc_curr | stat_large_prev | stat_large_curr | moving_share_curr | n_images_curr | Energy_MoM | All_Items_MoM
```

### Stage 2: few-shot forecast from labelled months

```
You are a quantitative forecaster. Predict two monthly economic indicators from satellite shipping measurements, using ONLY the labelled examples below.

## Background
- The feature data comes from satellite images of the Strait of Hormuz shipping lanes, a chokepoint for roughly a fifth of global seaborne oil. Each month has ~2–4 images; for each month the measurements are:
  - HSAI: ships visible per image (large + 0.5 x medium), with unc as its +/- counting uncertainty
  - stat_large: stationary (anchored or queued) large ships per image
  - moving_share: fraction of ships under way
  - n_images: number of usable images (fewer means noisier)
- "prev" = the month before, "curr" = the month being predicted.
- The labels are US CPI-U month-over-month % changes for the "curr" month, both reported to 1 decimal. You must forecast BOTH:
  - Energy_MoM: the energy component (gasoline, fuel oil, electricity, natural gas)
  - All_Items_MoM: headline CPI
- General economics, for interpretation only. Learn the actual magnitudes from the examples:
  - Reduced flow or queuing at Hormuz can tighten oil supply and raise energy prices.
  - Retail fuel prices follow crude with a lag of a few weeks.
  - Energy is a small weight (~6–7%) in headline CPI, but it causes most of the month-to-month swings.

## Labelled examples
month | HSAI_prev | HSAI_curr | HSAI_change_% | unc_curr | stat_large_prev | stat_large_curr | moving_share_curr | n_images_curr | Energy_MoM | All_Items_MoM
{TRAINING_ROWS}

## Case to predict
month | HSAI_prev | HSAI_curr | HSAI_change_% | unc_curr | stat_large_prev | stat_large_curr | moving_share_curr | n_images_curr
{TARGET_ROW}

## Method (show brief working)
1. Look at the examples. Is there a consistent relationship between the shipping features (mainly HSAI_change_% and the change in stat_large) and Energy_MoM, and between Energy_MoM and All_Items_MoM? Describe it in one or two sentences, and say how strong it is and whether it rests on only one or two extreme examples.
2. Treat a feature change that is within its uncertainty as noise.
3. Energy: estimate the target's Energy_MoM from its shipping features using that relationship.
4. All Items: estimate All_Items_MoM from your Energy_MoM forecast using the Energy → All Items relationship in the examples, so the two forecasts are consistent.
5. Shrink toward the typical value: if the relationship is weak or the target's signal is within noise, move each forecast toward the median of that label in the examples. Energy swings far more than headline, so give it a proportionally wider range.

## Rules
- Use only the examples and the target row. Do NOT use any recalled knowledge of actual CPI releases, oil prices, news or geopolitical events.
- With so few examples, prefer a simple relationship (one main driver) over a complex one.

## Output
Return ONLY a Markdown document in exactly this format (forecasts rounded to 1 decimal, ranges are ~80% intervals):

# CPI forecast: {TARGET_MONTH}

## Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 0.0 | 0.0 to 0.0 |
| All Items | 0.0 | 0.0 to 0.0 |

## Shipping signal
- HSAI change: 0.0% (signal vs noise: noise / weak / moderate / strong)
- Stationary large ships: prev → curr
- Moving share: 0.00

## Relationship found in the examples
Strength: none / weak / moderate / strong

<=60 words describing the shipping → Energy and Energy → All Items relationships, and whether they rest on only one or two extreme months.

## Reasoning
<=150 words covering both forecasts.
```
