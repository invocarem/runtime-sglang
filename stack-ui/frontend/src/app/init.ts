import { initBenchmark } from "../features/benchmark";
import { initChat } from "../features/chat";
import { initLogs, loadLogsOnceForSession } from "../features/logs";
import { initMetrics, loadMetricsOnceForSession } from "../features/metrics";
import { initStarter } from "../features/starter";
import { initTools } from "../features/tools";
import { initShellTabs } from "../shell/tabs";
import { initSharedModelInputs } from "../lib/model-prefs";

export function initApp(): void {
  initShellTabs({
    onMetricsTabSelect: () => void loadMetricsOnceForSession(),
    onLogsTabSelect: () => loadLogsOnceForSession(),
  });
  initSharedModelInputs();
  initStarter();
  initLogs();
  initTools();
  initMetrics();
  initChat();
  initBenchmark();
}
