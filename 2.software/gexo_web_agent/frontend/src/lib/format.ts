export function arrayValue<T>(values: T[] | undefined, index: number): T | undefined {
  return Array.isArray(values) ? values[index] : undefined;
}

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function formatMeasurement(
  value: number | undefined,
  digits: number,
  unit: string,
  fallback = "DATA UNAVAILABLE",
): string {
  return isFiniteNumber(value) ? `${value.toFixed(digits)} ${unit}` : fallback;
}

export function formatPercent(
  value: number | undefined,
  fallback = "DATA UNAVAILABLE",
): string {
  return isFiniteNumber(value) ? `${Math.round(value)}%` : fallback;
}

export function formatAge(ageMs: number | null): string {
  if (!isFiniteNumber(ageMs)) return "--";
  if (ageMs < 1_000) return `${Math.max(0, Math.round(ageMs))} ms`;
  return `${(ageMs / 1_000).toFixed(ageMs < 10_000 ? 1 : 0)} s`;
}

export function missingLabel(hasState: boolean): string {
  return hasState ? "DATA UNAVAILABLE" : "NOT CONNECTED";
}

export function maximum(values: number[] | undefined): number | undefined {
  const finite = values?.filter(isFiniteNumber) ?? [];
  return finite.length > 0 ? Math.max(...finite) : undefined;
}
