import type { Hono } from "hono";
import type { ContentfulStatusCode } from "hono/utils/http-status";
import {
  handleChat,
  handleHealth,
  handleLoadBenchmark,
  handleMetrics,
  handleModels,
  handleTaskBenchmark,
} from "./services.js";

async function parseJson(c: { req: { json: () => Promise<unknown> } }) {
  try {
    return { ok: true as const, body: await c.req.json() };
  } catch {
    return { ok: false as const, error: "Invalid JSON body" };
  }
}

export function registerRuntimeApiRoutes(app: Hono): void {
  app.get("/healthz", async (c) => {
    const res = await handleHealth();
    if (!res.ok) return c.json({ error: res.error }, (res.status ?? 502) as ContentfulStatusCode);
    return c.json(res.body, 200);
  });

  app.get("/v1/models", async (c) => {
    const res = await handleModels();
    if (!res.ok) return c.json({ error: res.error }, (res.status ?? 502) as ContentfulStatusCode);
    return c.json(res.body, res.status as ContentfulStatusCode);
  });

  app.get("/v1/metrics", async (c) => {
    const res = await handleMetrics();
    if (!res.ok) return c.json({ error: res.error, detail: res.bodyPreview }, (res.status ?? 502) as ContentfulStatusCode);
    return c.json(res.body, 200);
  });

  app.post("/v1/chat/completions", async (c) => {
    const body = await parseJson(c);
    if (!body.ok) return c.json({ error: body.error }, 400);
    const res = await handleChat(body.body);
    if (!res.ok) return c.json({ error: res.error, detail: res.bodyPreview }, (res.status ?? 502) as ContentfulStatusCode);
    return c.json(res.body, res.status as ContentfulStatusCode);
  });

  app.post("/v1/benchmark/load", async (c) => {
    const body = await parseJson(c);
    if (!body.ok) return c.json({ error: body.error }, 400);
    const res = await handleLoadBenchmark(body.body);
    if (!res.ok) return c.json({ error: res.error }, res.status as ContentfulStatusCode);
    return c.json(res.body, 200);
  });

  app.post("/v1/benchmark/task", async (c) => {
    const body = await parseJson(c);
    if (!body.ok) return c.json({ error: body.error }, 400);
    const res = await handleTaskBenchmark(body.body);
    if (!res.ok) return c.json({ error: res.error }, res.status as ContentfulStatusCode);
    return c.json(res.body, 200);
  });
}

