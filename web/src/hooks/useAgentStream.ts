import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
import { openAgentStream, type AgentEvent } from "@/lib/sse";

const MAX_EVENTS = 200;

/**
 * Subscribes to the backend agent stream and keeps a rolling event log plus the
 * latest status per agent — the data behind the Agent Control Center (§3.4).
 */
export function useAgentStream(enabled = true) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const statuses = useRef<Record<string, AgentEvent>>({});
  const [statusMap, setStatusMap] = useState<Record<string, AgentEvent>>({});

  useEffect(() => {
    if (!enabled) return;

    const handle = openAgentStream(`${API_BASE}/events`, {
      onOpen: () => setConnected(true),
      onError: () => setConnected(false),
      onEvent: (event) => {
        setEvents((prev) => [event, ...prev].slice(0, MAX_EVENTS));
        statuses.current = { ...statuses.current, [event.agent]: event };
        setStatusMap(statuses.current);
      },
    });

    return () => {
      handle.close();
      setConnected(false);
    };
  }, [enabled]);

  return { events, statusMap, connected };
}
