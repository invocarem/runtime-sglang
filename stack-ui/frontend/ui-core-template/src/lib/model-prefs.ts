import { loadUiConfig } from "./api";

const MODEL_KEY = "runtime-ui.preferred-model";
const CHANGE_EVENT = "runtime-ui.preferred-model.change";

export function getPreferredModel(): string {
  try {
    return localStorage.getItem(MODEL_KEY)?.trim() ?? "";
  } catch {
    return "";
  }
}

export function setPreferredModel(model: string): void {
  const value = model.trim();
  try {
    if (value) localStorage.setItem(MODEL_KEY, value);
    else localStorage.removeItem(MODEL_KEY);
  } catch {
    // Ignore storage failures.
  }
  window.dispatchEvent(new CustomEvent<string>(CHANGE_EVENT, { detail: value }));
}

export function onPreferredModelChange(handler: (model: string) => void): void {
  window.addEventListener(CHANGE_EVENT, (ev: Event) => {
    const detail = (ev as CustomEvent<string>).detail;
    handler(typeof detail === "string" ? detail : "");
  });
}

function modelInputs(): HTMLInputElement[] {
  return [
    document.querySelector<HTMLInputElement>("#chat-model"),
    document.querySelector<HTMLInputElement>("#bench-model"),
  ].filter((el): el is HTMLInputElement => el !== null);
}

export function initSharedModelInputs(): void {
  const stored = getPreferredModel();
  const apply = (model: string) => {
    for (const input of modelInputs()) {
      if (input.value !== model) input.value = model;
    }
  };

  apply(stored);
  for (const input of modelInputs()) {
    input.addEventListener("input", () => setPreferredModel(input.value));
  }
  onPreferredModelChange((model) => apply(model));

  void (async () => {
    if (stored) return;
    const config = await loadUiConfig();
    const model = config.defaultModel?.trim() ?? "";
    if (!model) return;
    setPreferredModel(model);
  })();
}
