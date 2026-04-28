import { FormEvent, useState } from "react";
import { apiUrl } from "../lib/api";

type BenchmarkResult = {
  successful_requests: number;
  failed_requests: number;
  avg_latency_sec: number;
  p50_latency_sec: number;
  p95_latency_sec: number;
  throughput_rps: number;
};

const DEFAULT_PROMPT = "Write a short haiku about distributed inference.";

type Props = {
  baseUrl: string;
  setBaseUrl: (v: string) => void;
  apiKey: string;
  setApiKey: (v: string) => void;
  model: string;
  setModel: (v: string) => void;
};

export default function BenchmarkPage({
  baseUrl,
  setBaseUrl,
  apiKey,
  setApiKey,
  model,
  setModel,
}: Props) {
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [maxTokens, setMaxTokens] = useState(64);
  const [requests, setRequests] = useState(20);
  const [timeoutSec, setTimeoutSec] = useState(120);
  const [loading, setLoading] = useState(false);
  const [resultText, setResultText] = useState("No run yet.");
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResultText("Running...");
    try {
      const resp = await fetch(apiUrl("/api/benchmark"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: baseUrl,
          api_key: apiKey,
          model,
          prompt,
          max_tokens: maxTokens,
          requests,
          timeout_sec: timeoutSec,
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
      setResultText(JSON.stringify(body as BenchmarkResult, null, 2));
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      setResultText("");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <p className="sub">
        Sends repeated chat completion requests to the inference URL below and prints
        latency stats. Same settings as <code>spark_runtime benchmark</code>.
      </p>

      <form onSubmit={onSubmit}>
        <label htmlFor="bench_base_url">Base URL</label>
        <input
          id="bench_base_url"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          autoComplete="off"
        />

        <label htmlFor="bench_api_key">API key</label>
        <input
          id="bench_api_key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          autoComplete="off"
        />

        <label htmlFor="bench_model">Model</label>
        <input
          id="bench_model"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          autoComplete="off"
        />

        <label htmlFor="bench_prompt">Prompt</label>
        <textarea
          id="bench_prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />

        <label htmlFor="bench_max_tokens">Max tokens</label>
        <input
          id="bench_max_tokens"
          type="number"
          min={1}
          value={maxTokens}
          onChange={(e) => setMaxTokens(Number(e.target.value))}
        />

        <label htmlFor="bench_requests">Requests</label>
        <input
          id="bench_requests"
          type="number"
          min={1}
          value={requests}
          onChange={(e) => setRequests(Number(e.target.value))}
        />

        <label htmlFor="bench_timeout_sec">Timeout (sec)</label>
        <input
          id="bench_timeout_sec"
          type="number"
          min={1}
          value={timeoutSec}
          onChange={(e) => setTimeoutSec(Number(e.target.value))}
        />

        <button type="submit" disabled={loading}>
          {loading ? "Running…" : "Run benchmark"}
        </button>
      </form>

      <h2>Result</h2>
      {error ? <p className="err">{error}</p> : null}
      <pre>{resultText}</pre>
    </div>
  );
}
