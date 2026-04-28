import { apiUrl } from "../lib/api";

const connectBtn = document.querySelector<HTMLButtonElement>("#logs-connect");
const disconnectBtn = document.querySelector<HTMLButtonElement>("#logs-disconnect");
const clearBtn = document.querySelector<HTMLButtonElement>("#logs-clear");
const sourceEl = document.querySelector<HTMLSelectElement>("#logs-source");
const hostFieldEl = document.querySelector<HTMLElement>("#logs-host-field");
const nodeFieldEl = document.querySelector<HTMLElement>("#logs-node-field");
const hostEl = document.querySelector<HTMLInputElement>("#logs-host");
const nodeRankEl = document.querySelector<HTMLInputElement>("#logs-node-rank");
const statusEl = document.querySelector<HTMLParagraphElement>("#logs-status");
const outEl = document.querySelector<HTMLPreElement>("#logs-output");

let eventSource: EventSource | null = null;
let pollTimer: ReturnType<typeof setInterval> | null = null;
let connectedOnce = false;

function setStatus(text: string, isError = false): void {
  if (!statusEl) return;
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

function setOutput(text: string): void {
  if (!outEl) return;
  outEl.textContent = text;
  outEl.scrollTop = outEl.scrollHeight;
}

function disconnect(): void {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function sourceMode(): "local" | "cluster" {
  return sourceEl?.value === "cluster" ? "cluster" : "local";
}

function queryFor(mode: "local" | "cluster"): string {
  if (mode === "local") return "tail_bytes=131072";
  const host = (hostEl?.value.trim() || "spark1");
  const nodeRank = Math.max(0, Number(nodeRankEl?.value ?? "0") || 0);
  return `host=${encodeURIComponent(host)}&node_rank=${nodeRank}&tail_bytes=131072`;
}

function streamPath(mode: "local" | "cluster"): string {
  return mode === "local" ? "/api/launch-log/stream" : "/api/cluster-log/stream";
}

function pollPath(mode: "local" | "cluster"): string {
  return mode === "local" ? "/api/launch-log" : "/api/cluster-log";
}

function refreshSourceUi(): void {
  const cluster = sourceMode() === "cluster";
  hostFieldEl?.classList.toggle("hidden", !cluster);
  nodeFieldEl?.classList.toggle("hidden", !cluster);
}

function applyPayload(raw: string): void {
  try {
    const parsed = JSON.parse(raw) as { content?: unknown };
    if (typeof parsed.content === "string") {
      setOutput(parsed.content);
      return;
    }
  } catch {
    // fall through
  }
  setOutput(raw);
}

async function pollOnce(): Promise<void> {
  const mode = sourceMode();
  try {
    const res = await fetch(apiUrl(`${pollPath(mode)}?${queryFor(mode)}`));
    const text = await res.text();
    if (!res.ok) {
      setStatus(`Polling error: HTTP ${res.status}`, true);
      return;
    }
    applyPayload(text);
    setStatus(`Connected via polling (${mode}).`);
  } catch (e) {
    setStatus(e instanceof Error ? e.message : String(e), true);
  }
}

function startPolling(): void {
  if (pollTimer) return;
  void pollOnce();
  pollTimer = setInterval(() => void pollOnce(), 1000);
}

function connect(): void {
  const mode = sourceMode();
  disconnect();
  setStatus(`Connecting to ${mode} log stream...`);
  const es = new EventSource(apiUrl(`${streamPath(mode)}?${queryFor(mode)}`));
  eventSource = es;

  let opened = false;
  const fallbackTimer = window.setTimeout(() => {
    if (!opened) {
      es.close();
      eventSource = null;
      startPolling();
    }
  }, 3000);

  es.onopen = () => {
    opened = true;
    clearTimeout(fallbackTimer);
    setStatus(`Connected to live stream (${mode}).`);
  };

  es.onmessage = (ev: MessageEvent<string>) => {
    applyPayload(ev.data);
  };

  es.onerror = () => {
    clearTimeout(fallbackTimer);
    es.close();
    eventSource = null;
    startPolling();
  };
}

export function loadLogsOnceForSession(): void {
  if (connectedOnce) return;
  connectedOnce = true;
  connect();
}

export function initLogs(): void {
  sourceEl?.addEventListener("change", refreshSourceUi);
  refreshSourceUi();
  connectBtn?.addEventListener("click", connect);
  disconnectBtn?.addEventListener("click", () => {
    disconnect();
    setStatus("Disconnected.");
  });
  clearBtn?.addEventListener("click", () => {
    setOutput("No logs yet.");
  });
}
