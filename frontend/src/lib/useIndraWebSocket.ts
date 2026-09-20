'use client';

import { useEffect, useRef, useCallback, useState } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

export type WsMessageType = 'NEW_REPORT' | 'VERIFIED_EVENT' | 'EVENT_REVIEWED' | 'DEMO_PULSE';

export interface WsMessage {
  type: WsMessageType;
  [key: string]: any;
}

export type WsListener = (message: WsMessage) => void;

/**
 * Centralized WebSocket hook for the INDRA `/ws/events` endpoint.
 *
 * Manages auto-reconnect and dispatches typed messages to registered listeners.
 * Multiple components can subscribe without opening duplicate connections.
 */
export function useIndraWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const listenersRef = useRef<Map<string, WsListener>>(new Map());
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [connected, setConnected] = useState(false);

  const connect = useCallback(() => {
    // Don't open duplicate connections
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const wsUrl = API_BASE
      .replace('http://', 'ws://')
      .replace('https://', 'wss://');

    try {
      const ws = new WebSocket(`${wsUrl}/ws/events`);

      ws.onopen = () => {
        setConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const msg: WsMessage = JSON.parse(event.data);
          if (msg.type) {
            listenersRef.current.forEach((listener) => {
              try { listener(msg); } catch { /* ignore listener errors */ }
            });
          }
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        // Auto-reconnect after 3 seconds
        reconnectTimerRef.current = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        // onclose will fire after onerror
      };

      wsRef.current = ws;
    } catch {
      console.warn('[INDRA] WebSocket connection failed (non-fatal)');
      reconnectTimerRef.current = setTimeout(connect, 5000);
    }
  }, []);

  // Connect on mount, disconnect on unmount
  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null; // prevent reconnect on intentional close
        wsRef.current.close();
      }
    };
  }, [connect]);

  /** Subscribe a listener. Returns an unsubscribe function. */
  const subscribe = useCallback((id: string, listener: WsListener): (() => void) => {
    listenersRef.current.set(id, listener);
    return () => {
      listenersRef.current.delete(id);
    };
  }, []);

  return { connected, subscribe };
}
