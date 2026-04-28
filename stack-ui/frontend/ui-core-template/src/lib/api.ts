export async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(`Non-JSON response from ${url}: ${text.slice(0, 180)}`);
  }
  if (!res.ok) {
    const msg =
      typeof body === "object" && body !== null && "error" in body
        ? String((body as { error: unknown }).error)
        : `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return body as T;
}

export type UiConfig = {
  inferenceBaseUrl?: string;
  metricsUrl?: string;
  defaultModel?: string;
  error?: string;
};

export async function loadUiConfig(): Promise<UiConfig> {
  try {
    return await fetchJson<UiConfig>("/api/config");
  } catch {
    return {};
  }
}
