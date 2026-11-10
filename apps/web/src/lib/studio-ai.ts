import type { AgAiEvent, AgLlmAdapter, AgLlmResponse } from "ag-studio";

// AG's agent loop runs locally; only its bounded provider turns go to our API.
export const studioAdapter: AgLlmAdapter = {
  executeTurn(request, options) {
    const complete = fetch("/api/v1/studio/turn", {
      method: "POST", credentials: "include", signal: options?.signal,
      headers: { "content-type": "application/json" }, body: JSON.stringify(request),
    }).then(async (response): Promise<AgLlmResponse> => {
      const body = await response.json();
      if (!response.ok) throw new Error(body?.error?.message ?? "Report AI is unavailable.");
      return body as AgLlmResponse;
    });
    // The provider turn is buffered; emit AG's content events once it completes.
    const stream = (async function* (): AsyncGenerator<AgAiEvent> {
      const result = await complete;
      for (const item of result.output) {
        if (item.type === "message") {
          yield { type: "TEXT_MESSAGE_START", messageId: item.id, role: "assistant" };
          for (const part of item.content) {
            yield { type: "TEXT_MESSAGE_CONTENT", messageId: item.id, delta: part.type === "text" ? part.text : part.refusal };
          }
          yield { type: "TEXT_MESSAGE_END", messageId: item.id };
        } else if (item.type === "function_call") {
          yield { type: "TOOL_CALL_START", toolCallId: item.callId, toolCallName: item.name };
          yield { type: "TOOL_CALL_ARGS", toolCallId: item.callId, delta: item.arguments };
          yield { type: "TOOL_CALL_END", toolCallId: item.callId };
        }
      }
    })();
    return { complete, stream };
  },
};
