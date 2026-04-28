export function assistantFromCompletionBody(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const root = body as Record<string, unknown>;
  const choices = root.choices;
  if (!Array.isArray(choices) || choices.length === 0) return null;
  const first = choices[0];
  if (!first || typeof first !== "object") return null;
  const message = (first as Record<string, unknown>).message;
  if (!message || typeof message !== "object") return null;
  const content = (message as Record<string, unknown>).content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    const textParts = content
      .map((part) => {
        if (!part || typeof part !== "object") return null;
        const p = part as Record<string, unknown>;
        return p.type === "text" && typeof p.text === "string" ? p.text : null;
      })
      .filter((v): v is string => typeof v === "string");
    return textParts.length > 0 ? textParts.join("") : null;
  }
  return null;
}

