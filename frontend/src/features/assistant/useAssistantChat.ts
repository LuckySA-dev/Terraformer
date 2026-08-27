import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api/network';
import type { AssistantSessionMode } from '../../types/api';

export interface ChangePlanPayload {
  plan_id: string;
  status: string;
  risk: string;
  safety_level: string;
  steps: { target: string; desired_value: string; rendered_commands: string }[];
}

export interface AssistantTranscriptEntry {
  id: string;
  role: 'user' | 'assistant' | 'tool' | 'change_plan';
  content?: string;
  toolName?: string;
  toolPayload?: Record<string, unknown>;
  plan?: ChangePlanPayload;
}

type ServerFrame =
  | { type: 'token'; content: string }
  | { type: 'tool_call'; tool: string; payload?: Record<string, unknown> }
  | { type: 'tool_result'; tool: string; payload: Record<string, unknown> }
  | { type: 'change_plan_proposed'; tool: string; payload: ChangePlanPayload }
  | { type: 'done' }
  | { type: 'mode_changed'; mode: AssistantSessionMode }
  | { type: 'error'; code: string; message: string };

let nextEntryId = 0;
const newEntryId = () => `entry-${String((nextEntryId += 1))}`;

export function useAssistantChat(
  sessionId: string | undefined,
  // Reopening a chat has to show the mode the server actually has. Starting
  // at 'confirm' regardless made the toggle lie about an Auto session, and
  // the client-side auto-apply keys off this value.
  initialMode: AssistantSessionMode = 'confirm',
) {
  const socketRef = useRef<WebSocket | null>(null);
  // Messages typed before the socket is open -- which now happens by design:
  // the composer accepts the first message and the session is created behind
  // it, so there is a real window where there is no socket yet. `send()` on a
  // CONNECTING socket throws, so they wait here instead.
  const pendingSends = useRef<string[]>([]);
  const [transcript, setTranscript] = useState<AssistantTranscriptEntry[]>([]);
  const [mode, setModeState] = useState<AssistantSessionMode>(initialMode);
  const [connectionState, setConnectionState] = useState<'connecting' | 'open' | 'closed'>('connecting');
  const [pendingModeError, setPendingModeError] = useState<string>();
  const streamingEntryId = useRef<string | null>(null);

  // Messages are persisted server-side, so a session opened in a new tab (or
  // after a reload) would otherwise look empty while the model still has the
  // full history -- a confusing mismatch.
  // Switching between saved chats must not carry the previous chat's mode
  // across; each session owns its own. Adjusted during render rather than in
  // an effect so the first paint of a reopened chat already shows the right
  // mode instead of flashing the previous one.
  const [modeSessionId, setModeSessionId] = useState(sessionId);
  if (sessionId !== modeSessionId) {
    setModeSessionId(sessionId);
    setModeState(initialMode);
  }

  useEffect(() => {
    if (sessionId === undefined) return;
    let cancelled = false;
    void api
      .assistantMessages(sessionId)
      .then((stored) => {
        if (cancelled) return;
        setTranscript(
          stored
            .filter((message) => message.role !== 'tool' && message.content !== '')
            .map((message) => ({
              id: `stored-${message.id}`,
              role: message.role === 'user' ? 'user' : 'assistant',
              content: message.content,
            })),
        );
      })
      .catch(() => {
        // A failed history load must not block a live chat: the socket below
        // still works, the operator just starts from a blank transcript.
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    if (sessionId === undefined) return undefined;
    const wsOrigin = window.location.origin.replace(/^http/, 'ws');
    const socket = new WebSocket(`${wsOrigin}/ws/assistant/${sessionId}`);
    socketRef.current = socket;
    socket.onopen = () => {
      setConnectionState('open');
      const queued = pendingSends.current;
      pendingSends.current = [];
      for (const content of queued) {
        socket.send(JSON.stringify({ type: 'user_message', content }));
      }
    };
    socket.onclose = () => setConnectionState('closed');
    socket.onmessage = (event: MessageEvent<string>) => {
      const frame = JSON.parse(event.data) as ServerFrame;
      if (frame.type === 'token') {
        setTranscript((current) => {
          if (streamingEntryId.current !== null) {
            return current.map((entry) =>
              entry.id === streamingEntryId.current
                ? { ...entry, content: (entry.content ?? '') + frame.content }
                : entry,
            );
          }
          const id = newEntryId();
          streamingEntryId.current = id;
          return [...current, { id, role: 'assistant', content: frame.content }];
        });
      } else if (frame.type === 'change_plan_proposed') {
        setTranscript((current) => [...current, { id: newEntryId(), role: 'change_plan', plan: frame.payload }]);
      } else if (frame.type === 'tool_result') {
        setTranscript((current) => [
          ...current,
          { id: newEntryId(), role: 'tool', toolName: frame.tool, toolPayload: frame.payload },
        ]);
      } else if (frame.type === 'done') {
        streamingEntryId.current = null;
      } else if (frame.type === 'mode_changed') {
        setModeState(frame.mode);
        setPendingModeError(undefined);
      } else if (frame.type === 'error') {
        setPendingModeError(frame.message);
      }
    };
    return () => socket.close();
  }, [sessionId]);

  const sendMessage = useCallback((content: string) => {
    setTranscript((current) => [...current, { id: newEntryId(), role: 'user', content }]);
    const socket = socketRef.current;
    if (socket !== null && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'user_message', content }));
    } else {
      pendingSends.current.push(content);
    }
  }, []);

  const setMode = useCallback((nextMode: AssistantSessionMode, riskAcknowledged: boolean) => {
    socketRef.current?.send(
      JSON.stringify({ type: 'set_mode', mode: nextMode, risk_acknowledged: riskAcknowledged }),
    );
  }, []);

  return { transcript, sendMessage, mode, setMode, connectionState, pendingModeError };
}
