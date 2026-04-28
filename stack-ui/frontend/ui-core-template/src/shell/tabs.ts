type TabId = "tools" | "metrics" | "benchmark";

type TabsOptions = {
  onMetricsTabSelect: () => void | Promise<void>;
};

export function initShellTabs(options: TabsOptions): void {
  const tabTools = document.querySelector<HTMLButtonElement>("#tab-tools");
  const tabMetrics = document.querySelector<HTMLButtonElement>("#tab-metrics");
  const tabBenchmark = document.querySelector<HTMLButtonElement>("#tab-benchmark");
  const panelTools = document.querySelector<HTMLDivElement>("#panel-tools");
  const panelMetrics = document.querySelector<HTMLDivElement>("#panel-metrics");
  const panelBenchmark = document.querySelector<HTMLDivElement>("#panel-benchmark");

  function selectTab(which: TabId): void {
    const toolsOn = which === "tools";
    const metricsOn = which === "metrics";
    const benchmarkOn = which === "benchmark";

    tabTools?.setAttribute("aria-selected", toolsOn ? "true" : "false");
    tabMetrics?.setAttribute("aria-selected", metricsOn ? "true" : "false");
    tabBenchmark?.setAttribute("aria-selected", benchmarkOn ? "true" : "false");

    panelTools?.classList.toggle("hidden", !toolsOn);
    panelMetrics?.classList.toggle("hidden", !metricsOn);
    panelBenchmark?.classList.toggle("hidden", !benchmarkOn);
    if (panelTools) panelTools.hidden = !toolsOn;
    if (panelMetrics) panelMetrics.hidden = !metricsOn;
    if (panelBenchmark) panelBenchmark.hidden = !benchmarkOn;

    if (metricsOn) {
      void options.onMetricsTabSelect();
    }
  }

  tabTools?.addEventListener("click", () => selectTab("tools"));
  tabMetrics?.addEventListener("click", () => selectTab("metrics"));
  tabBenchmark?.addEventListener("click", () => selectTab("benchmark"));

  selectTab("tools");
}
