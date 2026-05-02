export function assistantTextFromCompletionBody(body: unknown): string | null {
  function objectTextField(item: object, key: string): string {
    const value = (item as Record<string, unknown>)[key];
    return typeof value === "string" ? value : "";
  }

  function contentToText(content: unknown): string | null {
    if (typeof content === "string") return content;
    if (!Array.isArray(content)) return null;
    const parts = content
      .map((item) => {
        if (typeof item === "string") return item;
        if (typeof item !== "object" || item === null) return "";
        return (
          objectTextField(item, "text") ||
          objectTextField(item, "content") ||
          objectTextField(item, "value")
        );
      })
      .filter((part) => part.length > 0);
    return parts.length ? parts.join("") : null;
  }

  if (typeof body !== "object" || body === null) return null;
  const choices = (body as { choices?: unknown }).choices;
  if (!Array.isArray(choices) || choices.length === 0) return null;
  const first = choices[0];
  if (typeof first !== "object" || first === null) return null;

  const message = (first as { message?: unknown }).message;
  if (typeof message === "object" && message !== null) {
    const content = (message as { content?: unknown }).content;
    const text = contentToText(content);
    if (text !== null) return text;
    const reasoning = (message as { reasoning_content?: unknown }).reasoning_content;
    if (typeof reasoning === "string" && reasoning.trim().length > 0) return reasoning;
  }
  const text = (first as { text?: unknown }).text;
  if (typeof text === "string") return text;
  const delta = (first as { delta?: unknown }).delta;
  if (typeof delta === "object" && delta !== null) {
    const deltaContent = (delta as { content?: unknown }).content;
    const deltaText = contentToText(deltaContent);
    if (deltaText !== null) return deltaText;
  }

  const outputText = (body as { output_text?: unknown }).output_text;
  if (typeof outputText === "string") return outputText;

  const output = (body as { output?: unknown }).output;
  if (Array.isArray(output)) {
    const parts = output
      .map((item) => {
        if (typeof item !== "object" || item === null) return "";
        const content = (item as { content?: unknown }).content;
        return contentToText(content) ?? "";
      })
      .filter((part) => part.length > 0);
    if (parts.length) return parts.join("");
  }
  return null;
}
