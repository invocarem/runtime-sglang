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

function setStatus(message: string, isError = false): void {
  if (!statusEl) return;
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function renderOutput(value: unknown): void {
  if (!outEl) return;
  outEl.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
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
  const tool = selectEl?.value.trim() ?? "";
  if (!tool) return;
  const rawArgs = argsEl?.value.trim() ?? "";
  let args: Record<string, unknown> = {};
  if (rawArgs) {
    try {
      const parsed = JSON.parse(rawArgs) as unknown;
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setStatus("Args must be a JSON object.", true);
        return;
      }
      args = parsed as Record<string, unknown>;
    } catch {
      setStatus("Invalid args JSON.", true);
      return;
    }
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
  void loadTools();
}
