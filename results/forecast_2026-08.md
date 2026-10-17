# CPI forecast: 2026-08

## Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 1.5 | -3.5 to 6.0 |
| All Items | 0.3 | -0.1 to 0.7 |

## Shipping signal
- HSAI change: 234.6% (signal vs noise: noise)
- Stationary large ships: 0.0 → 0.0
- Moving share: 0.83

## Relationship found in the examples
Strength: weak

Shipping → Energy is weak. The one clear case is March: a big HSAI drop (-73%) came with Energy at +10.9. Other drops came with negative Energy (June, July), and a rise came with +3.9 (May). Stat_large is flat at 0. Energy → All Items is strong and consistent: roughly All ≈ 0.15 + 0.08 × Energy, across all eight months, not just the extremes.

## Reasoning
HSAI went from 0.26 to 0.87 ships per image. That is +235%, but the absolute rise of 0.61 is about the same as the counting uncertainty (±0.6), so I treat it as noise. Since April, ship counts have stayed close to zero, and month-to-month changes there have not mapped reliably to Energy (+3.9, -5.7, -1.5, +5.2). Stationary large ships stayed at 0. The moving share of 0.83 is below 1.0. In the examples, lower moving shares (March 0.75, September 0.6) came with positive Energy, which hints at a small upside, but it is not reliable. So I shrink most of the way toward the Energy median of 2.2, nudged down slightly because the May/June/July months near zero ships averaged negative. That gives Energy 1.5, with a wide range for Energy's volatility (-5.7 to +10.9 in the examples). All Items comes from the Energy → headline fit: 0.15 + 0.08 × 1.5 ≈ 0.3. This is close to the All Items median of 0.4.
