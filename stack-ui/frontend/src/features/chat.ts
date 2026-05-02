import { fetchJson, loadUiConfig } from "../lib/api";
import { assistantTextFromCompletionBody } from "../lib/completion";

type ChatRole = "system" | "user" | "assistant";
type ChatMessage = { role: ChatRole; content: string };

const messagesEl = document.querySelector<HTMLDivElement>("#chat-messages");
const statusEl = document.querySelector<HTMLParagraphElement>("#chat-status");
const modelInput = document.querySelector<HTMLInputElement>("#chat-model");
const inputEl = document.querySelector<HTMLTextAreaElement>("#chat-input");
const btnSend = document.querySelector<HTMLButtonElement>("#chat-send");
const btnClear = document.querySelector<HTMLButtonElement>("#chat-clear");

let history: ChatMessage[] = [];

function setStatus(text: string, isError = false): void {
  if (!statusEl) return;
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function previewResponseShape(body: unknown): string {
  try {
    const serialized = JSON.stringify(body);
    if (!serialized) return "<empty>";
    return serialized.length > 240 ? `${serialized.slice(0, 240)}...` : serialized;
  } catch {
    return "<unserializable>";
  }
}

function renderMessages(): void {
  if (!messagesEl) return;
  if (history.length === 0) {
    messagesEl.innerHTML = '<p class="chat-empty">Send a message to start.</p>';
    return;
  }
  messagesEl.innerHTML = history
    .map((m) => {
      const label = m.role === "user" ? "You" : m.role === "assistant" ? "Assistant" : "System";
      return `<div class="chat-bubble chat-bubble--${m.role}"><span class="chat-bubble__label">${label}</span><div class="chat-bubble__text">${escapeHtml(m.content)}</div></div>`;
    })
    .join("");
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function send(): Promise<void> {
  const model = modelInput?.value.trim() ?? "";
  const text = inputEl?.value.trim() ?? "";
  if (!model) return setStatus("Set model first.", true);
  if (!text) return setStatus("Type a message.", true);
  if (!inputEl || !btnSend) return;

  history = [...history, { role: "user", content: text }];
  inputEl.value = "";
  renderMessages();
  btnSend.disabled = true;
  setStatus("Sending...");

  try {
    const body = await fetchJson<unknown>("/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, messages: history }),
    });
    const answer = assistantTextFromCompletionBody(body);
    if (answer === null) {
      throw new Error(`Unexpected chat response shape: ${previewResponseShape(body)}`);
    }
    history = [...history, { role: "assistant", content: answer }];
    renderMessages();
    setStatus("Done.");
  } catch (e) {
    history = history.slice(0, -1);
    renderMessages();
    setStatus(e instanceof Error ? e.message : String(e), true);
  } finally {
    btnSend.disabled = false;
  }
}

function clear(): void {
  history = [];
  renderMessages();
  setStatus("Cleared.");
}

export function initChat(): void {
  renderMessages();
  btnSend?.addEventListener("click", () => void send());
  btnClear?.addEventListener("click", clear);
  inputEl?.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      void send();
    }
  });
  void (async () => {
    const cfg = await loadUiConfig();
    if (cfg.inferenceBaseUrl) setStatus(`Inference: ${cfg.inferenceBaseUrl}`);
  })();
}
