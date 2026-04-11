/**
 * AI backend abstraction for PulseCoach addon.
 *
 * Supports three backends:
 * 1. ha_conversation — Uses HA Conversation API (requires a conversation agent in HA)
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
// conversation agent is configured (OpenAI, Google, Claude, local LLM, etc.)
// Docs: https://developers.home-assistant.io/docs/api/rest/#post-apiconversationprocess
//
// NOTE: Requires a conversation agent to be configured in Home Assistant.
// If no agent is available, the function returns a friendly error message
// instead of throwing, so callers can degrade gracefully.

async function haConversationChat(messages: ChatMessage[]): Promise<string> {
  const token = process.env.SUPERVISOR_TOKEN;
  const baseUrl = process.env.HA_BASE_URL ?? "http://supervisor/core";

  if (!token) {
    console.warn("[ai-backend] No SUPERVISOR_TOKEN available — AI chat unavailable");
    return "AI coaching is not available: No Home Assistant Supervisor token found. " +
      "Please ensure the addon has 'homeassistant_api: true' in config.json. " +
      "Rules-based insights on the Insights page are always available.";
  }

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
        // Use the default conversation agent configured in HA
        agent_id: null,
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const text = await response.text();
      console.error(`[ai-backend] HA Conversation API error ${response.status}: ${text}`);
      return "AI coaching is temporarily unavailable. " +
        "Please check that a conversation agent (e.g. OpenAI, Claude, or a local LLM) " +
        "is configured in Home Assistant under Settings → Voice Assistants. " +
        "Rules-based insights on the Insights page are always available.";
    }

    const data = (await response.json()) as {
      response: {
        speech: { plain: { speech: string } };
        response_type: string;
      };
    };

    if (data.response?.response_type === "error") {
      console.warn("[ai-backend] HA Conversation returned an error response — no agent may be configured");
      return "AI coaching is not available: No conversation agent is configured in Home Assistant. " +
        "To enable AI coaching, install a conversation agent (e.g. OpenAI, Claude, or a local LLM) " +
        "under Settings → Voice Assistants. " +
        "Rules-based insights on the Insights page are always available.";
    }

    return (
      data.response?.speech?.plain?.speech ??
      "I couldn't generate a response. Please try again."
    );
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      console.error("[ai-backend] HA Conversation API request timed out");
      return "AI coaching request timed out. The conversation agent may be slow or unavailable. " +
        "Rules-based insights on the Insights page are always available.";
    }
    console.error("[ai-backend] HA Conversation API request failed:", err);
    return "AI coaching is temporarily unavailable. " +
      "Please check that a conversation agent is configured in Home Assistant. " +
      "Rules-based insights on the Insights page are always available.";
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
