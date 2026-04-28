import { fetchJson } from "../lib/api";

type ToolDef = {
  id: string;
  label: string;
  description?: string;
};

type ToolsResponse = {
  tools: ToolDef[];
};

type ToolRunResponse = {
  ok: boolean;
  output?: unknown;
  error?: string;
};

const selectEl = document.querySelector<HTMLSelectElement>("#tools-select");
const argsEl = document.querySelector<HTMLTextAreaElement>("#tools-args");
const runEl = document.querySelector<HTMLButtonElement>("#tools-run");
const statusEl = document.querySelector<HTMLParagraphElement>("#tools-status");
const outEl = document.querySelector<HTMLPreElement>("#tools-output");
const benchmarkFieldsEl = document.querySelector<HTMLElement>("#tools-benchmark-load-fields");
const benchModelEl = document.querySelector<HTMLInputElement>("#tools-bench-model");
const benchBaseUrlEl = document.querySelector<HTMLInputElement>("#tools-bench-base-url");
const benchBackendEl = document.querySelector<HTMLInputElement>("#tools-bench-backend");
const benchDatasetEl = document.querySelector<HTMLInputElement>("#tools-bench-dataset");
const benchNumPromptsEl = document.querySelector<HTMLInputElement>("#tools-bench-num-prompts");
const benchRandomInputLenEl = document.querySelector<HTMLInputElement>("#tools-bench-random-input-len");
const benchRandomOutputLenEl = document.querySelector<HTMLInputElement>("#tools-bench-random-output-len");
const benchMaxConcurrencyEl = document.querySelector<HTMLInputElement>("#tools-bench-max-concurrency");
const benchHfModelEl = document.querySelector<HTMLInputElement>("#tools-bench-hf-model");
const benchTokenizerEl = document.querySelector<HTMLInputElement>("#tools-bench-tokenizer");
const benchExtraBodyEl = document.querySelector<HTMLTextAreaElement>("#tools-bench-extra-request-body");

function setStatus(message: string, isError = false): void {
  if (!statusEl) return;
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function renderOutput(value: unknown): void {
  if (!outEl) return;
  outEl.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function selectedTool(): string {
  return selectEl?.value.trim() ?? "";
}

function parseIntField(el: HTMLInputElement | null): number | undefined {
  const raw = el?.value.trim() ?? "";
  if (!raw) return undefined;
  const value = Number(raw);
  if (!Number.isFinite(value)) return undefined;
  return Math.trunc(value);
}

function parseJsonObjectField(raw: string): Record<string, unknown> | undefined {
  const trimmed = raw.trim();
  if (!trimmed) return undefined;
  const parsed = JSON.parse(trimmed) as unknown;
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("Extra request body must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

function buildBenchmarkLoadArgs(): Record<string, unknown> {
  const args: Record<string, unknown> = {};
  const strFields: Array<[HTMLInputElement | null, string]> = [
    [benchModelEl, "model"],
    [benchBaseUrlEl, "base_url"],
    [benchBackendEl, "backend"],
    [benchDatasetEl, "dataset_name"],
    [benchHfModelEl, "hf_model"],
    [benchTokenizerEl, "tokenizer"],
  ];
  for (const [el, key] of strFields) {
    const value = el?.value.trim() ?? "";
    if (value) args[key] = value;
  }
  const hfModel = typeof args.hf_model === "string" ? args.hf_model.trim() : "";
  if (hfModel && !args.tokenizer) {
    args.tokenizer = hfModel;
  }
  const intFields: Array<[HTMLInputElement | null, string]> = [
    [benchNumPromptsEl, "num_prompts"],
    [benchRandomInputLenEl, "random_input_len"],
    [benchRandomOutputLenEl, "random_output_len"],
    [benchMaxConcurrencyEl, "max_concurrency"],
  ];
  for (const [el, key] of intFields) {
    const value = parseIntField(el);
    if (value !== undefined) args[key] = value;
  }
  const extra = parseJsonObjectField(benchExtraBodyEl?.value ?? "");
  if (extra) args.extra_request_body = extra;
  return args;
}

function setToolUi(): void {
  const useForm = selectedTool() === "benchmark_load";
  benchmarkFieldsEl?.classList.toggle("hidden", !useForm);
  argsEl?.closest(".field")?.classList.toggle("hidden", useForm);
}

async function loadTools(): Promise<void> {
  if (!selectEl) return;
  try {
    const body = await fetchJson<ToolsResponse>("/api/tools/definitions");
    const tools = Array.isArray(body.tools) ? body.tools : [];
    selectEl.innerHTML = "";
    if (tools.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(no tools exposed)";
      selectEl.appendChild(opt);
      setStatus("No tools exposed by backend.");
      return;
    }
    for (const t of tools) {
      const opt = document.createElement("option");
      opt.value = t.id;
      opt.textContent = t.description ? `${t.label} - ${t.description}` : t.label;
      selectEl.appendChild(opt);
    }
    setStatus(`Loaded ${tools.length} tool(s).`);
  } catch {
    selectEl.innerHTML = "";
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "(tools API not available)";
    selectEl.appendChild(opt);
    setStatus("Tools API not available. Implement /api/tools/definitions and /api/tools/run.");
  }
}

async function runTool(): Promise<void> {
  const tool = selectedTool();
  if (!tool) return;
  let args: Record<string, unknown> = {};
  try {
    if (tool === "benchmark_load") {
      args = buildBenchmarkLoadArgs();
    } else {
      const rawArgs = argsEl?.value.trim() ?? "";
      if (rawArgs) {
        const parsed = JSON.parse(rawArgs) as unknown;
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          setStatus("Args must be a JSON object.", true);
          return;
        }
        args = parsed as Record<string, unknown>;
      }
    }
  } catch (e) {
    setStatus(e instanceof Error ? e.message : "Invalid JSON.", true);
    return;
  }
  if (!runEl) return;
  runEl.disabled = true;
  setStatus(`Running ${tool}...`);
  try {
    const body = await fetchJson<ToolRunResponse>("/api/tools/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tool, args }),
    });
    if (!body.ok) {
      setStatus(body.error ?? "Tool failed.", true);
      renderOutput(body);
      return;
    }
    renderOutput(body.output ?? body);
    setStatus("Done.");
  } catch (e) {
    setStatus(e instanceof Error ? e.message : String(e), true);
  } finally {
    runEl.disabled = false;
  }
}

export function initTools(): void {
  runEl?.addEventListener("click", () => void runTool());
  selectEl?.addEventListener("change", setToolUi);
  setToolUi();
  void loadTools();
}
