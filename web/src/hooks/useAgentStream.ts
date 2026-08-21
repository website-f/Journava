import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { openAgentStream, type AgentEvent, type StreamHandle } from "@/lib/sse";

const MAX_EVENTS = 200;

/*
 * One EventSource for the whole app.
 *
 * `useAgentStream` is called from the shell *and* from several pages at once, so
 * a per-hook connection meant four concurrent SSE streams against a six-per-host
 * HTTP/1.1 budget — and because the backend replays its buffer to every new
 * subscriber, each extra connection also re-delivered the same 50 events.
 *
 * A module-level store fixes both: subscribers share one connection, one event
 * log, and one status map. The connection opens with the first subscriber and
 * closes when the last one unmounts.
 */

type StreamState = {
  events: AgentEvent[];
  statusMap: Record<string, AgentEvent>;
  connected: boolean;
};

type Listener = (state: StreamState) => void;

let state: StreamState = { events: [], statusMap: {}, connected: false };
let handle: StreamHandle | null = null;
const listeners = new Set<Listener>();
/** Event ids already applied — the replay buffer can resend after a reconnect. */
let seenIds = new Set<string>();

function emit(next: Partial<StreamState>) {
  state = { ...state, ...next };
  for (const listener of listeners) listener(state);
}

function connect() {
  if (handle) return;
  // EventSource can't send an Authorization header, so the access token rides in
  // the query string (the auth middleware accepts it for /events only). Build the
  // URL lazily — passed as a getter — so every reconnect re-reads the CURRENT
  // token. If the token rotated (a 401 elsewhere refreshed it), the reconnect
  // picks up the fresh one instead of looping forever on the stale token, which
  // used to require a full page refresh to recover.
  const buildUrl = () => {
    const token = getAccessToken();
    return token
      ? `${API_BASE}/events?token=${encodeURIComponent(token)}`
      : `${API_BASE}/events`;
  };
  handle = openAgentStream(buildUrl, {
    onOpen: () => emit({ connected: true }),
    onError: () => emit({ connected: false }),
    onEvent: (event) => {
      // Deduplicate: a reconnect replays recent events the log already holds.
      if (event.id && seenIds.has(event.id)) return;
      if (event.id) {
        seenIds.add(event.id);
        if (seenIds.size > MAX_EVENTS * 2) {
          // Keep the set bounded without losing the ids still in the log.
          seenIds = new Set(state.events.map((e) => e.id));
        }
      }
      emit({
        events: [event, ...state.events].slice(0, MAX_EVENTS),
        statusMap: { ...state.statusMap, [event.agent]: event },
      });
    },
  });
}

function disconnect() {
  handle?.close();
  handle = null;
  emit({ connected: false });
}

/**
 * Subscribe to the shared agent event stream — the data behind the Agent Control
 * Center (§3.4), the plan overlay's live log, and the shell's error toasts.
 */
export function useAgentStream(enabled = true) {
  const [local, setLocal] = useState<StreamState>(state);

  useEffect(() => {
    if (!enabled) return;

    const listener: Listener = (next) => setLocal(next);
    listeners.add(listener);
    connect();
    // Adopt whatever the shared stream already has, so a page mounted mid-run
    // renders the backlog instead of starting from an empty log.
    setLocal(state);

    return () => {
      listeners.delete(listener);
      if (listeners.size === 0) disconnect();
    };
  }, [enabled]);

  return local;
}
