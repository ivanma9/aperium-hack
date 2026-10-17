import type { LonLat } from "@/lib/geographies";

/** Point at fraction `t` (0..1) along a [lon, lat] polyline, by (planar) arc length. */
export function pointAlong(pts: readonly LonLat[], t: number): LonLat {
  const segs: number[] = [];
  let total = 0;
  for (let i = 1; i < pts.length; i++) {
    const l = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    segs.push(l);
    total += l;
  }
  let d = t * total;
  for (let i = 0; i < segs.length; i++) {
    if (d <= segs[i]) {
      const f = segs[i] === 0 ? 0 : d / segs[i];
      return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f];
    }
    d -= segs[i];
  }
  return pts[pts.length - 1];
}

/** True heading in degrees (0 = north) of the polyline at fraction `t`. */
export function headingAlong(pts: readonly LonLat[], t: number): number {
  const a = pointAlong(pts, Math.max(0, t - 0.01));
  const b = pointAlong(pts, Math.min(1, t + 0.01));
  const east = (b[0] - a[0]) * Math.cos((((a[1] + b[1]) / 2) * Math.PI) / 180);
  const north = b[1] - a[1];
  return ((Math.atan2(east, north) * 180) / Math.PI + 360) % 360;
}
