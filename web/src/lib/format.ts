/** Signed number with a true minus sign, e.g. "+0.42" / "−1.3". */
export function signed(v: number, digits: number): string {
  const fixed = Math.abs(v).toFixed(digits);
  // Avoid "−0.00" for values that round to zero.
  if (Number(fixed) === 0) return `+${fixed}`;
  return `${v >= 0 ? "+" : "−"}${fixed}`;
}

/** "HH:MM:SSZ" from a timestamp. */
export function utcClock(ts: number): string {
  return new Date(ts).toISOString().slice(11, 19) + "Z";
}

