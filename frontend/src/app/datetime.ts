/**
 * Parse timestamps returned by NOVA APIs.
 *
 * Backend resource timestamps are stored as naive UTC datetimes. When an
 * API timestamp has no explicit timezone suffix, treat it as UTC instead of
 * allowing the browser to interpret it as local wall-clock time.
 */
export function parseApiDateTime(value: string): Date {
  const normalized = value.trim()
  if (!normalized) return new Date(NaN)

  const hasExplicitTimezone =
    /(?:[zZ]|[+-]\d{2}:\d{2})$/.test(normalized)

  return new Date(
    hasExplicitTimezone
      ? normalized
      : normalized + "Z",
  )
}
