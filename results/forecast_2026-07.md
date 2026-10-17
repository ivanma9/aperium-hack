# CPI forecast: 2026-07

## Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 2.8 | -3.5 to 8.0 |
| All Items | 0.4 | -0.1 to 0.8 |

## Shipping signal
- HSAI change: -39.5% (signal vs noise: noise)
- Stationary large ships: 0.0 → 0.0
- Moving share: 1.00

## Relationship found in the examples
Strength: weak

Shipping → Energy is weak and inconsistent. The large energy jump (+10.9) follows the only big drop from a high HSAI level (March). Similar percentage drops later go with energy readings of -5.7 to +5.2, so this link rests on one month. Energy → All Items is strong and steady across all eight months: All Items ≈ 0.18 + 0.079 × Energy.

## Reasoning
HSAI fell from 0.43 to 0.26, a drop of 0.17 ships per image. That is well inside the ±0.5 counting uncertainty. Stationary large ships stayed at zero and moving share is 1.00, so there is no sign of queuing. The -39.5% change is noise caused by the very low ship counts, not a real signal. Since April, when counts became this low, Energy has ranged from -5.7 to +5.2 with no clear link to HSAI. So I shrink the Energy forecast almost fully to the typical value of the examples (median 2.95, mean 2.7), giving 2.8. The range is wide because Energy has a spread of about ±5 pts in the examples. For All Items, I use the fitted Energy → All Items line: 0.18 + 0.079 × 2.8 ≈ 0.40. This matches the example median of 0.45. Applying the same line to the Energy range gives roughly -0.1 to 0.8, so the two forecasts are consistent.
