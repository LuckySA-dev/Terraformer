import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { api } from '../src/api/network';
import { AssistantChatPanel } from '../src/features/assistant/AssistantChatPanel';
import type { AssistantSession, ProviderProfile } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    providerProfiles: vi.fn(),
    providerProfileModels: vi.fn(),
    assistantSessions: vi.fn(),
    assistantMessages: vi.fn(),
    createAssistantSession: vi.fn(),
    applyChangePlan: vi.fn(),
    stageCommand: vi.fn(),
  },
}));

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  emitMessage(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  close() {
    this.onclose?.();
  }
}

const DEVICE_ID = '9f1d3a2b-0000-4000-8000-000000000001';

const profile: ProviderProfile = {
  id: '2ad0db14-5a87-4147-a4e7-c98f88322464',
  name: 'Local Ollama',
  provider_type: 'openai_compatible',
  base_url: 'http://localhost:11434/v1',
  has_api_key: false,
  created_at: '2026-08-24T00:00:00Z',
  updated_at: '2026-08-24T00:00:00Z',
};

const session: AssistantSession = {
  id: 'session-1',
  provider_profile_id: profile.id,
  model_id: 'llama3.1',
  device_id: DEVICE_ID,
  mode: 'confirm',
  supports_streaming: false,
  supports_tool_calling: true,
  auto_apply_count: 0,
  created_at: '2026-08-24T00:00:00Z',
  updated_at: '2026-08-24T00:00:00Z',
};

function TestProviders({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderPanel(deviceId?: string) {
  render(
    <AssistantChatPanel
      {...(deviceId === undefined ? {} : { deviceId })}
      scopeHint="scope hint text"
    />,
    { wrapper: TestProviders },
  );
}

async function startChat(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(await screen.findByLabelText('Provider profile'), profile.id);
  await user.type(await screen.findByLabelText('Model'), 'llama3.1');
  await user.click(screen.getByRole('button', { name: 'New chat' }));
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeWebSocket);
  vi.mocked(api.providerProfiles).mockResolvedValue([profile]);
  vi.mocked(api.providerProfileModels).mockResolvedValue({ models: ['llama3.1'] });
  vi.mocked(api.assistantSessions).mockResolvedValue([]);
  vi.mocked(api.assistantMessages).mockResolvedValue([]);
});

it('refuses to work until an API key profile exists', async () => {
  vi.mocked(api.providerProfiles).mockResolvedValue([]);
  renderPanel(DEVICE_ID);

  expect(await screen.findByText('Add an API key first')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'New chat' })).not.toBeInTheDocument();
});

it('asks the server only for this device\'s own conversations', async () => {
  renderPanel(DEVICE_ID);

  await waitFor(() => {
    expect(api.assistantSessions).toHaveBeenCalledWith('device', DEVICE_ID);
  });
});

it('asks for workspace conversations when it is not pinned to a device', async () => {
  renderPanel();

  await waitFor(() => {
    expect(api.assistantSessions).toHaveBeenCalledWith('workspace', undefined);
  });
});

it('pins a new device chat to that device', async () => {
  vi.mocked(api.createAssistantSession).mockResolvedValue(session);
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await startChat(user);

  expect(api.createAssistantSession).toHaveBeenCalledWith(profile.id, 'llama3.1', DEVICE_ID);
});

it('leaves a workspace chat unpinned', async () => {
  vi.mocked(api.createAssistantSession).mockResolvedValue({ ...session, device_id: null });
  const user = userEvent.setup();
  renderPanel();

  await startChat(user);

  expect(api.createAssistantSession).toHaveBeenCalledWith(profile.id, 'llama3.1', undefined);
});

it('shows the scope so the operator knows what this chat can see', async () => {
  renderPanel(DEVICE_ID);

  expect(await screen.findByText('scope hint text')).toBeVisible();
});

it('lists earlier conversations for this scope so they can be reopened', async () => {
  vi.mocked(api.assistantSessions).mockResolvedValue([session]);
  vi.mocked(api.assistantMessages).mockResolvedValue([
    {
      id: 'm1',
      session_id: session.id,
      role: 'user',
      content: 'what changed yesterday?',
      tool_calls: null,
      tool_results: null,
      created_at: '2026-08-24T00:00:00Z',
    },
  ]);
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await user.click(await screen.findByText('Earlier conversations here'));
  await user.click(screen.getByRole('button', { name: /llama3\.1/ }));

  expect(await screen.findByText('what changed yesterday?')).toBeVisible();
});

it('connects the socket and renders the transcript once a chat starts', async () => {
  vi.mocked(api.createAssistantSession).mockResolvedValue(session);
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await startChat(user);

  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  expect(FakeWebSocket.instances[0]?.url).toContain('/ws/assistant/session-1');
  expect(await screen.findByRole('log', { name: 'Assistant conversation' })).toBeVisible();
});

it('shows the mode the server actually has when a chat is reopened', async () => {
  // Reopening an Auto chat used to show "Ask me first" while the server was
  // still in Auto -- the toggle lied about whether changes would auto-apply.
  const autoSession = { ...session, mode: 'auto' as const, auto_apply_count: 2 };
  vi.mocked(api.assistantSessions).mockResolvedValue([autoSession]);
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await user.click(await screen.findByRole('button', { name: /llama3\.1/ }));

  expect(await screen.findByText('3 auto-applies left')).toBeVisible();
});

it('stops auto-applying once the server-side allowance is spent', async () => {
  const spent = { ...session, mode: 'auto' as const, auto_apply_count: 5 };
  vi.mocked(api.assistantSessions).mockResolvedValue([spent]);
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await user.click(await screen.findByRole('button', { name: /llama3\.1/ }));
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  const socket = FakeWebSocket.instances[0];
  if (socket === undefined) throw new Error('expected a FakeWebSocket instance');

  socket.emitMessage({
    type: 'change_plan_proposed',
    tool: 'propose_change_plan',
    payload: {
      plan_id: 'plan-1',
      status: 'draft',
      risk: 'low',
      safety_level: 'best_effort',
      steps: [],
    },
  });

  await waitFor(() => expect(screen.getByText('0 auto-applies left')).toBeVisible());
  expect(api.applyChangePlan).not.toHaveBeenCalled();
});

it('sends the session id only when Auto fired the apply', async () => {
  const auto = { ...session, mode: 'auto' as const, auto_apply_count: 0 };
  vi.mocked(api.assistantSessions).mockResolvedValue([auto]);
  vi.mocked(api.applyChangePlan).mockResolvedValue({} as never);
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await user.click(await screen.findByRole('button', { name: /llama3\.1/ }));
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  const socket = FakeWebSocket.instances[0];
  if (socket === undefined) throw new Error('expected a FakeWebSocket instance');

  socket.emitMessage({
    type: 'change_plan_proposed',
    tool: 'propose_change_plan',
    payload: {
      plan_id: 'plan-1',
      status: 'draft',
      risk: 'low',
      safety_level: 'best_effort',
      steps: [],
    },
  });

  await waitFor(() => expect(api.applyChangePlan).toHaveBeenCalledWith('plan-1', session.id));
});

it('shows why an apply failed instead of silently stopping', async () => {
  // A locked device, a spent Auto allowance and an unreachable switch all
  // used to look identical to success: the card just stopped spinning.
  const auto = { ...session, mode: 'auto' as const, auto_apply_count: 0 };
  vi.mocked(api.assistantSessions).mockResolvedValue([auto]);
  vi.mocked(api.applyChangePlan).mockRejectedValue(
    new Error('Another change is already being applied to this device'),
  );
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await user.click(await screen.findByRole('button', { name: /llama3\.1/ }));
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  const socket = FakeWebSocket.instances[0];
  if (socket === undefined) throw new Error('expected a FakeWebSocket instance');

  socket.emitMessage({
    type: 'change_plan_proposed',
    tool: 'propose_change_plan',
    payload: {
      plan_id: 'plan-1',
      status: 'draft',
      risk: 'low',
      safety_level: 'best_effort',
      steps: [],
    },
  });

  expect(
    await screen.findByText('Another change is already being applied to this device'),
  ).toBeVisible();
});

it('surfaces a provider failure without dropping the conversation', async () => {
  vi.mocked(api.createAssistantSession).mockResolvedValue(session);
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await startChat(user);
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  const socket = FakeWebSocket.instances[0];
  if (socket === undefined) throw new Error('expected a FakeWebSocket instance');

  socket.emitMessage({
    type: 'error',
    code: 'provider_unreachable',
    message: 'Could not reach the AI provider. Check the profile\'s API key.',
  });

  expect(await screen.findByText(/Could not reach the AI provider/)).toBeVisible();
  // Still a live chat, not a dead one.
  expect(screen.getByRole('log', { name: 'Assistant conversation' })).toBeVisible();
});

it('warns when the chosen model has no tool support', async () => {
  const noTools = { ...session, supports_tool_calling: false };
  vi.mocked(api.createAssistantSession).mockResolvedValue(noTools);
  vi.mocked(api.assistantSessions).mockResolvedValue([noTools]);
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await startChat(user);

  expect(await screen.findByText('No device tools for this model')).toBeVisible();
});

it('renders a tool result instead of a blank entry', async () => {
  vi.mocked(api.createAssistantSession).mockResolvedValue(session);
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await startChat(user);
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  const socket = FakeWebSocket.instances[0];
  if (socket === undefined) throw new Error('expected a FakeWebSocket instance');

  socket.emitMessage({ type: 'tool_result', tool: 'get_interfaces', payload: { count: 2 } });

  expect(await screen.findByText('get_interfaces')).toBeVisible();
  expect(screen.getByText(/"count": 2/)).toBeVisible();
});

it('renders a fenced command from the assistant as a console suggestion card', async () => {
  vi.mocked(api.createAssistantSession).mockResolvedValue(session);
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await startChat(user);
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  const socket = FakeWebSocket.instances[0];
  if (socket === undefined) throw new Error('expected a FakeWebSocket instance');

  socket.emitMessage({
    type: 'token',
    content: 'Try this:\n```\ninterface GigabitEthernet0/1\n```\n',
  });
  socket.emitMessage({ type: 'done' });

  expect(await screen.findByText('interface GigabitEthernet0/1')).toBeVisible();
  expect(screen.getByRole('button', { name: /copy and open inventory/i })).toBeVisible();
});

it('disables New chat until a provider profile and model are chosen', async () => {
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  expect(await screen.findByRole('button', { name: 'New chat' })).toBeDisabled();

  await user.selectOptions(await screen.findByLabelText('Provider profile'), profile.id);
  expect(screen.getByRole('button', { name: 'New chat' })).toBeDisabled();

  await user.type(await screen.findByLabelText('Model'), 'llama3.1');
  expect(screen.getByRole('button', { name: 'New chat' })).toBeEnabled();
});
