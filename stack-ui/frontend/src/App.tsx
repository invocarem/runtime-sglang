import { useCallback, useEffect, useState } from "react";
import BenchmarkPage from "./pages/BenchmarkPage";
import StarterPage from "./pages/StarterPage";
import {
  LS_API_KEY,
  LS_BASE_URL,
  LS_MODEL,
  loadStored,
  store,
} from "./lib/storage";

type TabId = "starter" | "benchmark";

const DEFAULT_BASE = "http://127.0.0.1:30000";

export default function App() {
  const [tab, setTab] = useState<TabId>("starter");
  const [baseUrl, setBaseUrlState] = useState(DEFAULT_BASE);
  const [apiKey, setApiKeyState] = useState("EMPTY");
  const [model, setModelState] = useState("default");

  useEffect(() => {
    setBaseUrlState(loadStored(LS_BASE_URL, DEFAULT_BASE));
    setApiKeyState(loadStored(LS_API_KEY, "EMPTY"));
    setModelState(loadStored(LS_MODEL, "default"));
  }, []);

  const setBaseUrl = useCallback((v: string) => {
    setBaseUrlState(v);
    store(LS_BASE_URL, v);
  }, []);

  const setApiKey = useCallback((v: string) => {
    setApiKeyState(v);
    store(LS_API_KEY, v);
  }, []);

  const setModel = useCallback((v: string) => {
    setModelState(v);
    store(LS_MODEL, v);
  }, []);

  const onModelsLoaded = useCallback(
    (ids: string[]) => {
      if (ids.length === 1) {
        setModel(ids[0]!);
      }
    },
    [setModel],
  );

  return (
    <div className="page">
      <header className="header">
        <h1>SGLang stack UI</h1>
        <p className="tagline">
          Dev: <code>cd stack-ui && npm run dev</code>. Cluster:{" "}
          <code>STACK_UI_BIND_HOST=0.0.0.0 STACK_UI_EXPOSE_DEV=1 npm run dev</code>
          . Optional <code>VITE_API_URL</code> if UI and API differ.
        </p>
        <nav className="tabs" role="tablist" aria-label="Sections">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "starter"}
            className={tab === "starter" ? "tab active" : "tab"}
            onClick={() => setTab("starter")}
          >
            Starter
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "benchmark"}
            className={tab === "benchmark" ? "tab active" : "tab"}
            onClick={() => setTab("benchmark")}
          >
            Benchmark
          </button>
        </nav>
      </header>

      <section
        className={tab === "starter" ? "tab-panel" : "tab-panel panel-hidden"}
        role="tabpanel"
      >
        <StarterPage
          baseUrl={baseUrl}
          apiKey={apiKey}
          onModelsLoaded={onModelsLoaded}
        />
      </section>

      <section
        className={tab === "benchmark" ? "tab-panel" : "tab-panel panel-hidden"}
        role="tabpanel"
      >
        <BenchmarkPage
          baseUrl={baseUrl}
          setBaseUrl={setBaseUrl}
          apiKey={apiKey}
          setApiKey={setApiKey}
          model={model}
          setModel={setModel}
        />
      </section>
    </div>
  );
}
