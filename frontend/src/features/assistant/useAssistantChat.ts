import { useCallback, useEffect, useRef, useState } from 'react';
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

export function useAssistantChat(sessionId: string | undefined) {
  const socketRef = useRef<WebSocket | null>(null);
  const [transcript, setTranscript] = useState<AssistantTranscriptEntry[]>([]);
  const [mode, setModeState] = useState<AssistantSessionMode>('confirm');
  const [connectionState, setConnectionState] = useState<'connecting' | 'open' | 'closed'>('connecting');
  const [pendingModeError, setPendingModeError] = useState<string>();
  const streamingEntryId = useRef<string | null>(null);

  useEffect(() => {
    if (sessionId === undefined) return undefined;
    const wsOrigin = window.location.origin.replace(/^http/, 'ws');
    const socket = new WebSocket(`${wsOrigin}/ws/assistant/${sessionId}`);
    socketRef.current = socket;
    socket.onopen = () => setConnectionState('open');
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
    socketRef.current?.send(JSON.stringify({ type: 'user_message', content }));
  }, []);

  const setMode = useCallback((nextMode: AssistantSessionMode, riskAcknowledged: boolean) => {
    socketRef.current?.send(
      JSON.stringify({ type: 'set_mode', mode: nextMode, risk_acknowledged: riskAcknowledged }),
    );
  }, []);

  return { transcript, sendMessage, mode, setMode, connectionState, pendingModeError };
}
