# CPI forecast: 2026-01

## Forecast
| Indicator | Forecast MoM % | 80% range |
|---|---|---|
| Energy | 1.5 | -3.0 to 6.0 |
| All Items | 0.3 | -0.1 to 0.7 |

## Shipping signal
- HSAI change: -23.1% (signal vs noise: noise)
- Stationary large ships: 0.26 → 0.0
- Moving share: 0.96

## Relationship found in the examples
Strength: weak

Shipping → Energy: no consistent relationship. HSAI declines go with both big rises (Mar +10.9, Sep +5.2) and falls (Jun -5.7, Jul -1.5). After March, most HSAI levels sit within their uncertainty. Energy → All Items is strong and consistent across all eight months (All ≈ 0.19 + 0.078 × Energy). The extremes in March and June help set the slope, but the middle months fit it too.

## Reasoning
The HSAI drop of 1.47 ships per image (6.36 → 4.89) is smaller than its uncertainty of ±1.5, so it is noise. The move in stationary large ships (0.26 → 0) is tiny, and the moving share of 0.96 is normal. That means there is no usable shipping signal, and shipping features predict Energy poorly in the examples anyway. The Energy forecast is therefore shrunk toward the example median of 2.95. It is also pulled down toward the closest analog, February (high HSAI, moving share 0.97, Energy +0.6), which gives 1.5. The range is wide (±4.5) because Energy swings a lot in the examples. All Items comes from the fitted link: 0.19 + 0.078 × 1.5 ≈ 0.3. That is close to the example median of 0.45, and the range is about a tenth as wide as Energy's, consistent with the slope.
