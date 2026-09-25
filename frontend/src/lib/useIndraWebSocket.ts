'use client';

import { useEffect, useCallback, useState } from 'react';
import { API_BASE } from './api-base';

export type WsMessageType = 'NEW_REPORT' | 'VERIFIED_EVENT' | 'EVENT_REVIEWED';

export interface WsMessage {
  type: WsMessageType;
  [key: string]: any;
}

export type WsListener = (message: WsMessage) => void;

/*
 * One connection to `/ws/events` for the whole tab.
 *
 * Each call of the hook used to open its own socket, and two components opened
 * raw ones beside it, so the dashboard held five or six connections to the same
 * endpoint, each reconnecting on its own schedule. The socket, its listeners and
 * its connected flag now live at module level; the hook only registers. The
 * socket opens with the first subscriber and closes a few seconds after the
 * last one leaves, so a page change does not drop and redial it.
 */

const listeners = new Map<string, WsListener>();
const connectedSetters = new Set<(v: boolean) => void>();
let socket: WebSocket | null = null;
let isConnected = false;
let users = 0;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let idleTimer: ReturnType<typeof setTimeout> | null = null;

function setConnected(v: boolean) {
  isConnected = v;
  connectedSetters.forEach((set) => set(v));
}

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  const wsUrl = API_BASE.replace(/^http/, 'ws');
  try {
    const ws = new WebSocket(`${wsUrl}/ws/events`);
    ws.onopen = () => setConnected(true);
    ws.onmessage = (event) => {
      try {
        const msg: WsMessage = JSON.parse(event.data);
        if (msg.type) {
          listeners.forEach((listener) => {
            try { listener(msg); } catch { /* one listener's error is not the others' */ }
          });
        }
      } catch {
        // A malformed frame is not a reason to tear the socket down.
      }
    };
    ws.onclose = () => {
      setConnected(false);
      socket = null;
      if (users > 0) reconnectTimer = setTimeout(connect, 3000);
    };
    socket = ws;
  } catch {
    console.warn('[INDRA] WebSocket connection failed (non-fatal)');
    if (users > 0) reconnectTimer = setTimeout(connect, 5000);
  }
}

function acquire() {
  users += 1;
  if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
  connect();
}

function release() {
  users = Math.max(0, users - 1);
  if (users > 0) return;
  idleTimer = setTimeout(() => {
    if (users > 0) return;
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    if (socket) {
      socket.onclose = null;
      socket.close();
      socket = null;
    }
    setConnected(false);
  }, 5000);
}

/**
 * The shared `/ws/events` connection: whether it is up, and a way to listen.
 * Any number of components may call this; there is still one socket.
 */
export function useIndraWebSocket() {
  const [connected, setConnectedState] = useState(isConnected);

  useEffect(() => {
    connectedSetters.add(setConnectedState);
    setConnectedState(isConnected);
    acquire();
    return () => {
      connectedSetters.delete(setConnectedState);
      release();
    };
  }, []);

  /** Subscribe a listener under a unique id. Returns an unsubscribe function. */
  const subscribe = useCallback((id: string, listener: WsListener): (() => void) => {
    listeners.set(id, listener);
    return () => {
      if (listeners.get(id) === listener) listeners.delete(id);
    };
  }, []);

  return { connected, subscribe };
}
