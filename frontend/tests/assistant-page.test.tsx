import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { api } from '../src/api/network';
import { AssistantPage } from '../src/features/assistant/AssistantPage';
import type { AssistantSession, ProviderProfile } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    providerProfiles: vi.fn(),
    createProviderProfile: vi.fn(),
    updateProviderProfile: vi.fn(),
    deleteProviderProfile: vi.fn(),
    probeProviderProfile: vi.fn(),
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

const profile: ProviderProfile = {
  id: '2ad0db14-5a87-4147-a4e7-c98f88322464',
  name: 'Local Ollama',
  base_url: 'http://localhost:11434/v1',
  model_id: 'llama3.1',
  has_api_key: false,
  context_limit_override: null,
  supports_streaming: false,
  supports_tool_calling: false,
  created_at: '2026-08-24T00:00:00Z',
  updated_at: '2026-08-24T00:00:00Z',
};

function TestProviders({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderAssistant() {
  render(<AssistantPage />, { wrapper: TestProviders });
}

const session: AssistantSession = {
  id: 'session-1',
  provider_profile_id: profile.id,
  mode: 'confirm',
  auto_apply_count: 0,
  created_at: '2026-08-24T00:00:00Z',
  updated_at: '2026-08-24T00:00:00Z',
};

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeWebSocket);
  vi.mocked(api.assistantSessions).mockResolvedValue([]);
  vi.mocked(api.assistantMessages).mockResolvedValue([]);
  vi.mocked(api.providerProfiles).mockResolvedValue([profile]);
});

it('opens the provider profile list from the header button', async () => {
  const user = userEvent.setup();
  renderAssistant();

  await user.click(screen.getByRole('button', { name: 'Provider profile' }));

  const dialog = await screen.findByRole('dialog', { name: 'Provider profiles' });
  expect(within(dialog).getByText('Local Ollama')).toBeVisible();
});

it('shows an empty state and offers to create the first profile', async () => {
  vi.mocked(api.providerProfiles).mockResolvedValue([]);
  const user = userEvent.setup();
  renderAssistant();

  await user.click(screen.getByRole('button', { name: 'Provider profile' }));

  const dialog = await screen.findByRole('dialog', { name: 'Provider profiles' });
  expect(within(dialog).getByText('No provider profiles yet')).toBeVisible();
});

it('creates a profile with an optional API key', async () => {
  vi.mocked(api.createProviderProfile).mockResolvedValue({ ...profile, id: 'new-id' });
  const user = userEvent.setup();
  renderAssistant();

  await user.click(screen.getByRole('button', { name: 'Provider profile' }));
  await user.click(await screen.findByRole('button', { name: /new profile/i }));
  await user.type(screen.getByLabelText('Profile name'), 'Cloud');
  await user.type(screen.getByLabelText('Base URL'), 'https://api.openai.com/v1');
  await user.type(screen.getByLabelText('Model ID'), 'gpt-4o');
  await user.click(screen.getByRole('button', { name: 'Save profile' }));

  expect(api.createProviderProfile).toHaveBeenCalledWith(
    expect.objectContaining({
      name: 'Cloud',
      base_url: 'https://api.openai.com/v1',
      model_id: 'gpt-4o',
    }),
  );
});

it('deletes a profile through a separate confirmation modal', async () => {
  vi.mocked(api.deleteProviderProfile).mockResolvedValue(undefined);
  const user = userEvent.setup();
  renderAssistant();

  await user.click(screen.getByRole('button', { name: 'Provider profile' }));
  await user.click(await screen.findByRole('button', { name: 'Delete Local Ollama' }));

  const confirm = await screen.findByRole('dialog', { name: 'Remove provider profile?' });
  expect(within(confirm).getByText('Local Ollama')).toBeVisible();
  await user.click(within(confirm).getByRole('button', { name: 'Remove profile' }));

  expect(api.deleteProviderProfile).toHaveBeenCalledWith(profile.id);
});

it('warns that an untested profile gives the assistant no device tools', async () => {
  const user = userEvent.setup();
  renderAssistant();

  await user.click(screen.getByRole('button', { name: 'Provider profile' }));

  const dialog = await screen.findByRole('dialog', { name: 'Provider profiles' });
  expect(within(dialog).getByText(/no device tools/i)).toBeVisible();
});

it('runs a capability probe from the list and reflects the enabled tools', async () => {
  vi.mocked(api.probeProviderProfile).mockResolvedValue({
    ...profile,
    supports_streaming: true,
    supports_tool_calling: true,
  });
  const user = userEvent.setup();
  renderAssistant();

  await user.click(screen.getByRole('button', { name: 'Provider profile' }));
  await user.click(
    await screen.findByRole('button', { name: `Test connection for ${profile.name}` }),
  );

  expect(api.probeProviderProfile).toHaveBeenCalledWith(profile.id);
});

it('surfaces a failed probe instead of silently leaving tools off', async () => {
  vi.mocked(api.probeProviderProfile).mockRejectedValue(
    new Error('Could not reach the configured endpoint'),
  );
  const user = userEvent.setup();
  renderAssistant();

  await user.click(screen.getByRole('button', { name: 'Provider profile' }));
  await user.click(
    await screen.findByRole('button', { name: `Test connection for ${profile.name}` }),
  );

  expect(await screen.findByText('Could not reach the configured endpoint')).toBeVisible();
});

it('restores a persisted transcript when a session is opened', async () => {
  vi.mocked(api.createAssistantSession).mockResolvedValue(session);
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
    {
      id: 'm2',
      session_id: session.id,
      role: 'assistant',
      content: 'Nothing was applied yesterday.',
      tool_calls: null,
      tool_results: null,
      created_at: '2026-08-24T00:00:01Z',
    },
  ]);
  const user = userEvent.setup();
  renderAssistant();

  await user.selectOptions(await screen.findByLabelText('Provider profile'), profile.id);
  await user.click(screen.getByRole('button', { name: 'New chat' }));

  expect(await screen.findByText('what changed yesterday?')).toBeVisible();
  expect(screen.getByText('Nothing was applied yesterday.')).toBeVisible();
});

it('starts a new chat with the selected provider profile and connects the socket', async () => {
  vi.mocked(api.createAssistantSession).mockResolvedValue(session);
  const user = userEvent.setup();
  renderAssistant();

  await user.selectOptions(await screen.findByLabelText('Provider profile'), profile.id);
  await user.click(screen.getByRole('button', { name: 'New chat' }));

  expect(api.createAssistantSession).toHaveBeenCalledWith(profile.id);
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  expect(FakeWebSocket.instances[0]?.url).toContain('/ws/assistant/session-1');
  expect(await screen.findByRole('log', { name: 'Assistant conversation' })).toBeVisible();
});

it('disables New chat until a provider profile is selected', async () => {
  renderAssistant();

  expect(await screen.findByRole('button', { name: 'New chat' })).toBeDisabled();
});

it('renders a fenced command from the assistant as a console suggestion card', async () => {
  vi.mocked(api.createAssistantSession).mockResolvedValue(session);
  const user = userEvent.setup();
  renderAssistant();

  await user.selectOptions(await screen.findByLabelText('Provider profile'), profile.id);
  await user.click(screen.getByRole('button', { name: 'New chat' }));
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
