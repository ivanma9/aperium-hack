# CPI forecast: 2026-09

## Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 1.2 | -3.0 to 5.0 |
| All Items | 0.3 | -0.1 to 0.6 |

## Shipping signal
- HSAI change: -26.4% (signal vs noise: noise)
- Stationary large ships: 0.0 → 0.0
- Moving share: 0.60

## Relationship found in the examples
Strength: weak

The link from shipping to Energy is inconsistent. The large Energy spike (+10.9) comes with the March HSAI collapse, but drops of similar size give -5.7 and -1.5, and rises give +3.9 and +2.1. So it rests mostly on one extreme month. Energy → All Items is strong and consistent: All ≈ 0.18 + 0.08 × Energy.

## Reasoning
HSAI fell from 0.87 to 0.64, a change of -0.23. That is smaller than its ±0.4 uncertainty, and the base is near zero, so the -26.4% is noise. Stationary large ships stayed at zero. A moving share of 0.60 is the lowest in the sample, which hints at slower traffic. But with only about 0.6 ships per image, that ratio is very noisy. It gets only a slight nudge, and no clear queuing signal is present.

With a weak relationship and no real signal, the Energy forecast is pulled toward the example median of 1.35. I set it at 1.2. The range is wide, because Energy in the examples ran from -5.7 to +10.9.

All Items comes from the fitted Energy link: 0.18 + 0.08 × 1.2 ≈ 0.28, which rounds to 0.3. That matches the example median of 0.35. Its range follows from the Energy range, with some extra width for error in the fit.
