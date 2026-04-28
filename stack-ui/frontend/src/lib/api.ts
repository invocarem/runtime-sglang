/** Prefix for calling stack-ui backend (empty = same origin / Vite proxy). */
export function apiUrl(path: string): string {
  const base = import.meta.env.VITE_API_URL?.replace(/\/$/, "") ?? "";
  return `${base}${path}`;
}
