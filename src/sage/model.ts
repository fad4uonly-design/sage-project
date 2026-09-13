/**
 * SAGE Model Abstraction
 *
 * Model-agnostic interface. The concrete provider is selected at runtime.
 *
 * Supported providers:
 *   SAGE_MODEL_PROVIDER=ollama  → local Ollama model
 *   OPENAI_API_KEY              → OpenAI
 *   ANTHROPIC_API_KEY           → Anthropic
 *   otherwise                   → stub
 */

export interface ModelMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface ModelResponse {
  content: string;
  modelId: string;
}

export interface ModelProvider {
  id: string;
  complete(
    messages: ModelMessage[],
    systemPrompt?: string
  ): Promise<ModelResponse>;
}

/**
 * Text-model roles have independent configuration so SAGE can evaluate and
 * replace a reasoning or coding model without coupling the application layer
 * to a particular provider. Perception roles will receive their own typed
 * interfaces rather than being forced through a chat-completion API.
 */
export type TextModelRole = "language" | "reasoning" | "coding";

// -- Ollama provider ------------------------------------------------

function ollamaProvider(
  modelId = "gemma3:4b",
  baseUrl = "http://127.0.0.1:11434/v1"
): ModelProvider {
  return {
    id: modelId,

    async complete(messages, systemPrompt) {
      const finalMessages: ModelMessage[] = [
        ...(systemPrompt
          ? [{ role: "system" as const, content: systemPrompt }]
          : []),
        ...messages,
      ];

      const res = await fetch(`${baseUrl}/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: modelId,
          messages: finalMessages,
          temperature: 0.2,
        }),
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(`Ollama error ${res.status}: ${err}`);
      }

      const data = (await res.json()) as {
        model?: string;
        choices?: Array<{
          message?: {
            content?: string;
          };
        }>;
      };

      const content = data.choices?.[0]?.message?.content?.trim();

      if (!content) {
        throw new Error("Ollama returned no response content.");
      }

      return {
        content,
        modelId: data.model ?? modelId,
      };
    },
  };
}

// -- OpenAI provider ------------------------------------------------

function openAIProvider(apiKey: string, modelId = "gpt-5"): ModelProvider {
  return {
    id: modelId,

    async complete(messages, systemPrompt) {
      const input = [
        ...(systemPrompt
          ? [{ role: "developer", content: systemPrompt }]
          : []),
        ...messages,
      ];

      const body = {
        model: modelId,
        input,
      };

      const res = await fetch("https://api.openai.com/v1/responses", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(`OpenAI error ${res.status}: ${err}`);
      }

      const data = (await res.json()) as {
        output_text?: string;
        output?: Array<{
          type?: string;
          content?: Array<{ type?: string; text?: string }>;
        }>;
      };

      const fallbackText = (data.output ?? [])
        .flatMap((item) => item.content ?? [])
        .filter(
          (item) =>
            item.type === "output_text" && typeof item.text === "string"
        )
        .map((item) => item.text as string)
        .join("\n")
        .trim();

      return {
        content: data.output_text?.trim() || fallbackText || "(no response)",
        modelId,
      };
    },
  };
}

// -- Anthropic provider ---------------------------------------------

function anthropicProvider(
  apiKey: string,
  modelId = "claude-3-haiku-20240307"
): ModelProvider {
  return {
    id: modelId,

    async complete(messages, systemPrompt) {
      const body = {
        model: modelId,
        max_tokens: 1024,
        ...(systemPrompt ? { system: systemPrompt } : {}),
        messages,
      };

      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": apiKey,
          "anthropic-version": "2023-06-01",
        },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(`Anthropic error ${res.status}: ${err}`);
      }

      const data = (await res.json()) as {
        content: Array<{ type: string; text: string }>;
      };

      const textBlock = data.content.find((b) => b.type === "text");

      return {
        content: textBlock?.text ?? "(no response)",
        modelId,
      };
    },
  };
}

// -- Stub provider --------------------------------------------------

function stubProvider(): ModelProvider {
  return {
    id: "stub",

    async complete(messages) {
      const lastUser = [...messages]
        .reverse()
        .find((m) => m.role === "user");

      const input = lastUser?.content ?? "";

      return {
        content:
          `[SAGE stub — no model configured]\n\n` +
          `You said: "${input}"`,
        modelId: "stub",
      };
    },
  };
}

// -- Provider selection ---------------------------------------------

const cachedProviders = new Map<TextModelRole, ModelProvider>();

function environmentName(role: TextModelRole, suffix: "PROVIDER" | "MODEL_ID"): string {
  return `SAGE_${role.toUpperCase()}_${suffix}`;
}

export function getModelProvider(role: TextModelRole = "language"): ModelProvider {
  const cached = cachedProviders.get(role);
  if (cached) return cached;

  const provider = (
    process.env[environmentName(role, "PROVIDER")] ??
    process.env.SAGE_MODEL_PROVIDER
  )?.toLowerCase();
  const modelId =
    process.env[environmentName(role, "MODEL_ID")] ??
    process.env.SAGE_MODEL_ID;

  let selected: ModelProvider;

  if (provider === "ollama") {
    selected = ollamaProvider(
      modelId ?? "gemma3:4b",
      process.env.SAGE_OLLAMA_BASE_URL ??
        "http://127.0.0.1:11434/v1"
    );
  } else if (process.env.OPENAI_API_KEY) {
    selected = openAIProvider(
      process.env.OPENAI_API_KEY,
      modelId ?? "gpt-5"
    );
  } else if (process.env.ANTHROPIC_API_KEY) {
    selected = anthropicProvider(
      process.env.ANTHROPIC_API_KEY,
      modelId ?? "claude-3-haiku-20240307"
    );
  } else {
    selected = stubProvider();
  }

  cachedProviders.set(role, selected);
  return selected;
}

