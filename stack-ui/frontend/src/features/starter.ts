import { fetchJson } from "../lib/api";
import { setPreferredModel } from "../lib/model-prefs";

type HealthResponse = {
  status?: string;
};

type ModelsResponse = {
  data?: Array<{ id?: string }>;
};

const refreshBtn = document.querySelector<HTMLButtonElement>("#starter-refresh");
const stopBtn = document.querySelector<HTMLButtonElement>("#starter-stop");
const statusEl = document.querySelector<HTMLParagraphElement>("#starter-status");
const modelsEl = document.querySelector<HTMLPreElement>("#starter-models");
const presetEl = document.querySelector<HTMLSelectElement>("#starter-preset");
const launchModeEl = document.querySelector<HTMLSelectElement>("#starter-launch-mode");
const soloHostFieldEl = document.querySelector<HTMLElement>("#starter-solo-host-field");
const clusterHostsFieldEl = document.querySelector<HTMLElement>("#starter-cluster-hosts-field");
const soloHostEl = document.querySelector<HTMLInputElement>("#starter-solo-host");
const clusterHostsEl = document.querySelector<HTMLInputElement>("#starter-cluster-hosts");
const launchBtn = document.querySelector<HTMLButtonElement>("#starter-launch");
const launchStatusEl = document.querySelector<HTMLParagraphElement>("#starter-launch-status");
const launchOutputEl = document.querySelector<HTMLPreElement>("#starter-launch-output");

type PresetsResponse = {
  preset_names?: string[];
  launch_enabled?: boolean;
  launch_hint?: string;
};

function setStatus(text: string, isError = false): void {
  if (!statusEl) return;
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

function setLaunchStatus(text: string, isError = false): void {
  if (!launchStatusEl) return;
  launchStatusEl.textContent = text;
  launchStatusEl.classList.toggle("error", isError);
}

function setLaunchOutput(text: string): void {
  if (!launchOutputEl) return;
  launchOutputEl.textContent = text;
}

function setLaunchModeUi(): void {
  const mode = launchModeEl?.value === "cluster" ? "cluster" : "solo";
  const isCluster = mode === "cluster";
  soloHostFieldEl?.classList.toggle("hidden", isCluster);
  clusterHostsFieldEl?.classList.toggle("hidden", !isCluster);
}

async function refresh(): Promise<void> {
  if (!modelsEl || !refreshBtn) return;
  refreshBtn.disabled = true;
  setStatus("Checking /healthz and /v1/models ...");
  try {
    const [health, models] = await Promise.all([
      fetchJson<HealthResponse>("/healthz"),
      fetchJson<ModelsResponse>("/v1/models"),
    ]);

    const ids = Array.isArray(models.data)
      ? models.data
          .map((m) => (typeof m?.id === "string" ? m.id.trim() : ""))
          .filter((id) => id.length > 0)
      : [];

    if (ids.length === 0) {
      modelsEl.textContent = "No models returned from /v1/models.";
    } else {
      modelsEl.textContent = ids.map((id) => `- ${id}`).join("\n");
      if (ids.length === 1) setPreferredModel(ids[0]);
    }
    setStatus(`Runtime ${health.status === "ok" ? "healthy" : "reachable"} · ${ids.length} model(s) found`);
  } catch (e) {
    setStatus(e instanceof Error ? e.message : String(e), true);
    modelsEl.textContent = "Failed to load models.";
  } finally {
    refreshBtn.disabled = false;
  }
}

async function loadPresets(): Promise<void> {
  if (!presetEl || !launchBtn) return;
  setLaunchStatus("Loading presets...");
  try {
    const body = await fetchJson<PresetsResponse>("/api/presets");
    const names = Array.isArray(body.preset_names) ? body.preset_names : [];
    presetEl.innerHTML = "";
    if (names.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(no presets)";
      presetEl.appendChild(opt);
    } else {
      for (const name of names) {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        presetEl.appendChild(opt);
      }
    }
    const enabled = body.launch_enabled !== false;
    launchBtn.disabled = !enabled || names.length === 0;
    setLaunchStatus(enabled ? "Presets loaded." : body.launch_hint ?? "Launch disabled by backend.");
  } catch (e) {
    if (presetEl) {
      presetEl.innerHTML = "";
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(launch API unavailable)";
      presetEl.appendChild(opt);
    }
    if (launchBtn) launchBtn.disabled = true;
    setLaunchStatus(e instanceof Error ? e.message : String(e), true);
  }
}

async function launch(): Promise<void> {
  if (!launchBtn) return;
  const preset = presetEl?.value.trim() ?? "";
  if (!preset) {
    setLaunchStatus("Choose a preset first.", true);
    return;
  }
  const mode = launchModeEl?.value === "cluster" ? "cluster" : "solo";
  const host = soloHostEl?.value.trim() ?? "";
  const hosts = clusterHostsEl?.value.trim() ?? "";

  launchBtn.disabled = true;
  setLaunchStatus("Launching...");
  try {
    const body = await fetchJson<{
      pid?: number;
      log_file?: string;
      note?: string;
    }>("/api/launch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        preset,
        mode,
        host: mode === "solo" ? host : "",
        hosts: mode === "cluster" ? hosts : "",
      }),
    });
    const msg = [
      `Preset: ${preset}`,
      body.pid != null ? `PID: ${body.pid}` : "",
      body.log_file ? `Log file: ${body.log_file}` : "",
      body.note ?? "",
    ]
      .filter(Boolean)
      .join("\n");
    setLaunchOutput(msg || "Launch request succeeded.");
    setLaunchStatus("Launch started.");
  } catch (e) {
    setLaunchStatus(e instanceof Error ? e.message : String(e), true);
  } finally {
    launchBtn.disabled = false;
  }
}

async function stopServer(): Promise<void> {
  if (!stopBtn) return;
  stopBtn.disabled = true;
  setStatus("Stopping server...");
  try {
    await fetchJson<unknown>("/api/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    setStatus("Stop signal sent.");
  } catch (e) {
    setStatus(e instanceof Error ? e.message : String(e), true);
  } finally {
    stopBtn.disabled = false;
  }
}

export function initStarter(): void {
  refreshBtn?.addEventListener("click", () => void refresh());
  stopBtn?.addEventListener("click", () => void stopServer());
  launchModeEl?.addEventListener("change", setLaunchModeUi);
  launchBtn?.addEventListener("click", () => void launch());
  setLaunchModeUi();
  void loadPresets();
  void refresh();
}
