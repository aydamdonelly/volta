import { formatInTimeZone } from "date-fns-tz";

export const CET_ZONE = "Europe/Berlin";

export function formatCET(iso: string, fmt: string = "HH:mm"): string {
  try {
    return formatInTimeZone(new Date(iso), CET_ZONE, fmt);
  } catch {
    return iso;
  }
}

export const formatCETDay = (iso: string) => formatCET(iso, "yyyy-MM-dd");
export const formatCETFull = (iso: string) => formatCET(iso, "EEE, MMM d · HH:mm");
