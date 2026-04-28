import { serve } from "@hono/node-server";
import { Hono } from "hono";
import { cors } from "hono/cors";
import { registerRuntimeApiRoutes } from "./routes.js";

const app = new Hono();

app.use(
  "*",
  cors({
    origin: "*",
  }),
);

registerRuntimeApiRoutes(app);

const port = Number(process.env.RUNTIME_API_PORT ?? "8788");

serve({ fetch: app.fetch, port }, () => {
  console.log(`SGLang Runtime API listening on http://127.0.0.1:${port}`);
});

