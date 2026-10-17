# CPI forecast: 2026-06

## Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 1.5 | -2.0 to 5.5 |
| All Items | 0.3 | 0.1 to 0.6 |

## Shipping signal
- HSAI change: -46.3% (signal vs noise: noise; 0.80 → 0.43 is a 0.37 drop, smaller than unc ±0.5)
- Stationary large ships: 0.0 → 0.0
- Moving share: 1.00

## Relationship found in the examples
Strength: weak

HSAI_change_% does not predict Energy consistently. Drops came with -1.5 to 10.9, and rises came with 0.6 to 3.9. The apparent link depends on one extreme month, March (-72.8% → 10.9). stat_large hardly varies. In contrast, Energy → All Items is strong across all 8 months: All ≈ 0.22 + 0.07 × Energy.

## Reasoning
The target's HSAI fall happens at a very low level (below 1 ship per image), and the change is within the counting uncertainty. Stationary ships stay at zero and every ship is moving, so the shipping signal is noise. The closest example is July (-39.5%, 0.43 → 0.26, moving share 1.0, 4 images), which had Energy -1.5. The median Energy across the examples is about 3.0, and May (the month before) was 3.9. Because the signal is noise, I weighted the July analogue against the median and its neighbours and landed at 1.5. Energy swings a lot, so the range is wide (-2.0 to 5.5). For headline, I applied the Energy → All Items fit: 0.22 + 0.07 × 1.5 ≈ 0.33, giving 0.3. The same fit maps the Energy range to roughly 0.1 to 0.6. That forecast sits near the headline median (0.45) and is consistent with the Energy forecast.
