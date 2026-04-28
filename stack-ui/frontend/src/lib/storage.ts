export const LS_BASE_URL = "stack-ui-base-url";
export const LS_API_KEY = "stack-ui-api-key";
export const LS_MODEL = "stack-ui-model";
export const LS_LAUNCH_PRESET = "stack-ui-launch-preset";
export const LS_LAUNCH_MODE = "stack-ui-launch-mode";

/** Default presets filename; backend resolves relative to repo root. */
export const DEFAULT_PRESETS_FILE = "model_presets.json";

export function loadStored(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

export function store(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}
