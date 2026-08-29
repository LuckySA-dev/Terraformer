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
    updateAssistantSessionModel: vi.fn(),
    updateAssistantSessionScope: vi.fn(),
    devices: vi.fn(),
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
  readyState = 1;
  // The hook reads these off the global the way the real API exposes them.
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

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
  scope_device_ids: [],
  mode: 'confirm',
  supports_streaming: false,
  supports_tool_calling: true,
  auto_apply_count: 0,
  summary: null,
  summarised_message_count: 0,
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

async function pickModel(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /^Model:/ }));
  await user.click(await screen.findByRole('menuitem', { name: /llama3\.1/ }));
}

async function startChat(user: ReturnType<typeof userEvent.setup>) {
  await pickModel(user);
  await user.type(screen.getByLabelText('Message'), 'hello');
  await user.click(screen.getByRole('button', { name: /send/i }));
  await waitFor(() => expect(api.createAssistantSession).toHaveBeenCalled());
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeWebSocket);
  vi.mocked(api.providerProfiles).mockResolvedValue([profile]);
  vi.mocked(api.providerProfileModels).mockResolvedValue({ models: ['llama3.1'] });
  vi.mocked(api.assistantSessions).mockResolvedValue([]);
  vi.mocked(api.assistantMessages).mockResolvedValue([]);
  vi.mocked(api.devices).mockResolvedValue([]);
});

it('refuses to work until an API key profile exists', async () => {
  vi.mocked(api.providerProfiles).mockResolvedValue([]);
  renderPanel(DEVICE_ID);

  expect(await screen.findByText('Add a provider key to start')).toBeVisible();
  expect(screen.getByLabelText('Message')).toBeDisabled();
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

  // Empty scope is "all devices"; a device-pinned chat has no scope picker.
  expect(api.createAssistantSession).toHaveBeenCalledWith(profile.id, 'llama3.1', DEVICE_ID, []);
});

it('leaves a workspace chat unpinned', async () => {
  vi.mocked(api.createAssistantSession).mockResolvedValue({ ...session, device_id: null });
  const user = userEvent.setup();
  renderPanel();

  await startChat(user);

  expect(api.createAssistantSession).toHaveBeenCalledWith(profile.id, 'llama3.1', undefined, []);
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

  await user.selectOptions(await screen.findByLabelText('Conversation'), session.id);

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

  await user.selectOptions(await screen.findByLabelText('Conversation'), session.id);

  expect(await screen.findByText('3 auto-applies left')).toBeVisible();
});

it('stops auto-applying once the server-side allowance is spent', async () => {
  const spent = { ...session, mode: 'auto' as const, auto_apply_count: 5 };
  vi.mocked(api.assistantSessions).mockResolvedValue([spent]);
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await user.selectOptions(await screen.findByLabelText('Conversation'), session.id);
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

  await user.selectOptions(await screen.findByLabelText('Conversation'), session.id);
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

  await user.selectOptions(await screen.findByLabelText('Conversation'), session.id);
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
  // The payload is collapsed behind the activity line now, but it is still
  // there in full for anyone who wants to check what the model was told.
  const disclosure = screen.getByText('get_interfaces').closest('details');
  expect(disclosure).not.toBeNull();
  expect(screen.getByText(/"count": 2/)).toBeInTheDocument();
  await user.click(screen.getByText('get_interfaces'));
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

it('will not send until a model is chosen', async () => {
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await user.type(await screen.findByLabelText('Message'), 'hello');
  expect(screen.getByRole('button', { name: /send/i })).toBeDisabled();

  await pickModel(user);
  expect(screen.getByRole('button', { name: /send/i })).toBeEnabled();
});

it('switches model from the composer without starting a new conversation', async () => {
  vi.mocked(api.assistantSessions).mockResolvedValue([session]);
  vi.mocked(api.providerProfileModels).mockResolvedValue({ models: ['llama3.1', 'qwen2.5'] });
  vi.mocked(api.updateAssistantSessionModel).mockResolvedValue({ ...session, model_id: 'qwen2.5' });
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await user.selectOptions(await screen.findByLabelText('Conversation'), session.id);
  await user.click(await screen.findByRole('button', { name: /^Model:/ }));
  await user.click(await screen.findByRole('menuitem', { name: /qwen2\.5/ }));

  // The point of the PATCH: the thread is repointed, not replaced, so the
  // history above the composer survives the switch.
  await waitFor(() =>
    expect(api.updateAssistantSessionModel).toHaveBeenCalledWith(session.id, profile.id, 'qwen2.5'),
  );
  expect(api.createAssistantSession).not.toHaveBeenCalled();
});

it('picks a model without contacting the provider until something is sent', async () => {
  vi.mocked(api.providerProfileModels).mockResolvedValue({ models: ['llama3.1', 'qwen2.5'] });
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await user.click(await screen.findByRole('button', { name: /^Model:/ }));
  await user.click(await screen.findByRole('menuitem', { name: /qwen2\.5/ }));

  // Creating a session probes the provider. Doing that for a chat the operator
  // may never send would spend a request on an idle dropdown.
  expect(api.createAssistantSession).not.toHaveBeenCalled();
  expect(api.updateAssistantSessionModel).not.toHaveBeenCalled();
  expect(await screen.findByRole('button', { name: /^Model: qwen2\.5/ })).toBeVisible();
});

it('reaches provider key management from inside the chat', async () => {
  const user = userEvent.setup();
  renderPanel(DEVICE_ID);

  await user.click(await screen.findByRole('button', { name: /^Model:/ }));
  await user.click(await screen.findByRole('menuitem', { name: /manage provider keys/i }));

  expect(await screen.findByText('Provider keys')).toBeVisible();
});

const sw = (id: string, name: string) => ({
  id,
  name,
  management_address: `192.0.2.${id.slice(-1)}`,
  port: 22,
  vendor: 'cisco_iosxe' as const,
  is_lab: false,
  console_transport: 'ssh' as const,
  credential_profile_id: 'c6d6a5be-bf2e-4d6a-bda8-3a559f985631',
  status: 'reachable' as const,
  facts: {},
  capabilities: [],
  last_seen_at: null,
  last_error_code: null,
  created_at: '2026-08-27T00:00:00Z',
  updated_at: '2026-08-27T00:00:00Z',
});

it('scopes a workspace chat to the devices the operator names', async () => {
  const sw1 = sw('9f1d3a2b-0000-4000-8000-000000000101', 'SW1');
  const sw2 = sw('9f1d3a2b-0000-4000-8000-000000000102', 'SW2');
  vi.mocked(api.devices).mockResolvedValue([sw1, sw2]);
  vi.mocked(api.createAssistantSession).mockResolvedValue({ ...session, device_id: null });
  const user = userEvent.setup();
  renderPanel();

  await user.click(await screen.findByRole('button', { name: /^Devices: All devices/ }));
  await user.click(await screen.findByRole('menuitemcheckbox', { name: 'SW1' }));
  // The menu stays open so a two-device scope is two clicks, not two openings.
  await user.click(screen.getByRole('menuitemcheckbox', { name: 'SW2' }));
  await pickModel(user);
  await user.type(screen.getByLabelText('Message'), 'shut both down');
  await user.click(screen.getByRole('button', { name: /send/i }));

  await waitFor(() =>
    expect(api.createAssistantSession).toHaveBeenCalledWith(profile.id, 'llama3.1', undefined, [
      sw1.id,
      sw2.id,
    ]),
  );
});

it('offers no device scope for a chat already pinned to one device', async () => {
  renderPanel(DEVICE_ID);

  expect(await screen.findByLabelText('Message')).toBeVisible();
  expect(screen.queryByRole('button', { name: /^Devices:/ })).not.toBeInTheDocument();
});

it('rescopes a live conversation without starting a new one', async () => {
  const sw1 = sw('9f1d3a2b-0000-4000-8000-000000000101', 'SW1');
  vi.mocked(api.devices).mockResolvedValue([sw1]);
  vi.mocked(api.assistantSessions).mockResolvedValue([{ ...session, device_id: null }]);
  vi.mocked(api.updateAssistantSessionScope).mockResolvedValue({
    ...session,
    device_id: null,
    scope_device_ids: [sw1.id],
  });
  const user = userEvent.setup();
  renderPanel();

  await user.selectOptions(await screen.findByLabelText('Conversation'), session.id);
  await user.click(await screen.findByRole('button', { name: /^Devices:/ }));
  await user.click(await screen.findByRole('menuitemcheckbox', { name: 'SW1' }));

  await waitFor(() =>
    expect(api.updateAssistantSessionScope).toHaveBeenCalledWith(session.id, [sw1.id]),
  );
  expect(api.createAssistantSession).not.toHaveBeenCalled();
});


describe('the composer answers commands itself', () => {
  const openChat = async (user: ReturnType<typeof userEvent.setup>) => {
    vi.mocked(api.providerProfiles).mockResolvedValue([profile]);
    vi.mocked(api.devices).mockResolvedValue([]);
    vi.mocked(api.assistantSessions).mockResolvedValue([session]);
    vi.mocked(api.assistantMessages).mockResolvedValue([]);
    renderPanel(DEVICE_ID);
    await user.selectOptions(await screen.findByLabelText('Conversation'), session.id);
    return screen.getByLabelText('Message');
  };

  it('lists the commands without sending anything to the model', async () => {
    const user = userEvent.setup();
    const input = await openChat(user);

    await user.type(input, '/help{Enter}');

    expect(await screen.findByText(/Apply changes as soon as they are drafted/)).toBeVisible();
    // A command is answered by the panel, so it must not enter the
    // conversation the model sees.
    const socket = FakeWebSocket.instances.at(-1);
    expect(socket?.sent.some((frame) => frame.includes('/help'))).toBe(false);
  });

  it('switches to Auto on the command, treating typing it as the acceptance', async () => {
    const user = userEvent.setup();
    const input = await openChat(user);

    await user.type(input, '/auto{Enter}');

    const socket = FakeWebSocket.instances.at(-1);
    await waitFor(() =>
      expect(
        socket?.sent.some((frame) => {
          const parsed = JSON.parse(frame) as Record<string, unknown>;
          return (
            parsed.type === 'set_mode'
            && parsed.mode === 'auto'
            && parsed.risk_acknowledged === true
          );
        }),
      ).toBe(true),
    );
    // And it says what it just turned on, including the ceiling.
    expect(await screen.findByText(/Type \/manual to stop/)).toBeVisible();
  });

  it('switches back to Confirm', async () => {
    const user = userEvent.setup();
    const input = await openChat(user);

    await user.type(input, '/manual{Enter}');

    const socket = FakeWebSocket.instances.at(-1);
    await waitFor(() =>
      expect(
        socket?.sent.some((frame) => {
          const parsed = JSON.parse(frame) as Record<string, unknown>;
          return parsed.type === 'set_mode' && parsed.mode === 'confirm';
        }),
      ).toBe(true),
    );
    expect(await screen.findByText(/Every apply waits for you/)).toBeVisible();
  });

  it('says an unknown command is unknown rather than asking the model about it', async () => {
    const user = userEvent.setup();
    const input = await openChat(user);

    await user.type(input, '/wat{Enter}');

    expect(await screen.findByText(/Unknown command \/wat/)).toBeVisible();
    const socket = FakeWebSocket.instances.at(-1);
    expect(socket?.sent.some((frame) => frame.includes('/wat'))).toBe(false);
  });

  it('offers the commands as soon as a slash is typed', async () => {
    const user = userEvent.setup();
    const input = await openChat(user);

    await user.type(input, '/a');

    const hint = await screen.findByRole('button', { name: /\/auto/ });
    expect(hint).toBeVisible();
    await user.click(hint);
    expect(screen.getByLabelText('Message')).toHaveValue('/auto ');
  });
});


describe('what the transcript shows while the agent works', () => {
  it('reports a tool result as one line, with the payload behind it', async () => {
    const user = userEvent.setup();
    vi.mocked(api.providerProfiles).mockResolvedValue([profile]);
    vi.mocked(api.devices).mockResolvedValue([]);
    vi.mocked(api.assistantSessions).mockResolvedValue([session]);
    vi.mocked(api.assistantMessages).mockResolvedValue([]);
    renderPanel(DEVICE_ID);
    await user.selectOptions(await screen.findByLabelText('Conversation'), session.id);

    const socket = FakeWebSocket.instances.at(-1);
    socket?.emitMessage({
      type: 'tool_result',
      tool: 'get_topology',
      payload: {
        devices: [{ name: 'SW1' }, { name: 'SW2' }],
        links: [{ local_device: 'SW1' }],
        observed_only_neighbours: [],
      },
    });

    // A whole-network payload printed in full put the answer hundreds of lines
    // below the question, so the transcript states what came back instead.
    expect(await screen.findByText(/2 devices, 1 links, 0 observed only neighbours/)).toBeVisible();
    expect(screen.getByText('get_topology')).toBeVisible();
  });

  it('shows a tool error as the summary rather than a field count', async () => {
    const user = userEvent.setup();
    vi.mocked(api.providerProfiles).mockResolvedValue([profile]);
    vi.mocked(api.devices).mockResolvedValue([]);
    vi.mocked(api.assistantSessions).mockResolvedValue([session]);
    vi.mocked(api.assistantMessages).mockResolvedValue([]);
    renderPanel(DEVICE_ID);
    await user.selectOptions(await screen.findByLabelText('Conversation'), session.id);

    const socket = FakeWebSocket.instances.at(-1);
    socket?.emitMessage({
      type: 'tool_result',
      tool: 'get_device_facts',
      payload: { error: 'device_id must be a UUID' },
    });

    expect(await screen.findByText('device_id must be a UUID')).toBeVisible();
  });
});


describe('compacting a long conversation', () => {
  const openChat = async (user: ReturnType<typeof userEvent.setup>) => {
    vi.mocked(api.providerProfiles).mockResolvedValue([profile]);
    vi.mocked(api.devices).mockResolvedValue([]);
    vi.mocked(api.assistantSessions).mockResolvedValue([session]);
    vi.mocked(api.assistantMessages).mockResolvedValue([]);
    renderPanel(DEVICE_ID);
    await user.selectOptions(await screen.findByLabelText('Conversation'), session.id);
    return screen.getByLabelText('Message');
  };

  it('asks the server to compact on /compact', async () => {
    const user = userEvent.setup();
    const input = await openChat(user);

    await user.type(input, '/compact{Enter}');

    const socket = FakeWebSocket.instances.at(-1);
    await waitFor(() =>
      expect(
        socket?.sent.some(
          (frame) => (JSON.parse(frame) as Record<string, unknown>).type === 'compact',
        ),
      ).toBe(true),
    );
    // The command never becomes a message the model has to read.
    expect(socket?.sent.some((frame) => frame.includes('/compact'))).toBe(false);
  });

  it('marks where the conversation was folded, and keeps what it established', async () => {
    const user = userEvent.setup();
    await openChat(user);

    const socket = FakeWebSocket.instances.at(-1);
    socket?.emitMessage({
      type: 'compacted',
      content: 'SW1 Gi1/0/1 was found down; VLAN 10 was ruled out.',
    });

    // A divider, not a message -- and the summary is readable, because it is
    // what the model will be working from afterwards.
    expect(await screen.findByText(/Earlier turns compacted/)).toBeVisible();
    expect(screen.getByText(/VLAN 10 was ruled out/)).toBeInTheDocument();
  });
});
