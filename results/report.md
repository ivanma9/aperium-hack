# Hormuz ship imagery → CPI: results

This is a run of the pipeline in [prompts/cpi_from_hormuz.md](../prompts/cpi_from_hormuz.md).
- **Stage 1** counted ships in 38 Sentinel-2 images (Dec 2025 – Oct 2026), with one subagent per month: [hsai_*.json](.).
- **Stage 2** forecast Energy and All Items CPI month-over-month. Each of Jan – Sep was forecast with that month held out (leave-one-out), using the other 8 months as examples, and October 2026 was forecast using all 9: [forecast_*.md](.).
- The feature table is in [features.md](features.md).

## Leave-one-out results

| Month | Energy actual | Energy forecast | Energy 80% range | Energy error | In range | All Items actual | All Items forecast | All Items 80% range | All Items error | In range |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-01 | 0.6 | 1.5 | -3 to 6 | +0.9 | yes | 0.2 | 0.3 | -0.1 to 0.7 | +0.1 | yes |
| 2026-02 | 0.6 | 0.5 | -2.5 to 3.5 | -0.1 | yes | 0.3 | 0.2 | 0 to 0.4 | -0.1 | yes |
| 2026-03 | 10.9 | 1.8 | -2.5 to 5.5 | -9.1 | **no** | 0.9 | 0.4 | 0 to 0.7 | -0.5 | **no** |
| 2026-04 | 3.8 | 3.0 | -3 to 9 | -0.8 | yes | 0.6 | 0.4 | 0 to 0.9 | -0.2 | yes |
| 2026-05 | 3.9 | 1.0 | -4.5 to 6 | -2.9 | yes | 0.5 | 0.3 | -0.2 to 0.7 | -0.2 | yes |
| 2026-06 | -5.7 | 1.5 | -2 to 5.5 | +7.2 | **no** | -0.4 | 0.3 | 0.1 to 0.6 | +0.7 | **no** |
| 2026-07 | -1.5 | 2.8 | -3.5 to 8 | +4.3 | yes | 0.1 | 0.4 | -0.1 to 0.8 | +0.3 | yes |
| 2026-08 | 2.1 | 1.5 | -3.5 to 6 | -0.6 | yes | 0.4 | 0.3 | -0.1 to 0.7 | -0.1 | yes |
| 2026-09 | 5.2 | 1.2 | -3 to 5 | -4.0 | **no** | 0.6 | 0.3 | -0.1 to 0.6 | -0.3 | yes |

Error = forecast − actual.

| | Energy | All Items |
|---|---|---|
| Mean absolute error | **3.32** pts | **0.28** pts |
| Actual inside the 80% range | **6 / 9** (target ≈ 7) | **7 / 9** (target ≈ 7) |

**January 2026, the original target:** the forecast was All Items **0.3** against an actual of **0.2**, and Energy **1.5** against an actual of **0.6**.

## October 2026 forecast

| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | **2.0** | -3.5 to 7.0 |
| All Items | **0.4** | 0.0 to 0.8 |

This forecast rests on only 2 October images (Oct 4 and 9). The model judged the shipping signal to be noise, so the forecast is essentially the typical value from the examples.

## What the satellite counts show

| Month | HSAI (ships per image) | Notes from Stage 1 |
|---|---|---|
| 2025-12 | 6.36 | Normal two-way lane traffic |
| 2026-01 | 4.89 | Normal two-way lane traffic |
| 2026-02 | 7.71 | Busy and normal |
| 2026-03 | 2.10 | Sharp drop. No large ships. A vessel with a fire or smoke plume was seen on both dates. |
| 2026-04 | 0.17 | Lanes essentially empty |
| 2026-05 – 2026-10 | 0.26 – 0.87 | Near-empty. One medium ship sits repeatedly near the Quoin islets, and there are groups of small fast craft (≈12–20 boats) on several dates. |

The clearest finding is in the images themselves. Commercial traffic in the lanes collapsed between February and April 2026 and has not recovered. This happened as Energy CPI spiked (+10.9% in March).

## Assessment

**Did the method catch March and June? No.**
- **March (Energy +10.9):** this was the biggest miss. Stage 2 did flag March's 73% traffic drop as a "moderate" signal. But with March held out, the other 8 examples show no consistent link between shipping and Energy, so the forecast was shrunk to +1.8.
- **June (Energy −5.7):** the forecast was +1.5. Nothing in the shipping data pointed to a fall in energy prices. Traffic was already near zero and stayed there.
- **The rest:** in the quieter months the errors are small. That is because the forecasts sit near the typical value (Energy ≈ 1–3, All Items ≈ 0.2–0.4), not because the images predicted anything.

**Is the relationship consistent across the 9 runs? Yes, but it's consistently weak.**
- All 9 runs reached the same conclusion: shipping → Energy is weak, and any apparent link rests on March alone.
- All 9 also found the Energy → All Items link strong and stable, at roughly All ≈ 0.2 + 0.07–0.09 × Energy.
- So the second step of the method works, and the first step doesn't, as currently set up.

**Why the shipping signal didn't carry through:**
1. **The feature is month-over-month % change, but the shock is a change in level.** After April, traffic sits near zero, so the % changes swing wildly (+371%, +235%, −59%) on differences smaller than the counting uncertainty. A 2-ship drop from 2 to 0.17 looks like −92%. The thing that actually distinguishes Mar–Oct from Dec–Feb is the *level* of traffic (a disrupted vs normal regime), and the % change hides it.
2. **Only one month marks the transition (March).** Leave-one-out removes it when March is the target, so the model never sees a comparable case.
3. **After the disruption, energy prices move for reasons the images can't see.** Energy went +3.8, +3.9, −5.7, −1.5, +2.1, +5.2 while traffic stayed flat near zero.
4. **Counting is noisy.** Each month was counted by a different subagent, and the large/medium split near the 15 px boundary varied. For example, Feb counted 10 medium ships per image against about 3–5 in Dec and Jan.

**Bottom line:**
- Headline All Items error averaged 0.28 pts, and 7 of 9 actuals fell inside the 80% range. But that is mostly the forecast staying near the typical value.
- The images clearly detect the Hormuz traffic collapse, yet the current feature (HSAI % change) and the leave-one-out setup don't turn that into a useful CPI forecast.
- The most promising change is to give Stage 2 the traffic *level*, or a disrupted/normal flag, alongside the % change, and to add months before Dec 2025 so the model has more normal-regime examples.

---

# Appendix

## A. Feature table

Built from results/hsai_*.json (Stage 1) and data/cpi_combined_data_2026.csv. prev = the month before. 2026-10 has no CPI yet.

```
month | HSAI_prev | HSAI_curr | HSAI_change_% | unc_curr | stat_large_prev | stat_large_curr | moving_share_curr | n_images_curr | Energy_MoM | All_Items_MoM
2026-01 | 6.36 | 4.89 | -23.1 | 1.5 | 0.26 | 0.0 | 0.96 | 4 | 0.6 | 0.2
2026-02 | 4.89 | 7.71 | 57.7 | 2.5 | 0.0 | 0.0 | 0.97 | 3 | 0.6 | 0.3
2026-03 | 7.71 | 2.1 | -72.8 | 1.8 | 0.0 | 0.0 | 0.75 | 2 | 10.9 | 0.9
2026-04 | 2.1 | 0.17 | -91.9 | 0.5 | 0.0 | 0.0 | 1.0 | 3 | 3.8 | 0.6
2026-05 | 0.17 | 0.8 | 370.6 | 0.5 | 0.0 | 0.0 | 1.0 | 4 | 3.9 | 0.5
2026-06 | 0.8 | 0.43 | -46.3 | 0.5 | 0.0 | 0.0 | 1.0 | 4 | -5.7 | -0.4
2026-07 | 0.43 | 0.26 | -39.5 | 0.5 | 0.0 | 0.0 | 1.0 | 4 | -1.5 | 0.1
2026-08 | 0.26 | 0.87 | 234.6 | 0.6 | 0.0 | 0.0 | 0.83 | 4 | 2.1 | 0.4
2026-09 | 0.87 | 0.64 | -26.4 | 0.4 | 0.0 | 0.0 | 0.6 | 4 | 5.2 | 0.6
2026-10 | 0.64 | 0.26 | -59.4 | 0.5 | 0.0 | 0.0 | 0.0 | 2 |  | 
```

## B. Stage 1 ship counts by month

| Month | Images | Large / image | Medium / image | HSAI � unc | Moving share | Per-image large+medium |
|---|---|---|---|---|---|---|
| 2025-12 | 4 | 3.64 | 5.44 | 6.36 � 2.0 | 0.91 | 2025-12-03: 3+6, 2025-12-13: 4+4, 2025-12-23: 6+7, 2025-12-30: 1+4 |
| 2026-01 | 4 | 3.29 | 3.21 | 4.89 � 1.5 | 0.96 | 2026-01-02: 4+3, 2026-01-07: 3+6, 2026-01-17: 2+1, 2026-01-22: 3+2 |
| 2026-02 | 3 | 2.59 | 10.23 | 7.71 � 2.5 | 0.97 | 2026-02-16: 1+13, 2026-02-21: 2+9, 2026-02-26: 4+7 |
| 2026-03 | 2 | 0.0 | 4.21 | 2.1 � 1.8 | 0.75 | 2026-03-18: 0+7, 2026-03-28: 0+1 |
| 2026-04 | 3 | 0.0 | 0.33 | 0.17 � 0.5 | 1.0 | 2026-04-02: 0+1, 2026-04-07: 0+0, 2026-04-17: 0+0 |
| 2026-05 | 4 | 0.8 | 0.0 | 0.8 � 0.5 | 1.0 | 2026-05-02: 0+0, 2026-05-09: 1+0, 2026-05-17: 1+0, 2026-05-29: 1+0 |
| 2026-06 | 4 | 0.25 | 0.36 | 0.43 � 0.5 | 1.0 | 2026-06-01: 1+0, 2026-06-11: 0+1, 2026-06-18: 0+0, 2026-06-21: 0+0 |
| 2026-07 | 4 | 0.0 | 0.52 | 0.26 � 0.5 | 1.0 | 2026-07-06: 0+1, 2026-07-11: 0+0, 2026-07-21: 0+1, 2026-07-26: 0+0 |
| 2026-08 | 4 | 0.0 | 1.73 | 0.87 � 0.6 | 0.83 | 2026-08-07: 0+2, 2026-08-10: 0+1, 2026-08-25: 0+1, 2026-08-30: 0+2 |
| 2026-09 | 4 | 0.0 | 1.29 | 0.64 � 0.4 | 0.6 | 2026-09-04: 0+2, 2026-09-09: 0+1, 2026-09-19: 0+1, 2026-09-29: 0+1 |
| 2026-10 | 2 | 0.0 | 0.52 | 0.26 � 0.5 | 0.0 | 2026-10-04: 0+1, 2026-10-09: 0+0 |

- **2025-12:** Traffic was light to moderate and varied a lot between images: from 1 large and 4 medium vessels on 30 Dec to 6 large and 7 medium on 23 Dec. Almost all large and medium vessels were under way along the separation lanes, with inbound and outbound traffic roughly balanced (12 vs 16). Only one stationary large vessel was seen across the four images, and there were no anchorage queues or clusters.
- **2026-01:** Traffic is light-to-moderate: roughly 3 large and 3 medium vessels per scene, with counts ranging from 3 (Jan 17) to 9 (Jan 7) large plus medium vessels. Almost every vessel is under way with a clear wake, split between inbound (W/NW) and outbound (E/SE) lanes, and no anchorage, queue or cluster of stationary ships is visible in any image.
- **2026-02:** Traffic was moderate and steady: about 11-14 large and medium vessels per image, all three images usable, and little change between images apart from the large/medium split. Almost every vessel was under way with a clear wake, with more eastbound/SE-bound than westbound traffic. No anchorages, queues or groups of stationary ships were seen.
- **2026-03:** Traffic in the box is very light in both images. No large tankers or carriers (15 px or longer) were seen, and only a handful of medium vessels are present. On 03-18 about 7 medium vessels were seen, mostly moving east/southeast, plus a few small craft. On 03-28 essentially nothing was seen beyond one doubtful object. Both images show a vessel with a dark smoke-like plume, and there is no anchorage or queue clustering.
- **2026-04:** Commercial traffic in the box was close to zero in all three April images. Across them there is no large vessel, one probable medium vessel moving roughly westward in the inbound direction on 04-02, and no anchored or queued ships. The lanes appear essentially empty. moving_share rests on a single vessel, and the uncertainty mostly comes from small faint targets that were not counted, mixed in with whitecap speckle and small clouds.
- **2026-05:** Commercial traffic was very light: no more than one large vessel in transit per image (0, 1, 1, 1), with one inbound and two outbound, and no medium vessels. No stationary ships, queues or anchorage clusters appeared. The one notable feature was a formation of about 20 small fast craft on 2026-05-09.
- **2026-06:** Shipping in the lanes box was very sparse in all four images. The month showed one large vessel (June 1) and one probable medium vessel inferred from a wake (June 11); June 18 and June 21 showed no large or medium ships. Every vessel detected was under way, and there were no stationary groups, queues or anchorages.
- **2026-07:** Merchant traffic in the separation lanes is essentially absent across all four images: no large vessels (>=150 m) were seen in any image, and only two medium-or-smaller vessels were seen in total, both under way. The only notable activity is a group of roughly a dozen small fast craft with wakes on 2026-07-21. There are no anchorages, queues or stationary large ships.
- **2026-08:** Traffic was extremely light in all four images. No large vessels (150 m or more) were seen; each image had only 1-2 medium vessels and a few small craft. A red-hulled medium vessel appears near the southern Quoin islet in every image, moving on 3 of the 4 dates. There are no queues, anchorage clusters or groups of stationary ships. Moving share uses only large and medium vessels (5 of 6 had wakes), and the image 3 wake is uncertain.
- **2026-09:** Commercial traffic was almost absent: none of the four scenes shows a vessel of 150 m or more. Medium vessels numbered 1-2 per scene, and the main one was the same red-hulled ship sitting south of the southern Quoin islet on every date. Most of what is visible is small fast craft (1-9 per scene, rising towards month end). Where direction could be read, the medium vessels were heading SE (outbound), and there were no queues or anchorage clusters of large ships.
- **2026-10:** Commercial shipping in the separation lanes is close to absent this month: neither image shows a single large vessel, and only one uncertain stationary medium-sized object appears, on 10-04. The only clearly active traffic is groups of small fast craft moving roughly NE in convoy-like strings on 10-04, and almost none on 10-09. moving_share is 0 because the only large/medium candidate has no wake; small craft are excluded from that ratio.

## C. Stage 2 forecasts (full text)

### CPI forecast: 2026-01

#### Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 1.5 | -3.0 to 6.0 |
| All Items | 0.3 | -0.1 to 0.7 |

#### Shipping signal
- HSAI change: -23.1% (signal vs noise: noise)
- Stationary large ships: 0.26 → 0.0
- Moving share: 0.96

#### Relationship found in the examples
Strength: weak

Shipping → Energy: no consistent relationship. HSAI declines go with both big rises (Mar +10.9, Sep +5.2) and falls (Jun -5.7, Jul -1.5). After March, most HSAI levels sit within their uncertainty. Energy → All Items is strong and consistent across all eight months (All ≈ 0.19 + 0.078 × Energy). The extremes in March and June help set the slope, but the middle months fit it too.

#### Reasoning
The HSAI drop of 1.47 ships per image (6.36 → 4.89) is smaller than its uncertainty of ±1.5, so it is noise. The move in stationary large ships (0.26 → 0) is tiny, and the moving share of 0.96 is normal. That means there is no usable shipping signal, and shipping features predict Energy poorly in the examples anyway. The Energy forecast is therefore shrunk toward the example median of 2.95. It is also pulled down toward the closest analog, February (high HSAI, moving share 0.97, Energy +0.6), which gives 1.5. The range is wide (±4.5) because Energy swings a lot in the examples. All Items comes from the fitted link: 0.19 + 0.078 × 1.5 ≈ 0.3. That is close to the example median of 0.45, and the range is about a tenth as wide as Energy's, consistent with the slope.

### CPI forecast: 2026-02

#### Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 0.5 | -2.5 to 3.5 |
| All Items | 0.2 | 0.0 to 0.4 |

#### Shipping signal
- HSAI change: 57.7% (signal vs noise: weak)
- Stationary large ships: 0.0 → 0.0
- Moving share: 0.97

#### Relationship found in the examples
Strength: weak

Shipping → Energy is weak and inconsistent. Most of it comes from one month, 2026-03, when HSAI fell 73% from a high base and Energy rose 10.9%. After that, HSAI sits near zero and month-to-month changes are within the ±0.5 uncertainty, so they are noise. Energy → All Items is strong and holds across all months: All ≈ 0.17 + 0.08 × Energy.

#### Reasoning
HSAI rose from 4.89 to 7.71, a gain of 2.82 ships per image. That is only slightly larger than the ±2.5 uncertainty, so the signal is weak at best. Stationary large ships stayed at 0 and the moving share was high (0.97), so there is no sign of queuing. If the rise in flow is real, it points to looser supply, not tighter. The closest example is 2026-01: traffic was similar and normal, the HSAI change was within noise, and Energy rose 0.6%. The median Energy value in the examples (about 3.0) comes mostly from disrupted months, so I gave it less weight. I forecast Energy at 0.5%, with a wide range for its volatility. Putting that into the Energy → All Items fit (0.17 + 0.08 × 0.5 ≈ 0.21) gives All Items 0.2%, which matches the median headline value (0.45) shrunk toward the 2026-01 analog (0.2). The range is 0.0 to 0.4.

### CPI forecast: 2026-03

#### Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 1.8 | -2.5 to 5.5 |
| All Items | 0.4 | 0.0 to 0.7 |

#### Shipping signal
- HSAI change: -72.8% (signal vs noise: moderate)
- Stationary large ships: 0.0 → 0.0
- Moving share: 0.75

#### Relationship found in the examples
Strength: weak

There is no consistent link from shipping to Energy. HSAI fell in Jan, Apr, Jun, Jul and Sep, and Energy came in at +0.6, +3.8, -5.7, -1.5 and +5.2. stat_large is almost always 0. Energy to All Items is strong and holds across all eight months, not just one or two extremes: All Items ≈ 0.2 + 0.09 × Energy.

#### Reasoning
HSAI dropped from 7.71 to 2.1. That is a fall of 5.6 ships per image against an uncertainty of 1.8, so it is larger than the noise. It still counts only as moderate because there were just 2 images and stat_large did not change. The closest example is April (-92%), which had Energy +3.8. But June (-46%) and July (-40%) also fell and had negative Energy, so a lower HSAI does not reliably mean higher energy prices. With the shipping-to-Energy link this weak, I shrank the forecast most of the way toward the Energy median of the examples (1.35), leaving a small upward tilt for the large drop and the lower moving share (0.75). That gives 1.8. The range is wide (-2.5 to 5.5) because Energy in the examples runs from -5.7 to +5.2. Feeding 1.8 into the Energy-to-All Items fit gives 0.2 + 0.09 × 1.8 ≈ 0.36, which rounds to 0.4. That matches the All Items median of 0.35, and I used a proportionally narrower range of 0.0 to 0.7.

### CPI forecast: 2026-04

#### Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 3.0 | -3.0 to 9.0 |
| All Items | 0.4 | 0.0 to 0.9 |

#### Shipping signal
- HSAI change: -91.9% (signal vs noise: moderate)
- Stationary large ships: 0.0 → 0.0
- Moving share: 1.00

#### Relationship found in the examples
Strength: weak

Shipping → Energy is weak and inconsistent. Falls in HSAI go with both +10.9 (Mar) and -5.7 (Jun), and rises go with modest gains. The only clear link is March, a single extreme month. Energy → All Items is strong and holds across all months: All ≈ 0.22 + 0.07 × Energy.

#### Reasoning
HSAI fell from 2.1 to 0.17, a drop of about 1.9 ships against an uncertainty of 0.5. That is beyond noise, so it counts as a real signal. It looks like March's large drop, which came with the biggest energy jump (10.9). Since retail fuel lags crude by a few weeks, the decline may still be passing through. But the shipping → energy link rests mostly on March. There is also no queuing: stationary large ships stayed at 0, and moving share is 1.0, the same as May–July, whose energy outcomes were mixed. And only 3 images were usable. So I shrank the energy forecast strongly toward the example median of about 1.35, putting about 20% weight on a March-like outcome. That gives 3.0, with a wide range of -3.0 to 9.0. For headline, the Energy → All Items fit gives 0.22 + 0.07 × 3.0 ≈ 0.43, so 0.4. That is close to the headline median of 0.35, with a range of 0.0 to 0.9.

### CPI forecast: 2026-05

#### Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 1.0 | -4.5 to 6.0 |
| All Items | 0.3 | -0.2 to 0.7 |

#### Shipping signal
- HSAI change: 370.6% (signal vs noise: weak; the absolute change of +0.63 ships/image is only just above the ±0.5 uncertainty, from a very low base)
- Stationary large ships: 0.0 → 0.0
- Moving share: 1.00

#### Relationship found in the examples
Strength: weak

There is no consistent shipping → Energy relationship. Big HSAI drops come with both large rises (Mar +10.9, Apr +3.8) and declines (Jun -5.7, Jul -1.5). Any apparent link depends mostly on the extreme March month. The Energy → All Items link is strong and steady across all 8 months: All Items ≈ 0.2 + 0.07 × Energy.

#### Reasoning
Energy: HSAI rose from 0.17 to 0.80. The 370% change is large only because the base is tiny. In absolute terms it is about one counting uncertainty, so it is barely signal. Stationary large ships stayed at zero, and moving share is 1.00, so there is no sign of queuing. The closest example is August (0.26 → 0.87, a similar small rebound), when Energy was +2.1. The shipping → Energy relationship is weak, so I shrink strongly toward the example median of about 1.35, giving roughly +1.0. Energy across the examples spans -5.7 to +10.9, so the range is wide (-4.5 to 6.0).

All Items: I apply the Energy → All Items fit to the Energy forecast: 0.2 + 0.07 × 1.0 ≈ 0.3. That matches the example median of 0.35. Mapping the Energy range through the same fit, plus some extra spread, gives -0.2 to 0.7.

### CPI forecast: 2026-06

#### Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 1.5 | -2.0 to 5.5 |
| All Items | 0.3 | 0.1 to 0.6 |

#### Shipping signal
- HSAI change: -46.3% (signal vs noise: noise; 0.80 → 0.43 is a 0.37 drop, smaller than unc ±0.5)
- Stationary large ships: 0.0 → 0.0
- Moving share: 1.00

#### Relationship found in the examples
Strength: weak

HSAI_change_% does not predict Energy consistently. Drops came with -1.5 to 10.9, and rises came with 0.6 to 3.9. The apparent link depends on one extreme month, March (-72.8% → 10.9). stat_large hardly varies. In contrast, Energy → All Items is strong across all 8 months: All ≈ 0.22 + 0.07 × Energy.

#### Reasoning
The target's HSAI fall happens at a very low level (below 1 ship per image), and the change is within the counting uncertainty. Stationary ships stay at zero and every ship is moving, so the shipping signal is noise. The closest example is July (-39.5%, 0.43 → 0.26, moving share 1.0, 4 images), which had Energy -1.5. The median Energy across the examples is about 3.0, and May (the month before) was 3.9. Because the signal is noise, I weighted the July analogue against the median and its neighbours and landed at 1.5. Energy swings a lot, so the range is wide (-2.0 to 5.5). For headline, I applied the Energy → All Items fit: 0.22 + 0.07 × 1.5 ≈ 0.33, giving 0.3. The same fit maps the Energy range to roughly 0.1 to 0.6. That forecast sits near the headline median (0.45) and is consistent with the Energy forecast.

### CPI forecast: 2026-07

#### Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 2.8 | -3.5 to 8.0 |
| All Items | 0.4 | -0.1 to 0.8 |

#### Shipping signal
- HSAI change: -39.5% (signal vs noise: noise)
- Stationary large ships: 0.0 → 0.0
- Moving share: 1.00

#### Relationship found in the examples
Strength: weak

Shipping → Energy is weak and inconsistent. The large energy jump (+10.9) follows the only big drop from a high HSAI level (March). Similar percentage drops later go with energy readings of -5.7 to +5.2, so this link rests on one month. Energy → All Items is strong and steady across all eight months: All Items ≈ 0.18 + 0.079 × Energy.

#### Reasoning
HSAI fell from 0.43 to 0.26, a drop of 0.17 ships per image. That is well inside the ±0.5 counting uncertainty. Stationary large ships stayed at zero and moving share is 1.00, so there is no sign of queuing. The -39.5% change is noise caused by the very low ship counts, not a real signal. Since April, when counts became this low, Energy has ranged from -5.7 to +5.2 with no clear link to HSAI. So I shrink the Energy forecast almost fully to the typical value of the examples (median 2.95, mean 2.7), giving 2.8. The range is wide because Energy has a spread of about ±5 pts in the examples. For All Items, I use the fitted Energy → All Items line: 0.18 + 0.079 × 2.8 ≈ 0.40. This matches the example median of 0.45. Applying the same line to the Energy range gives roughly -0.1 to 0.8, so the two forecasts are consistent.

### CPI forecast: 2026-08

#### Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 1.5 | -3.5 to 6.0 |
| All Items | 0.3 | -0.1 to 0.7 |

#### Shipping signal
- HSAI change: 234.6% (signal vs noise: noise)
- Stationary large ships: 0.0 → 0.0
- Moving share: 0.83

#### Relationship found in the examples
Strength: weak

Shipping → Energy is weak. The one clear case is March: a big HSAI drop (-73%) came with Energy at +10.9. Other drops came with negative Energy (June, July), and a rise came with +3.9 (May). Stat_large is flat at 0. Energy → All Items is strong and consistent: roughly All ≈ 0.15 + 0.08 × Energy, across all eight months, not just the extremes.

#### Reasoning
HSAI went from 0.26 to 0.87 ships per image. That is +235%, but the absolute rise of 0.61 is about the same as the counting uncertainty (±0.6), so I treat it as noise. Since April, ship counts have stayed close to zero, and month-to-month changes there have not mapped reliably to Energy (+3.9, -5.7, -1.5, +5.2). Stationary large ships stayed at 0. The moving share of 0.83 is below 1.0. In the examples, lower moving shares (March 0.75, September 0.6) came with positive Energy, which hints at a small upside, but it is not reliable. So I shrink most of the way toward the Energy median of 2.2, nudged down slightly because the May/June/July months near zero ships averaged negative. That gives Energy 1.5, with a wide range for Energy's volatility (-5.7 to +10.9 in the examples). All Items comes from the Energy → headline fit: 0.15 + 0.08 × 1.5 ≈ 0.3. This is close to the All Items median of 0.4.

### CPI forecast: 2026-09

#### Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 1.2 | -3.0 to 5.0 |
| All Items | 0.3 | -0.1 to 0.6 |

#### Shipping signal
- HSAI change: -26.4% (signal vs noise: noise)
- Stationary large ships: 0.0 → 0.0
- Moving share: 0.60

#### Relationship found in the examples
Strength: weak

The link from shipping to Energy is inconsistent. The large Energy spike (+10.9) comes with the March HSAI collapse, but drops of similar size give -5.7 and -1.5, and rises give +3.9 and +2.1. So it rests mostly on one extreme month. Energy → All Items is strong and consistent: All ≈ 0.18 + 0.08 × Energy.

#### Reasoning
HSAI fell from 0.87 to 0.64, a change of -0.23. That is smaller than its ±0.4 uncertainty, and the base is near zero, so the -26.4% is noise. Stationary large ships stayed at zero. A moving share of 0.60 is the lowest in the sample, which hints at slower traffic. But with only about 0.6 ships per image, that ratio is very noisy. It gets only a slight nudge, and no clear queuing signal is present.

With a weak relationship and no real signal, the Energy forecast is pulled toward the example median of 1.35. I set it at 1.2. The range is wide, because Energy in the examples ran from -5.7 to +10.9.

All Items comes from the fitted Energy link: 0.18 + 0.08 × 1.2 ≈ 0.28, which rounds to 0.3. That matches the example median of 0.35. Its range follows from the Energy range, with some extra width for error in the fit.

### CPI forecast: 2026-10

#### Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 2.0 | -3.5 to 7.0 |
| All Items | 0.4 | 0.0 to 0.8 |

#### Shipping signal
- HSAI change: -59.4% (signal vs noise: noise. The absolute drop of 0.38 is smaller than unc 0.5, and HSAI is near the floor.)
- Stationary large ships: 0.0 → 0.0
- Moving share: 0.00 (based on about 0.5 ships per image across only 2 images, so it carries no real information)

#### Relationship found in the examples
Strength: weak (shipping → Energy); strong (Energy → All Items)

HSAI_change_% does not track Energy_MoM reliably. Drops come with both +10.9 and -5.7, and rises come with +0.6 to +3.9. The apparent link rests mostly on March, a single extreme month (-72.8%, +10.9). stat_large never changes. Energy → All Items is consistent across all months, roughly All ≈ 0.25 + 0.065 × Energy.

#### Reasoning
The October HSAI fall (0.64 → 0.26) is within its counting uncertainty. Ship counts have been near zero since April, so the percentage changes are inflated by tiny bases. Stationary large ships stay at 0. The 0.00 moving share comes from roughly one ship across two images, so I treat it as noise. The shipping evidence is weak and this month's signal is noise, so the Energy forecast shrinks almost fully to the example median of 2.1. I nudged it to 2.0 and gave it a wide range (-3.5 to 7.0), since monthly energy values in the examples run from -5.7 to +10.9.

For headline CPI, the Energy → All Items fit gives 0.25 + 0.065 × 2.0 ≈ 0.38, which rounds to 0.4. That matches the All Items median of 0.4. The range (0.0 to 0.8) scales with the energy range and allows for the residual seen in June.

