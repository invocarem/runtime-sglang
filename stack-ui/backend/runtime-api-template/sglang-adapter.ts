import type { ChatCompletionsRequest } from "./types.js";

const DEFAULT_BASE_URL = process.env.SGLANG_BASE_URL ?? "http://127.0.0.1:30000";
const METRICS_PATH = process.env.SGLANG_METRICS_PATH ?? "/metrics";
const REQUEST_TIMEOUT_MS = Number(process.env.SGLANG_REQUEST_TIMEOUT_MS ?? "120000");
const MODELS_TIMEOUT_MS = Number(process.env.SGLANG_MODELS_TIMEOUT_MS ?? "5000");
const ALLOWED_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);

function assertSafeUrl(urlString: string): URL {
  const u = new URL(urlString);
  if (u.protocol !== "http:" && u.protocol !== "https:") {
    throw new Error("Only http(s) URLs are allowed");
  }
  if (process.env.SGLANG_ALLOW_ANY_HOST === "1") return u;
  if (!ALLOWED_HOSTS.has(u.hostname.toLowerCase())) {
    throw new Error("Host must be localhost/127.0.0.1/::1 (or set SGLANG_ALLOW_ANY_HOST=1)");
  }
  return u;
}

export function getSglangBaseUrl(): string {
  const envUrl = process.env.SGLANG_BASE_URL?.trim() || DEFAULT_BASE_URL;
  return assertSafeUrl(envUrl).origin;
}

export function getSglangMetricsUrl(): string {
  const full = process.env.SGLANG_METRICS_URL?.trim();
  if (full) return assertSafeUrl(full).toString();
  return new URL(METRICS_PATH, `${getSglangBaseUrl()}/`).toString();
}

export type AdapterResult =
  | { ok: true; status: number; body: unknown }
  | { ok: false; error: string; status?: number; bodyPreview?: string };

export async function chatCompletions(body: ChatCompletionsRequest): Promise<AdapterResult> {
  const url = new URL("/v1/chat/completions", `${getSglangBaseUrl()}/`);
  return postJson(url, body, REQUEST_TIMEOUT_MS);
}

export async function listModels(): Promise<AdapterResult> {
  const url = new URL("/v1/models", `${getSglangBaseUrl()}/`);
  return getJson(url, MODELS_TIMEOUT_MS);
}

export async function fetchMetricsText(): Promise<
  | { ok: true; status: number; contentType: string | null; text: string }
  | { ok: false; error: string; status?: number; bodyPreview?: string }
> {
  const url = getSglangMetricsUrl();
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(url, { signal: ac.signal });
    const text = await res.text();
    if (!res.ok) {
      return {
        ok: false,
        error: `SGLang HTTP ${res.status}`,
        status: res.status,
        bodyPreview: text.slice(0, 4000),
      };
    }
    return { ok: true, status: res.status, contentType: res.headers.get("content-type"), text };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  } finally {
    clearTimeout(timer);
  }
}

async function postJson(url: URL, body: unknown, timeoutMs: number): Promise<AdapterResult> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const res = await fetch(url.toString(), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
      signal: ac.signal,
    });
    const text = await res.text();
    let parsed: unknown = null;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      parsed = { raw: text.slice(0, 8000) };
    }
    if (!res.ok) {
      return {
        ok: false,
        error: `SGLang HTTP ${res.status}`,
        status: res.status,
        bodyPreview:
          typeof parsed === "object" && parsed !== null
            ? JSON.stringify(parsed).slice(0, 4000)
            : String(parsed).slice(0, 4000),
      };
    }
    return { ok: true, status: res.status, body: parsed };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  } finally {
    clearTimeout(timer);
  }
}

async function getJson(url: URL, timeoutMs: number): Promise<AdapterResult> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const res = await fetch(url.toString(), {
      headers: { Accept: "application/json" },
      signal: ac.signal,
    });
    const text = await res.text();
    let parsed: unknown = null;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      parsed = { raw: text.slice(0, 8000) };
    }
    if (!res.ok) {
      return {
        ok: false,
        error: `SGLang HTTP ${res.status}`,
        status: res.status,
        bodyPreview: typeof parsed === "string" ? parsed.slice(0, 4000) : JSON.stringify(parsed).slice(0, 4000),
      };
    }
    return { ok: true, status: res.status, body: parsed };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  } finally {
    clearTimeout(timer);
  }
}

