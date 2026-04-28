import { fetchJson } from "../lib/api";

type LoadResult = {
  ok: true;
  model: string;
  wallTimeMs: number;
  requests: number;
  concurrency: number;
  successes: number;
  failures: number;
  p50: number;
  p95: number;
  p99: number;
  throughputRps: number;
  errorSamples?: string[];
  sampleContent?: string | null;
};

type TaskResult = {
  ok: true;
  model: string;
  input: string;
  wallTimeMs: number;
  cases: number;
  passed: number;
  failed: number;
  passRate: number;
};

const modelEl = document.querySelector<HTMLInputElement>("#bench-model");
const modeEl = document.querySelector<HTMLSelectElement>("#bench-mode");
const messageEl = document.querySelector<HTMLTextAreaElement>("#bench-message");
const concurrencyEl = document.querySelector<HTMLInputElement>("#bench-concurrency");
const requestsEl = document.querySelector<HTMLInputElement>("#bench-requests");
const maxTokensEl = document.querySelector<HTMLInputElement>("#bench-max-tokens");
const taskInputEl = document.querySelector<HTMLInputElement>("#bench-task-input");
const taskTempEl = document.querySelector<HTMLInputElement>("#bench-task-temperature");
const taskMaxTokensEl = document.querySelector<HTMLInputElement>("#bench-task-max-tokens");
const loadMessageFieldEl = document.querySelector<HTMLElement>("#bench-load-message-field");
const loadControlsEl = document.querySelector<HTMLElement>("#bench-load-controls");
const taskControlsEl = document.querySelector<HTMLElement>("#bench-task-controls");
const btnRun = document.querySelector<HTMLButtonElement>("#bench-run");
const statusEl = document.querySelector<HTMLParagraphElement>("#bench-status");
const resultsEl = document.querySelector<HTMLPreElement>("#bench-results");

function mode(): "load" | "task" {
  return modeEl?.value === "task" ? "task" : "load";
}

function setStatus(text: string, isError = false): void {
  if (!statusEl) return;
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

function setModeUi(): void {
  const task = mode() === "task";
  loadMessageFieldEl?.classList.toggle("hidden", task);
  loadControlsEl?.classList.toggle("hidden", task);
  taskControlsEl?.classList.toggle("hidden", !task);
}

function formatLoadResult(r: LoadResult): string {
  const lines = [
    `Model: ${r.model}`,
    `Wall time: ${r.wallTimeMs} ms`,
    `Requests: ${r.requests} · Concurrency: ${r.concurrency}`,
    `Successes: ${r.successes} · Failures: ${r.failures}`,
    `Throughput: ${r.throughputRps.toFixed(2)} req/s`,
    `Latency p50/p95/p99: ${r.p50}/${r.p95}/${r.p99} ms`,
  ];
  if (Array.isArray(r.errorSamples) && r.errorSamples.length > 0) {
    lines.push("", "Error samples:", ...r.errorSamples.map((e) => `- ${e}`));
  }
  if (typeof r.sampleContent === "string" && r.sampleContent) {
    lines.push("", "Sample assistant reply:", r.sampleContent);
  }
  return lines.join("\n");
}

function formatTaskResult(r: TaskResult): string {
  return [
    `Model: ${r.model}`,
    `Input: ${r.input}`,
    `Wall time: ${r.wallTimeMs} ms`,
    `Cases: ${r.cases} · Passed: ${r.passed} · Failed: ${r.failed}`,
    `Pass rate: ${(r.passRate * 100).toFixed(2)}%`,
  ].join("\n");
}

async function run(): Promise<void> {
  if (!btnRun || !resultsEl) return;
  const m = modelEl?.value.trim() ?? "";
  if (!m) return setStatus("Set model first.", true);

  btnRun.disabled = true;
  resultsEl.textContent = "";
  setStatus("Running...");

  try {
    if (mode() === "load") {
      const message = messageEl?.value.trim() ?? "";
      const concurrency = Number(concurrencyEl?.value ?? "4");
      const requests = Number(requestsEl?.value ?? "20");
      const max_tokens = Number(maxTokensEl?.value ?? "256");
      const result = await fetchJson<LoadResult>("/api/benchmark", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: m, message, concurrency, requests, max_tokens }),
      });
      resultsEl.textContent = formatLoadResult(result);
      setStatus("Done.");
    } else {
      const input = taskInputEl?.value.trim() ?? "";
      const temperature = Number(taskTempEl?.value ?? "0.2");
      const max_tokens = Number(taskMaxTokensEl?.value ?? "1024");
      const result = await fetchJson<TaskResult>("/api/benchmark/task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: m, input, temperature, max_tokens }),
      });
      resultsEl.textContent = formatTaskResult(result);
      setStatus("Done.");
    }
  } catch (e) {
    setStatus(e instanceof Error ? e.message : String(e), true);
  } finally {
    btnRun.disabled = false;
  }
}

export function initBenchmark(): void {
  btnRun?.addEventListener("click", () => void run());
  modeEl?.addEventListener("change", setModeUi);
  setModeUi();
}
