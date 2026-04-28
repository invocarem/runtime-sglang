import { fetchJson, loadUiConfig } from "../lib/api";

type MetricsOk = {
  ok: true;
  highlightLines: string[];
  rawPreview: string;
  rawTruncated?: boolean;
  fetchedAt?: string;
};

type MetricsErr = {
  ok: false;
  error: string;
  bodyPreview?: string;
};

const metricsConfigEl = document.querySelector<HTMLParagraphElement>("#metrics-config");
const btnRefresh = document.querySelector<HTMLButtonElement>("#btn-metrics-refresh");
const selInterval = document.querySelector<HTMLSelectElement>("#sel-metrics-interval");
const statusEl = document.querySelector<HTMLParagraphElement>("#status-metrics");
const highlightsEl = document.querySelector<HTMLPreElement>("#metrics-highlights");
const rawEl = document.querySelector<HTMLPreElement>("#metrics-raw");
const chkRaw = document.querySelector<HTMLInputElement>("#chk-metrics-raw");

let timer: ReturnType<typeof setInterval> | null = null;
let loadedOnce = false;

function setStatus(message: string, isError = false): void {
  if (!statusEl) return;
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function refreshRawVisibility(): void {
  if (!rawEl || !chkRaw) return;
  rawEl.classList.toggle("hidden", !chkRaw.checked);
}

async function fetchMetrics(): Promise<void> {
  if (!highlightsEl || !rawEl) return;
  setStatus("Fetching metrics...");
  if (btnRefresh) btnRefresh.disabled = true;
  try {
    const body = await fetchJson<MetricsOk | MetricsErr>("/api/metrics");
    if (!body.ok) {
      highlightsEl.textContent = body.bodyPreview
        ? `Error: ${body.error}\n\n${body.bodyPreview}`
        : `Error: ${body.error}`;
      rawEl.textContent = "—";
      setStatus(body.error, true);
      return;
    }
    const lines = body.highlightLines ?? [];
    highlightsEl.textContent = lines.length > 0 ? lines.join("\n") : "(No highlighted metrics lines.)";
    rawEl.textContent = body.rawTruncated ? `${body.rawPreview}\n\n--- truncated ---` : body.rawPreview;
    refreshRawVisibility();
    setStatus(`OK${body.fetchedAt ? ` - ${body.fetchedAt}` : ""}`);
  } catch (e) {
    setStatus(e instanceof Error ? e.message : String(e), true);
  } finally {
    if (btnRefresh) btnRefresh.disabled = false;
  }
}

function restartPolling(): void {
  if (timer !== null) clearInterval(timer);
  timer = null;
  const ms = Number(selInterval?.value ?? "0");
  if (!Number.isFinite(ms) || ms <= 0) return;
  timer = setInterval(() => void fetchMetrics(), ms);
}

export async function loadMetricsOnceForSession(): Promise<void> {
  if (loadedOnce) {
    restartPolling();
    return;
  }
  loadedOnce = true;
  const cfg = await loadUiConfig();
  if (metricsConfigEl) {
    const parts = [cfg.metricsUrl ? `Metrics URL: ${cfg.metricsUrl}` : "", cfg.inferenceBaseUrl ? `Inference: ${cfg.inferenceBaseUrl}` : ""].filter(Boolean);
    metricsConfigEl.textContent = parts.join(" · ");
  }
  await fetchMetrics();
  restartPolling();
}

export function initMetrics(): void {
  btnRefresh?.addEventListener("click", () => void fetchMetrics());
  selInterval?.addEventListener("change", () => {
    restartPolling();
    if (Number(selInterval.value) > 0) void fetchMetrics();
  });
  chkRaw?.addEventListener("change", refreshRawVisibility);
}
