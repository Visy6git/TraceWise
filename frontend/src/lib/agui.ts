import { useEffect, useRef, useState } from 'react';
import type { AGUIEvent } from '../types/agui';

export type AGUIConnection = 'disabled' | 'connecting' | 'connected' | 'reconnecting' | 'error';

/**
 * Subscribe to AG-UI 1.0 events over SSE. The UI consumes run/step/tool/subagent,
 * state/activity and TraceWise CUSTOM telemetry. It deliberately ignores REASONING_*.
 * Agent chain-of-thought is not a UI activity feed.
 */
export function useAguiEvents(runId: string, enabled: boolean, onEvent: (event: AGUIEvent) => void) {
  const [connection, setConnection] = useState<AGUIConnection>(enabled ? 'connecting' : 'disabled');
  const callbackRef = useRef(onEvent);
  callbackRef.current = onEvent;

  useEffect(() => {
    if (!enabled || !runId) {
      setConnection('disabled');
      return;
    }
    setConnection('connecting');
    const base = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
    const source = new EventSource(`${base}/api/runs/${encodeURIComponent(runId)}/events`);
    source.onopen = () => setConnection('connected');
    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as AGUIEvent;
        callbackRef.current(event);
      } catch {
        // Malformed frames are ignored and should be surfaced by API-side diagnostics.
      }
    };
    source.onerror = () => setConnection('reconnecting');
    return () => source.close();
  }, [runId, enabled]);

  return connection;
}

export function isAguiEvent(value: unknown): value is AGUIEvent {
  return !!value && typeof value === 'object' && 'type' in value && typeof (value as { type: unknown }).type === 'string';
}
