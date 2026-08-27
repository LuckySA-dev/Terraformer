import { act, renderHook, waitFor } from '@testing-library/react';
import { useAssistantChat } from '../src/features/assistant/useAssistantChat';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  // The hook queues a message unless the socket is open, and reads the state
  // constants off the global the way the real API exposes them.
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  readyState = 0;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }

  emitOpen() {
    this.readyState = 1;
    this.onopen?.();
  }

  emitMessage(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeWebSocket);
});

function getSocket(): FakeWebSocket {
  const socket = FakeWebSocket.instances[0];
  if (socket === undefined) throw new Error('expected a FakeWebSocket instance to exist');
  return socket;
}

it('connects to the session-scoped endpoint and streams tokens into one transcript entry', async () => {
  const { result } = renderHook(() => useAssistantChat('session-1'));

  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  const socket = getSocket();
  expect(socket.url).toContain('/ws/assistant/session-1');
  act(() => socket.emitOpen());

  act(() => result.current.sendMessage('hello'));
  const [firstSent] = socket.sent;
  if (firstSent === undefined) throw new Error('expected a sent frame');
  expect(JSON.parse(firstSent)).toEqual({ type: 'user_message', content: 'hello' });

  act(() => socket.emitMessage({ type: 'token', content: 'Hi' }));
  act(() => socket.emitMessage({ type: 'token', content: ' there' }));
  act(() => socket.emitMessage({ type: 'done' }));

  const assistantEntry = result.current.transcript.find((e) => e.role === 'assistant');
  expect(assistantEntry?.content).toBe('Hi there');
});

it('surfaces change_plan_proposed as a distinct transcript entry', async () => {
  const { result } = renderHook(() => useAssistantChat('session-1'));
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  const socket = getSocket();
  act(() => socket.emitOpen());

  act(() =>
    socket.emitMessage({
      type: 'change_plan_proposed',
      tool: 'propose_change_plan',
      payload: { plan_id: 'p1', status: 'draft', risk: 'low', safety_level: 'C', steps: [] },
    }),
  );

  const planEntry = result.current.transcript.find((e) => e.role === 'change_plan');
  expect(planEntry?.plan?.plan_id).toBe('p1');
});

it('rejects switching to auto mode without acknowledgment and surfaces the error', async () => {
  const { result } = renderHook(() => useAssistantChat('session-1'));
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  const socket = getSocket();
  act(() => socket.emitOpen());

  act(() => result.current.setMode('auto', false));
  act(() =>
    socket.emitMessage({
      type: 'error',
      code: 'auto_mode_requires_acknowledgment',
      message: 'Confirm the risk before enabling Auto mode',
    }),
  );

  expect(result.current.pendingModeError).toBe('Confirm the risk before enabling Auto mode');
});
