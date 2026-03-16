/**
 * AI backend abstraction for GarminCoach addon.
 *
 * Supports three backends:
 * 1. ha_conversation — Uses HA Conversation API (OpenClaw/Claude/etc)
 * 2. ollama — Direct Ollama HTTP API (local LLM)
 * 3. none — Rules-based fallback (no LLM)
 *
 * The addon run script sets AI_BACKEND, SUPERVISOR_TOKEN, HA_BASE_URL,
 * OLLAMA_URL, and OLLAMA_MODEL as environment variables.
 */

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface AiBackendOptions {
  temperature?: number;
  maxTokens?: number;
}

/**
 * Send a chat completion request to the configured AI backend.
 * Returns the assistant's response text.
 */
export async function aiChat(
  messages: ChatMessage[],
  options?: AiBackendOptions,
): Promise<string> {
  const backend = process.env.AI_BACKEND ?? "none";

  switch (backend) {
    case "ha_conversation":
      return haConversationChat(messages);
    case "ollama":
      return ollamaChat(messages, options);
    default:
      throw new Error("NO_AI_BACKEND");
  }
}

/**
 * Check if an AI backend is available.
 */
export function isAiAvailable(): boolean {
  return (process.env.AI_BACKEND ?? "none") !== "none";
}

// ─── HA Conversation API ─────────────────────────────────────────────────────
// Uses the Home Assistant Conversation API which routes to whatever
// conversation agent is configured (OpenClaw, Google, OpenAI, etc.)
// Docs: https://developers.home-assistant.io/docs/api/rest/#post-apiconversationprocess

async function haConversationChat(messages: ChatMessage[]): Promise<string> {
  const token = process.env.SUPERVISOR_TOKEN;
  const baseUrl = process.env.HA_BASE_URL ?? "http://supervisor/core";

  if (!token) throw new Error("No SUPERVISOR_TOKEN available");

  // The HA Conversation API takes a single text input (not a message array).
  // We combine the system prompt + user messages into one structured prompt.
  const systemMsg = messages.find((m) => m.role === "system");
  const userMsgs = messages.filter((m) => m.role !== "system");
  const lastUserMsg = userMsgs.at(-1);

  // Build a structured prompt that includes context + question
  const prompt = [
    systemMsg
      ? `[CONTEXT]\n${systemMsg.content}\n[/CONTEXT]\n`
      : "",
    // Include recent conversation history for continuity
    ...userMsgs.slice(0, -1).map((m) =>
      m.role === "user" ? `User: ${m.content}` : `Assistant: ${m.content}`,
    ),
    // The actual question
    lastUserMsg?.content ?? "Hello",
  ]
    .filter(Boolean)
    .join("\n\n");

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120_000);

  try {
    const response = await fetch(`${baseUrl}/api/conversation/process`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text: prompt,
        language: "en",
        // Use the default conversation agent (OpenClaw in your case)
        agent_id: null,
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`HA API ${response.status}: ${text}`);
    }

    const data = (await response.json()) as {
      response: {
        speech: { plain: { speech: string } };
        response_type: string;
      };
    };

    return (
      data.response?.speech?.plain?.speech ??
      "I couldn't generate a response. Please try again."
    );
  } finally {
    clearTimeout(timeout);
  }
}

// ─── Ollama API ──────────────────────────────────────────────────────────────

async function ollamaChat(
  messages: ChatMessage[],
  options?: AiBackendOptions,
): Promise<string> {
  const model = process.env.OLLAMA_MODEL ?? "gpt-oss:20b";
  const url = process.env.OLLAMA_URL ?? "http://localhost:11434";

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120_000);

  try {
    const response = await fetch(`${url}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        messages,
        stream: false,
        options: {
          temperature: options?.temperature ?? 0.7,
          num_predict: options?.maxTokens ?? 1024,
        },
      }),
      signal: controller.signal,
    });

    if (!response.ok) throw new Error(`Ollama ${response.status}`);
    const data = (await response.json()) as {
      message?: { content?: string };
    };
    return data.message?.content ?? "";
  } finally {
    clearTimeout(timeout);
  }
}
