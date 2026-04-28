import { assistantFromCompletionBody } from "./openai-completion-text.js";
import {
  chatCompletions,
  fetchMetricsText,
  getSglangBaseUrl,
  getSglangMetricsUrl,
  listModels,
} from "./sglang-adapter.js";
import type { ChatCompletionsRequest, ChatMessage, TaskCase, TaskChecker } from "./types.js";

const MAX_METRICS_CHARS = Number(process.env.RUNTIME_METRICS_MAX_CHARS ?? "256000");
const MAX_HIGHLIGHT_LINES = Number(process.env.RUNTIME_METRICS_HIGHLIGHT_LINES ?? "500");
const MAX_BENCHMARK_REQUESTS = Number(process.env.RUNTIME_BENCHMARK_MAX_REQUESTS ?? "300");
const MAX_BENCHMARK_CONCURRENCY = Number(process.env.RUNTIME_BENCHMARK_MAX_CONCURRENCY ?? "64");

function isPlainObject(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

function isChatMessage(x: unknown): x is ChatMessage {
  if (!isPlainObject(x)) return false;
  if (x.role !== "system" && x.role !== "user" && x.role !== "assistant") return false;
  return typeof x.content === "string";
}

export function parseChatBody(body: unknown): ChatCompletionsRequest | null {
  if (!isPlainObject(body)) return null;
  if (typeof body.model !== "string" || !body.model.trim()) return null;
  if (!Array.isArray(body.messages) || body.messages.length === 0 || !body.messages.every(isChatMessage)) {
    return null;
  }
  if (body.temperature !== undefined && typeof body.temperature !== "number") return null;
  if (body.max_tokens !== undefined && (typeof body.max_tokens !== "number" || body.max_tokens <= 0)) {
    return null;
  }
  if (body.top_p !== undefined && typeof body.top_p !== "number") return null;
  if (body.separate_reasoning !== undefined && typeof body.separate_reasoning !== "boolean") return null;
  if (body.chat_template_kwargs !== undefined && !isPlainObject(body.chat_template_kwargs)) return null;
  return body as ChatCompletionsRequest;
}

export async function handleChat(body: unknown) {
  const parsed = parseChatBody(body);
  if (!parsed) {
    return {
      ok: false as const,
      status: 400,
      error: "Expected { model, messages[] } plus optional generation params",
    };
  }
  return chatCompletions(parsed);
}

export async function handleHealth() {
  const res = await listModels();
  if (!res.ok) return { ok: false as const, status: res.status ?? 502, error: res.error };
  return { ok: true as const, status: 200, body: { status: "ok", baseUrl: getSglangBaseUrl() } };
}

export async function handleModels() {
  return listModels();
}

export async function handleMetrics() {
  const res = await fetchMetricsText();
  if (!res.ok) return res;
  const lines = res.text.split(/\r?\n/).filter((line) => line.toLowerCase().includes("sglang"));
  return {
    ok: true as const,
    status: 200,
    body: {
      url: getSglangMetricsUrl(),
      fetchedAt: new Date().toISOString(),
      highlightLines: lines.slice(0, MAX_HIGHLIGHT_LINES),
      rawPreview: res.text.slice(0, MAX_METRICS_CHARS),
      rawTruncated: res.text.length > MAX_METRICS_CHARS,
      contentType: res.contentType,
    },
  };
}

type LoadBenchmarkReq = {
  model: string;
  message: string;
  concurrency: number;
  requests: number;
  max_tokens?: number;
};

function parseLoadBenchmarkBody(body: unknown): LoadBenchmarkReq | null {
  if (!isPlainObject(body)) return null;
  if (typeof body.model !== "string" || !body.model.trim()) return null;
  if (typeof body.message !== "string" || !body.message.trim()) return null;
  if (typeof body.concurrency !== "number" || !Number.isFinite(body.concurrency)) return null;
  if (typeof body.requests !== "number" || !Number.isFinite(body.requests)) return null;
  if (body.max_tokens !== undefined && (typeof body.max_tokens !== "number" || body.max_tokens <= 0)) {
    return null;
  }
  return body as LoadBenchmarkReq;
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const idx = Math.ceil((p / 100) * sorted.length) - 1;
  return sorted[Math.max(0, Math.min(sorted.length - 1, idx))];
}

export async function handleLoadBenchmark(body: unknown) {
  const parsed = parseLoadBenchmarkBody(body);
  if (!parsed) {
    return {
      ok: false as const,
      status: 400,
      error: "Expected { model, message, concurrency, requests, optional max_tokens }",
    };
  }
  const req = parsed;
  const requests = Math.max(1, Math.floor(req.requests));
  const concurrency = Math.max(1, Math.floor(req.concurrency));
  if (requests > MAX_BENCHMARK_REQUESTS) {
    return { ok: false as const, status: 400, error: `requests must be <= ${MAX_BENCHMARK_REQUESTS}` };
  }
  if (concurrency > MAX_BENCHMARK_CONCURRENCY) {
    return { ok: false as const, status: 400, error: `concurrency must be <= ${MAX_BENCHMARK_CONCURRENCY}` };
  }

  const latenciesMs: number[] = [];
  const errors: string[] = [];
  let success = 0;
  let fail = 0;
  let index = 0;
  let sampleContent: string | null = null;

  async function worker() {
    while (true) {
      const current = index++;
      if (current >= requests) return;
      const t0 = Date.now();
      const res = await chatCompletions({
        model: req.model,
        messages: [{ role: "user", content: req.message }],
        max_tokens: req.max_tokens,
        separate_reasoning: false,
        chat_template_kwargs: { enable_thinking: false },
      });
      latenciesMs.push(Date.now() - t0);
      if (res.ok) {
        success += 1;
        if (current === 0) sampleContent = assistantFromCompletionBody(res.body);
      } else {
        fail += 1;
        if (errors.length < 8) errors.push(res.error);
      }
    }
  }

  const workers = Math.min(requests, concurrency);
  const started = Date.now();
  await Promise.all(Array.from({ length: workers }, () => worker()));
  const wallTimeMs = Date.now() - started;
  const sorted = [...latenciesMs].sort((a, b) => a - b);
  const throughputRps = wallTimeMs > 0 ? success / (wallTimeMs / 1000) : 0;
  return {
    ok: true as const,
    status: 200,
    body: {
      model: req.model,
      requests,
      concurrency: workers,
      successes: success,
      failures: fail,
      wallTimeMs,
      p50: percentile(sorted, 50),
      p95: percentile(sorted, 95),
      p99: percentile(sorted, 99),
      throughputRps,
      errorSamples: errors,
      sampleContent,
    },
  };
}

type TaskBenchmarkReq = {
  model: string;
  tasks: TaskCase[];
  temperature?: number;
  max_tokens?: number;
};

function isTaskChecker(x: unknown): x is TaskChecker {
  if (!isPlainObject(x) || typeof x.type !== "string") return false;
  if (x.type === "regex") return typeof x.pattern === "string";
  if (x.type === "contains") return typeof x.value === "string";
  if (x.type === "contains_all") return Array.isArray(x.values) && x.values.every((v) => typeof v === "string");
  return false;
}

function isTaskCase(x: unknown): x is TaskCase {
  if (!isPlainObject(x)) return false;
  return (
    typeof x.id === "string" &&
    typeof x.category === "string" &&
    typeof x.prompt === "string" &&
    (x.system === undefined || typeof x.system === "string") &&
    isTaskChecker(x.checker)
  );
}

function parseTaskBenchmarkBody(body: unknown): TaskBenchmarkReq | null {
  if (!isPlainObject(body)) return null;
  if (typeof body.model !== "string" || !body.model.trim()) return null;
  if (!Array.isArray(body.tasks) || body.tasks.length === 0 || !body.tasks.every(isTaskCase)) return null;
  if (body.temperature !== undefined && typeof body.temperature !== "number") return null;
  if (body.max_tokens !== undefined && (typeof body.max_tokens !== "number" || body.max_tokens <= 0)) return null;
  return body as TaskBenchmarkReq;
}

function runTaskChecker(text: string, checker: TaskChecker): { ok: boolean; reason: string } {
  if (checker.type === "regex") {
    try {
      const flags = typeof checker.flags === "string" ? checker.flags : "";
      const re = new RegExp(checker.pattern, flags);
      return re.test(text) ? { ok: true, reason: "regex ok" } : { ok: false, reason: "regex did not match" };
    } catch (e) {
      return { ok: false, reason: e instanceof Error ? e.message : String(e) };
    }
  }
  if (checker.type === "contains") {
    const hay = checker.case_insensitive ? text.toLowerCase() : text;
    const needle = checker.case_insensitive ? checker.value.toLowerCase() : checker.value;
    return hay.includes(needle) ? { ok: true, reason: "contains ok" } : { ok: false, reason: "missing substring" };
  }
  const hay = checker.case_insensitive ? text.toLowerCase() : text;
  for (const v of checker.values) {
    const needle = checker.case_insensitive ? v.toLowerCase() : v;
    if (!hay.includes(needle)) return { ok: false, reason: `missing ${needle}` };
  }
  return { ok: true, reason: "contains_all ok" };
}

export async function handleTaskBenchmark(body: unknown) {
  const parsed = parseTaskBenchmarkBody(body);
  if (!parsed) {
    return {
      ok: false as const,
      status: 400,
      error: "Expected { model, tasks[], optional temperature/max_tokens }",
    };
  }
  const temperature = parsed.temperature ?? 0.2;
  const max_tokens = parsed.max_tokens ?? 1024;

  const byCategory: Record<string, { pass: number; fail: number }> = {};
  const results: Array<{ id: string; category: string; ok: boolean; reason: string; latencyMs: number }> = [];
  const started = Date.now();

  for (const t of parsed.tasks) {
    const messages: ChatMessage[] = [];
    if (t.system?.trim()) messages.push({ role: "system", content: t.system.trim() });
    messages.push({ role: "user", content: t.prompt.trim() });
    const t0 = Date.now();
    const res = await chatCompletions({
      model: parsed.model,
      messages,
      temperature,
      max_tokens,
      separate_reasoning: false,
      chat_template_kwargs: { enable_thinking: false },
    });
    const latencyMs = Date.now() - t0;
    const bucket = byCategory[t.category] ?? { pass: 0, fail: 0 };
    byCategory[t.category] = bucket;

    if (!res.ok) {
      bucket.fail += 1;
      results.push({ id: t.id, category: t.category, ok: false, reason: res.error, latencyMs });
      continue;
    }

    const output = assistantFromCompletionBody(res.body) ?? "";
    const checked = runTaskChecker(output, t.checker);
    if (checked.ok) bucket.pass += 1;
    else bucket.fail += 1;
    results.push({ id: t.id, category: t.category, ok: checked.ok, reason: checked.reason, latencyMs });
  }

  const passed = results.filter((r) => r.ok).length;
  return {
    ok: true as const,
    status: 200,
    body: {
      model: parsed.model,
      cases: results.length,
      passed,
      failed: results.length - passed,
      passRate: results.length > 0 ? Number((passed / results.length).toFixed(4)) : 0,
      wallTimeMs: Date.now() - started,
      byCategory,
      results,
    },
  };
}

