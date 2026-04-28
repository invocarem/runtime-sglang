export type ChatRole = "system" | "user" | "assistant";

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type ChatCompletionsRequest = {
  model: string;
  messages: ChatMessage[];
  temperature?: number;
  max_tokens?: number;
  top_p?: number;
  separate_reasoning?: boolean;
  chat_template_kwargs?: Record<string, unknown>;
};

export type TaskChecker =
  | { type: "regex"; pattern: string; flags?: string }
  | { type: "contains"; value: string; case_insensitive?: boolean }
  | { type: "contains_all"; values: string[]; case_insensitive?: boolean };

export type TaskCase = {
  id: string;
  category: string;
  prompt: string;
  system?: string;
  checker: TaskChecker;
};

