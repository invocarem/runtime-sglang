export function assistantTextFromCompletionBody(body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;
  const choices = (body as { choices?: unknown }).choices;
  if (!Array.isArray(choices) || choices.length === 0) return null;
  const first = choices[0];
  if (typeof first !== "object" || first === null) return null;

  const message = (first as { message?: unknown }).message;
  if (typeof message === "object" && message !== null) {
    const content = (message as { content?: unknown }).content;
    if (typeof content === "string") return content;
  }
  const text = (first as { text?: unknown }).text;
  if (typeof text === "string") return text;
  return null;
}
