import { VIEWBOX, type LocationConfig, type Point } from "@/config/locations";

/** Point at fraction `t` (0..1) along a polyline, by arc length. */
export function pointAlong(pts: readonly Point[], t: number): Point {
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

/** Heading in degrees (0 = north) of the polyline at fraction `t`. */
export function headingAlong(pts: readonly Point[], t: number): number {
  const a = pointAlong(pts, Math.max(0, t - 0.01));
  const b = pointAlong(pts, Math.min(1, t + 0.01));
  const deg = (Math.atan2(b[0] - a[0], a[1] - b[1]) * 180) / Math.PI;
  return (deg + 360) % 360;
}

/** ViewBox → lon/lat using the location's bbox. */
export function toLonLat(loc: LocationConfig, [x, y]: Point): { lon: number; lat: number } {
  const [w, s, e, n] = loc.bbox;
  return {
    lon: w + ((x - VIEWBOX.x) / VIEWBOX.width) * (e - w),
    lat: n - ((y - VIEWBOX.y) / VIEWBOX.height) * (n - s),
  };
}

/** lon/lat → viewBox using the location's bbox. */
export function toViewBox(loc: LocationConfig, lon: number, lat: number): Point {
  const [w, s, e, n] = loc.bbox;
  return [VIEWBOX.x + ((lon - w) / (e - w)) * VIEWBOX.width, VIEWBOX.y + ((n - lat) / (n - s)) * VIEWBOX.height];
}

/** ViewBox point → % offsets inside the map box. */
export function toPercent([x, y]: Point): { left: number; top: number } {
  return {
    left: ((x - VIEWBOX.x) / VIEWBOX.width) * 100,
    top: ((y - VIEWBOX.y) / VIEWBOX.height) * 100,
  };
}

export function polylinePath(pts: readonly Point[]): string {
  return pts.map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join(" ");
}
