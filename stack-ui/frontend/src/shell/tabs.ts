type TabId = "starter" | "logs" | "tools" | "metrics" | "benchmark";

type TabsOptions = {
  onMetricsTabSelect: () => void | Promise<void>;
  onLogsTabSelect: () => void | Promise<void>;
};

export function initShellTabs(options: TabsOptions): void {
  const tabStarter = document.querySelector<HTMLButtonElement>("#tab-starter");
  const tabLogs = document.querySelector<HTMLButtonElement>("#tab-logs");
  const tabTools = document.querySelector<HTMLButtonElement>("#tab-tools");
  const tabMetrics = document.querySelector<HTMLButtonElement>("#tab-metrics");
  const tabBenchmark = document.querySelector<HTMLButtonElement>("#tab-benchmark");
  const panelStarter = document.querySelector<HTMLDivElement>("#panel-starter");
  const panelLogs = document.querySelector<HTMLDivElement>("#panel-logs");
  const panelTools = document.querySelector<HTMLDivElement>("#panel-tools");
  const panelMetrics = document.querySelector<HTMLDivElement>("#panel-metrics");
  const panelBenchmark = document.querySelector<HTMLDivElement>("#panel-benchmark");

  function selectTab(which: TabId): void {
    const starterOn = which === "starter";
    const logsOn = which === "logs";
    const toolsOn = which === "tools";
    const metricsOn = which === "metrics";
    const benchmarkOn = which === "benchmark";

    tabStarter?.setAttribute("aria-selected", starterOn ? "true" : "false");
    tabLogs?.setAttribute("aria-selected", logsOn ? "true" : "false");
    tabTools?.setAttribute("aria-selected", toolsOn ? "true" : "false");
    tabMetrics?.setAttribute("aria-selected", metricsOn ? "true" : "false");
    tabBenchmark?.setAttribute("aria-selected", benchmarkOn ? "true" : "false");

    panelStarter?.classList.toggle("hidden", !starterOn);
    panelLogs?.classList.toggle("hidden", !logsOn);
    panelTools?.classList.toggle("hidden", !toolsOn);
    panelMetrics?.classList.toggle("hidden", !metricsOn);
    panelBenchmark?.classList.toggle("hidden", !benchmarkOn);
    if (panelStarter) panelStarter.hidden = !starterOn;
    if (panelLogs) panelLogs.hidden = !logsOn;
    if (panelTools) panelTools.hidden = !toolsOn;
    if (panelMetrics) panelMetrics.hidden = !metricsOn;
    if (panelBenchmark) panelBenchmark.hidden = !benchmarkOn;

    if (logsOn) {
      void options.onLogsTabSelect();
    }
    if (metricsOn) {
      void options.onMetricsTabSelect();
    }
  }

  tabStarter?.addEventListener("click", () => selectTab("starter"));
  tabLogs?.addEventListener("click", () => selectTab("logs"));
  tabTools?.addEventListener("click", () => selectTab("tools"));
  tabMetrics?.addEventListener("click", () => selectTab("metrics"));
  tabBenchmark?.addEventListener("click", () => selectTab("benchmark"));

  selectTab("starter");
}
