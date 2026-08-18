/**
 * SSE client for the live agent event stream (`GET /api/v1/events`).
 * Auto-reconnects with backoff; the backend replays recent events on connect.
 */

export type AgentStatus = "idle" | "active" | "working" | "monitoring" | "waiting" | "error";

export type AgentEvent = {
  id: string;
  ts: string;
  /** Agent slug: chief, flight, hotel, research, weather_risk, budget, itinerary, memory */
  agent: string;
  status: AgentStatus;
  message: string;
  /** Optional structured payload (results, costs, reasons). */
  data?: Record<string, unknown>;
  /** Set when this event was caused by another agent's hand-off. */
  causedBy?: string;
};

type StreamHandlers = {
  onEvent: (event: AgentEvent) => void;
  onOpen?: () => void;
  onError?: (err: unknown) => void;
};

export type StreamHandle = { close: () => void };

/**
 * Subscribe to the agent stream. Returns a handle — always close it on unmount.
 */
export function openAgentStream(
  path: string,
  { onEvent, onOpen, onError }: StreamHandlers,
): StreamHandle {
  let source: EventSource | null = null;
  let retry = 0;
  let timer: number | undefined;
  let closed = false;

  const connect = () => {
    if (closed) return;
    source = new EventSource(path);

    source.onopen = () => {
      retry = 0;
      onOpen?.();
    };

    source.onmessage = (raw) => {
      try {
        onEvent(JSON.parse(raw.data) as AgentEvent);
      } catch (err) {
        onError?.(err);
      }
    };

    source.onerror = (err) => {
      onError?.(err);
      source?.close();
      if (closed) return;
      // Backoff: 1s, 2s, 4s … capped at 15s.
      const delay = Math.min(1000 * 2 ** retry++, 15_000);
      timer = window.setTimeout(connect, delay);
    };
  };

  connect();

  return {
    close: () => {
      closed = true;
      if (timer) window.clearTimeout(timer);
      source?.close();
    },
  };
}
