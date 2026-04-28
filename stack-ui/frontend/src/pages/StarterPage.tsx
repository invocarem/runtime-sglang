import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl } from "../lib/api";
import {
  DEFAULT_PRESETS_FILE,
  LS_LAUNCH_MODE,
  LS_LAUNCH_PRESET,
  loadStored,
  store,
} from "../lib/storage";

type Props = {
  baseUrl: string;
  apiKey: string;
  onModelsLoaded: (ids: string[]) => void;
};

type ModelsPayload = {
  model_ids: string[];
  upstream: Record<string, unknown>;
};

type PresetSummary = {
  model_path?: string;
  tp?: number;
  port?: number;
  venv_path?: string;
};

type PresetsPayload = {
  presets_file: string;
  preset_names: string[];
  presets: Record<string, PresetSummary>;
  launch_enabled: boolean;
  launch_hint: string;
};

type LaunchMode = "solo" | "cluster";

export default function StarterPage({
  baseUrl,
  apiKey,
  onModelsLoaded,
}: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [stopLoading, setStopLoading] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);

  const [presetsData, setPresetsData] = useState<PresetsPayload | null>(null);
  const [presetsError, setPresetsError] = useState<string | null>(null);
  const [selectedPreset, setSelectedPreset] = useState(() =>
    loadStored(LS_LAUNCH_PRESET, ""),
  );
  const [launchMode, setLaunchMode] = useState<LaunchMode>(() =>
    (loadStored(LS_LAUNCH_MODE, "solo") === "cluster" ? "cluster" : "solo"),
  );
  const [soloHost, setSoloHost] = useState("");
  const [clusterHosts, setClusterHosts] = useState("");
  const [launchLoading, setLaunchLoading] = useState(false);
  const [launchResult, setLaunchResult] = useState<string | null>(null);
  const [launchLogBody, setLaunchLogBody] = useState<string | null>(null);
  const [launchLogPolling, setLaunchLogPolling] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const launchLogPreRef = useRef<HTMLPreElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        base_url: baseUrl,
        api_key: apiKey,
        timeout_sec: "30",
      });
      const resp = await fetch(apiUrl(`/api/models?${qs}`));
      const body: unknown = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const detail =
          typeof body === "object" && body !== null && "detail" in body
            ? String((body as { detail: unknown }).detail)
            : resp.statusText;
        throw new Error(detail);
      }
      const data = body as ModelsPayload;
      const ids = Array.isArray(data.model_ids) ? data.model_ids : [];
      setModels(ids);
      onModelsLoaded(ids);
    } catch (err) {
      setModels([]);
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      onModelsLoaded([]);
    } finally {
      setLoading(false);
    }
  }, [apiKey, baseUrl, onModelsLoaded]);

  const runStop = useCallback(async () => {
    setStopLoading(true);
    setStopError(null);
    try {
      const resp = await fetch(apiUrl("/api/stop"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base_url: baseUrl }),
      });
      const body: unknown = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const detail =
          typeof body === "object" && body !== null && "detail" in body
            ? String((body as { detail: unknown }).detail)
            : resp.statusText;
        throw new Error(detail);
      }
      await refresh();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setStopError(msg);
    } finally {
      setStopLoading(false);
    }
  }, [baseUrl, refresh]);

  const loadPresets = useCallback(async () => {
    setPresetsError(null);
    try {
      const resp = await fetch(apiUrl("/api/presets"));
      const body: unknown = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const detail =
          typeof body === "object" && body !== null && "detail" in body
            ? String((body as { detail: unknown }).detail)
            : resp.statusText;
        throw new Error(detail);
      }
      setPresetsData(body as PresetsPayload);
    } catch (err) {
      setPresetsData(null);
      const msg = err instanceof Error ? err.message : String(err);
      setPresetsError(msg);
    }
  }, []);

  useEffect(() => {
    void loadPresets();
  }, [loadPresets]);

  useEffect(() => {
    store(LS_LAUNCH_PRESET, selectedPreset);
  }, [selectedPreset]);

  useEffect(() => {
    store(LS_LAUNCH_MODE, launchMode);
  }, [launchMode]);

  const fetchLaunchLog = useCallback(async () => {
    try {
      const resp = await fetch(apiUrl("/api/launch-log?tail_bytes=131072"));
      const body: unknown = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const detail =
          typeof body === "object" && body !== null && "detail" in body
            ? String((body as { detail: unknown }).detail)
            : resp.statusText;
        throw new Error(detail);
      }
      const data = body as { content?: string };
      setLaunchLogBody(typeof data.content === "string" ? data.content : "");
    } catch {
      setLaunchLogBody("(could not read launch.log)");
    }
  }, []);

  useEffect(() => {
    if (!launchLogPolling) {
      return;
    }
    let cancelled = false;
    let pollStarted = false;
    let pollId: number | undefined;

    const applyStreamPayload = (raw: string) => {
      try {
        const data = JSON.parse(raw) as { content?: string };
        setLaunchLogBody(typeof data.content === "string" ? data.content : "");
      } catch {
        setLaunchLogBody("(could not read launch.log)");
      }
    };

    const startFallbackPoll = () => {
      if (pollStarted || cancelled) {
        return;
      }
      pollStarted = true;
      void fetchLaunchLog();
      pollId = window.setInterval(() => {
        void fetchLaunchLog();
      }, 500);
    };

    const url = apiUrl("/api/launch-log/stream?tail_bytes=131072");
    const es = new EventSource(url);
    let streamOpened = false;

    const openTimer = window.setTimeout(() => {
      if (!cancelled && !streamOpened && !pollStarted) {
        es.close();
        startFallbackPoll();
      }
    }, 3000);

    es.onopen = () => {
      streamOpened = true;
      window.clearTimeout(openTimer);
    };

    es.onmessage = (ev: MessageEvent<string>) => {
      applyStreamPayload(ev.data);
    };

    es.onerror = () => {
      es.close();
      if (!cancelled) {
        startFallbackPoll();
      }
    };

    return () => {
      cancelled = true;
      window.clearTimeout(openTimer);
      es.close();
      if (pollId !== undefined) {
        window.clearInterval(pollId);
      }
    };
  }, [launchLogPolling, fetchLaunchLog]);

  useEffect(() => {
    const el = launchLogPreRef.current;
    if (el && launchLogBody !== null) {
      el.scrollTop = el.scrollHeight;
    }
  }, [launchLogBody]);

  const summary =
    selectedPreset && presetsData?.presets
      ? presetsData.presets[selectedPreset]
      : undefined;

  async function runLaunch() {
    if (!selectedPreset) {
      setLaunchError("Choose a preset.");
      return;
    }
    setLaunchLoading(true);
    setLaunchError(null);
    setLaunchResult(null);
    setLaunchLogBody(null);
    setLaunchLogPolling(false);
    try {
      const resp = await fetch(apiUrl("/api/launch"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          preset: selectedPreset,
          mode: launchMode,
          host: launchMode === "solo" ? soloHost : "",
          hosts: launchMode === "cluster" ? clusterHosts : "",
        }),
      });
      const body: unknown = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const detail =
          typeof body === "object" && body !== null && "detail" in body
            ? String((body as { detail: unknown }).detail)
            : resp.statusText;
        throw new Error(detail);
      }
      const data = body as {
        pid: number;
        log_file: string;
        note?: string;
      };
      let msg = `Started OS pid ${data.pid}. Combined stdout/stderr: ${data.log_file}`;
      const port = summary?.port;
      if (port != null) {
        const hint = `http://127.0.0.1:${port}`;
        const matchesPort =
          baseUrl.includes(`:${port}`) || baseUrl.includes(`:${port}/`);
        if (!matchesPort) {
          msg += `\nIf this node serves inference at another port, set Benchmark tab Base URL to ${hint} or your URL.`;
        }
      }
      setLaunchResult(msg);
      setLaunchLogPolling(true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setLaunchError(msg);
    } finally {
      setLaunchLoading(false);
    }
  }

  return (
    <div>
      <p className="sub">
        Uses the same inference URL and API key as the Benchmark tab (defaults in{" "}
        <code>http://127.0.0.1:30000</code> and <code>EMPTY</code>).{" "}
        <strong>Refresh models</strong> queries <code>/v1/models</code>.{" "}
        <strong>Stop server</strong> stops local inference: it uses{" "}
        <code>launch.pid</code> after <strong>Launch</strong>, or finds processes listening on
        the Benchmark URL&apos;s TCP port on this machine (hostname in the URL does not matter).
      </p>

      <div className="starter-actions">
        <button type="button" onClick={() => void refresh()} disabled={loading}>
          {loading ? "Loading…" : "Refresh models"}
        </button>
        {models.length > 0 ? (
          <button
            type="button"
            className="btn-danger"
            onClick={() => void runStop()}
            disabled={stopLoading || loading}
          >
            {stopLoading ? "Stopping…" : "Stop server"}
          </button>
        ) : null}
      </div>
      {stopError ? <p className="err">{stopError}</p> : null}

      <h2>Models available</h2>
      {error ? <p className="err">{error}</p> : null}
      {!error && models.length === 0 && !loading ? (
        <p className="muted">Press &quot;Refresh models&quot; to query the server.</p>
      ) : null}
      {models.length > 0 ? (
        <ul className="model-list">
          {models.map((id) => (
            <li key={id}>
              <code>{id}</code>
            </li>
          ))}
        </ul>
      ) : null}
      {models.length === 1 ? (
        <p className="hint">
          The server reports a single model id; use this in the Benchmark tab unless
          you override it.
        </p>
      ) : null}

      <h2 className="section-title">Launch from preset</h2>
      <p className="sub">
        Runs <code>spark_runtime launch --preset …</code> on the machine where this API
        runs (same paths and <code>.env</code> as your shell), using{" "}
        <code>{DEFAULT_PRESETS_FILE}</code> at the repo root. Cluster: provide hosts; solo:
        optional SSH host for remote launch.
      </p>

      {presetsError ? <p className="err">{presetsError}</p> : null}

      {presetsData && (
        <>
          {!presetsData.launch_enabled ? (
            <p className="warn-box">
              Launch is disabled. Start the backend with{" "}
              <code>STACK_UI_ALLOW_LAUNCH=1</code>. {presetsData.launch_hint}
            </p>
          ) : null}

          <label htmlFor="preset_select">Preset</label>
          <select
            id="preset_select"
            value={selectedPreset}
            onChange={(e) => setSelectedPreset(e.target.value)}
          >
            <option value="">— select —</option>
            {presetsData.preset_names.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>

          {summary ? (
            <div className="launch-meta">
              {summary.port != null ? (
                <div>
                  Port: <code>{summary.port}</code>
                </div>
              ) : null}
              {summary.tp != null ? (
                <div>
                  TP: <code>{summary.tp}</code>
                </div>
              ) : null}
              {summary.model_path ? (
                <div>
                  Model path: <code>{summary.model_path}</code>
                </div>
              ) : null}
              {summary.venv_path ? (
                <div>
                  Venv: <code>{summary.venv_path}</code>
                </div>
              ) : null}
            </div>
          ) : null}

          <label htmlFor="launch_mode">Mode</label>
          <select
            id="launch_mode"
            value={launchMode}
            onChange={(e) => setLaunchMode(e.target.value as LaunchMode)}
            disabled={!presetsData.launch_enabled}
          >
            <option value="solo">Solo (this node or one SSH host)</option>
            <option value="cluster">Cluster (multiple hosts)</option>
          </select>

          {launchMode === "solo" ? (
            <>
              <label htmlFor="solo_host">SSH host (optional)</label>
              <input
                id="solo_host"
                value={soloHost}
                onChange={(e) => setSoloHost(e.target.value)}
                placeholder="empty = run locally on this machine"
                autoComplete="off"
                disabled={!presetsData.launch_enabled}
              />
            </>
          ) : (
            <>
              <label htmlFor="cluster_hosts">Hosts (comma-separated)</label>
              <input
                id="cluster_hosts"
                value={clusterHosts}
                onChange={(e) => setClusterHosts(e.target.value)}
                placeholder="spark-01, spark-02"
                autoComplete="off"
                disabled={!presetsData.launch_enabled}
              />
            </>
          )}

          <button
            type="button"
            onClick={() => void runLaunch()}
            disabled={!presetsData.launch_enabled || launchLoading || !selectedPreset}
          >
            {launchLoading ? "Starting…" : "Launch"}
          </button>

          {launchError ? <p className="err">{launchError}</p> : null}
          {launchResult || launchLogBody !== null ? (
            <div className="launch-output">
              {launchResult ? (
                <pre className="launch-pre launch-pre-meta">{launchResult}</pre>
              ) : null}
              {launchLogBody !== null ? (
                <>
                  <div className="launch-log-label">
                    <code>launch.log</code> — live updates (stream, 500ms poll fallback)
                  </div>
                  <pre
                    ref={launchLogPreRef}
                    className="launch-pre launch-pre-log"
                  >
                    {launchLogBody || "…"}
                  </pre>
                </>
              ) : null}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
