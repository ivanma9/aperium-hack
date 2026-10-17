# CPI forecast: 2026-10

## Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 2.0 | -3.5 to 7.0 |
| All Items | 0.4 | 0.0 to 0.8 |

## Shipping signal
- HSAI change: -59.4% (signal vs noise: noise. The absolute drop of 0.38 is smaller than unc 0.5, and HSAI is near the floor.)
- Stationary large ships: 0.0 → 0.0
- Moving share: 0.00 (based on about 0.5 ships per image across only 2 images, so it carries no real information)

## Relationship found in the examples
Strength: weak (shipping → Energy); strong (Energy → All Items)

HSAI_change_% does not track Energy_MoM reliably. Drops come with both +10.9 and -5.7, and rises come with +0.6 to +3.9. The apparent link rests mostly on March, a single extreme month (-72.8%, +10.9). stat_large never changes. Energy → All Items is consistent across all months, roughly All ≈ 0.25 + 0.065 × Energy.

## Reasoning
The October HSAI fall (0.64 → 0.26) is within its counting uncertainty. Ship counts have been near zero since April, so the percentage changes are inflated by tiny bases. Stationary large ships stay at 0. The 0.00 moving share comes from roughly one ship across two images, so I treat it as noise. The shipping evidence is weak and this month's signal is noise, so the Energy forecast shrinks almost fully to the example median of 2.1. I nudged it to 2.0 and gave it a wide range (-3.5 to 7.0), since monthly energy values in the examples run from -5.7 to +10.9.

For headline CPI, the Energy → All Items fit gives 0.25 + 0.065 × 2.0 ≈ 0.38, which rounds to 0.4. That matches the All Items median of 0.4. The range (0.0 to 0.8) scales with the energy range and allows for the residual seen in June.
