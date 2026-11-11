/** "8 min 30 s", "45 s", "1 h 5 min". */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds))
  if (s < 60) return `${s} s`
  const minutes = Math.floor(s / 60)
  const seconds = s % 60
  if (minutes < 60) return seconds ? `${minutes} min ${seconds} s` : `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours} h ${rest} min` : `${hours} h`
}

/** Rounded for a calm countdown: "about 8 min", "under a minute". */
export function formatEta(seconds: number | null): string {
  if (seconds == null) return ''
  if (seconds < 60) return 'under a minute'
  const minutes = Math.round(seconds / 60)
  return `about ${minutes} min`
}
