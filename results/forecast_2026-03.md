# CPI forecast: 2026-03

## Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 1.8 | -2.5 to 5.5 |
| All Items | 0.4 | 0.0 to 0.7 |

## Shipping signal
- HSAI change: -72.8% (signal vs noise: moderate)
- Stationary large ships: 0.0 → 0.0
- Moving share: 0.75

## Relationship found in the examples
Strength: weak

There is no consistent link from shipping to Energy. HSAI fell in Jan, Apr, Jun, Jul and Sep, and Energy came in at +0.6, +3.8, -5.7, -1.5 and +5.2. stat_large is almost always 0. Energy to All Items is strong and holds across all eight months, not just one or two extremes: All Items ≈ 0.2 + 0.09 × Energy.

## Reasoning
HSAI dropped from 7.71 to 2.1. That is a fall of 5.6 ships per image against an uncertainty of 1.8, so it is larger than the noise. It still counts only as moderate because there were just 2 images and stat_large did not change. The closest example is April (-92%), which had Energy +3.8. But June (-46%) and July (-40%) also fell and had negative Energy, so a lower HSAI does not reliably mean higher energy prices. With the shipping-to-Energy link this weak, I shrank the forecast most of the way toward the Energy median of the examples (1.35), leaving a small upward tilt for the large drop and the lower moving share (0.75). That gives 1.8. The range is wide (-2.5 to 5.5) because Energy in the examples runs from -5.7 to +5.2. Feeding 1.8 into the Energy-to-All Items fit gives 0.2 + 0.09 × 1.8 ≈ 0.36, which rounds to 0.4. That matches the All Items median of 0.35, and I used a proportionally narrower range of 0.0 to 0.7.
