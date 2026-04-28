import { initBenchmark } from "../features/benchmark";
import { initChat } from "../features/chat";
import { initMetrics, loadMetricsOnceForSession } from "../features/metrics";
import { initTools } from "../features/tools";
import { initShellTabs } from "../shell/tabs";
import { initSharedModelInputs } from "../lib/model-prefs";

export function initApp(): void {
  initShellTabs({
    onMetricsTabSelect: () => void loadMetricsOnceForSession(),
  });
  initSharedModelInputs();
  initTools();
  initMetrics();
  initChat();
  initBenchmark();
}
