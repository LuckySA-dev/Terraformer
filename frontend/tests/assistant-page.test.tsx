import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { ApiError } from '../src/api/client';
import { api } from '../src/api/network';
import { AssistantPage } from '../src/features/assistant/AssistantPage';
import { ProviderKeysDialog } from '../src/features/assistant/ProviderKeysDialog';
import type { ProviderProfile } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    providerProfiles: vi.fn(),
    createProviderProfile: vi.fn(),
    updateProviderProfile: vi.fn(),
    deleteProviderProfile: vi.fn(),
    providerProfileModels: vi.fn(),
    listProviderModels: vi.fn(),
    assistantSessions: vi.fn(),
    assistantMessages: vi.fn(),
    createAssistantSession: vi.fn(),
    updateAssistantSessionModel: vi.fn(),
    applyChangePlan: vi.fn(),
    stageCommand: vi.fn(),
  },
}));

const profile: ProviderProfile = {
  id: '2ad0db14-5a87-4147-a4e7-c98f88322464',
  name: 'Local Ollama',
  provider_type: 'openai_compatible',
  base_url: 'http://localhost:11434/v1',
  has_api_key: false,
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

// Provider keys now live behind the composer's model picker, so the CRUD
// behaviour these tests cover is exercised where it actually renders.
function renderKeys() {
  render(<ProviderKeysDialog open onClose={vi.fn()} />, { wrapper: TestProviders });
}

beforeEach(() => {
  vi.mocked(api.providerProfiles).mockResolvedValue([profile]);
  vi.mocked(api.providerProfileModels).mockResolvedValue({ models: ['llama3.1'] });
  vi.mocked(api.assistantSessions).mockResolvedValue([]);
  vi.mocked(api.assistantMessages).mockResolvedValue([]);
});

it('shows a clear message instead of a raw error when the gateway is disabled', async () => {
  const disabledError = new ApiError('The AI assistant gateway is disabled by server policy', {
    status: 403,
    code: 'ai_gateway_disabled_by_policy',
  });
  vi.mocked(api.providerProfiles).mockRejectedValue(disabledError);
  renderAssistant();

  expect(await screen.findByText('The assistant is turned off')).toBeVisible();
  expect(screen.getByText(/AI_GATEWAY_ENABLED=false/)).toBeVisible();
  expect(screen.queryByRole('button', { name: /new profile/i })).not.toBeInTheDocument();
});

it('opens straight into a chat rather than a settings screen', async () => {
  renderAssistant();

  // The tab named after the assistant used to be the one place you could not
  // talk to it.
  expect(await screen.findByLabelText('Message')).toBeVisible();
  expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument();
});

it('lists saved provider profiles in the keys dialog', async () => {
  renderKeys();

  expect(await screen.findByText('Local Ollama')).toBeVisible();
});

it('shows an empty state when no profile exists yet', async () => {
  vi.mocked(api.providerProfiles).mockResolvedValue([]);
  renderKeys();

  expect(await screen.findByText('No provider profiles yet')).toBeVisible();
});

it('creates a profile with an optional API key', async () => {
  vi.mocked(api.createProviderProfile).mockResolvedValue({ ...profile, id: 'new-id' });
  const user = userEvent.setup();
  renderKeys();

  await user.click(await screen.findByRole('button', { name: /new profile/i }));
  await user.type(screen.getByLabelText('Profile name'), 'Cloud');
  await user.type(screen.getByLabelText('Base URL'), 'https://api.openai.com/v1');
  await user.click(screen.getByRole('button', { name: 'Save profile' }));

  expect(api.createProviderProfile).toHaveBeenCalledWith(
    expect.objectContaining({ name: 'Cloud', base_url: 'https://api.openai.com/v1' }),
  );
});

it('saves an Anthropic profile with the anthropic wire format, not a base URL swap', async () => {
  vi.mocked(api.createProviderProfile).mockResolvedValue({ ...profile, id: 'new-id' });
  const user = userEvent.setup();
  renderKeys();

  await user.click(await screen.findByRole('button', { name: /new profile/i }));
  await user.type(screen.getByLabelText('Profile name'), 'Claude');
  await user.selectOptions(screen.getByLabelText('Provider'), 'Anthropic (Claude)');
  await user.click(screen.getByRole('button', { name: 'Save profile' }));

  expect(api.createProviderProfile).toHaveBeenCalledWith(
    expect.objectContaining({
      name: 'Claude',
      provider_type: 'anthropic',
      base_url: 'https://api.anthropic.com',
    }),
  );
});

it('keeps the trailing slash Gemini requires when its preset is chosen', async () => {
  const user = userEvent.setup();
  renderKeys();

  await user.click(await screen.findByRole('button', { name: /new profile/i }));
  await user.selectOptions(screen.getByLabelText('Provider'), 'Google Gemini');

  expect(screen.getByLabelText('Base URL')).toHaveValue(
    'https://generativelanguage.googleapis.com/v1beta/openai/',
  );
});

it('verifies the connection and reports how many models are available', async () => {
  vi.mocked(api.listProviderModels).mockResolvedValue({ models: ['llama3.1', 'llama3.2'] });
  const user = userEvent.setup();
  renderKeys();

  await user.click(await screen.findByRole('button', { name: /new profile/i }));
  await user.type(screen.getByLabelText('Base URL'), 'http://localhost:11434/v1');
  await user.click(screen.getByRole('button', { name: /verify connection/i }));

  expect(await screen.findByText(/2 model\(s\) available/)).toBeVisible();
  expect(api.listProviderModels).toHaveBeenCalledWith(
    'http://localhost:11434/v1',
    undefined,
    'openai_compatible',
  );
});

it('surfaces a connection failure when verifying a new profile fails', async () => {
  vi.mocked(api.listProviderModels).mockRejectedValue(new Error('network down'));
  const user = userEvent.setup();
  renderKeys();

  await user.click(await screen.findByRole('button', { name: /new profile/i }));
  await user.type(screen.getByLabelText('Base URL'), 'http://localhost:11434/v1');
  await user.click(screen.getByRole('button', { name: /verify connection/i }));

  expect(await screen.findByText('Could not reach that endpoint.')).toBeVisible();
});

it('deletes a profile through a separate confirmation modal', async () => {
  vi.mocked(api.deleteProviderProfile).mockResolvedValue(undefined);
  const user = userEvent.setup();
  renderKeys();

  await user.click(await screen.findByRole('button', { name: 'Delete Local Ollama' }));

  const confirm = await screen.findByRole('dialog', { name: 'Remove provider profile?' });
  expect(within(confirm).getByText('Local Ollama')).toBeVisible();
  await user.click(within(confirm).getByRole('button', { name: 'Remove profile' }));

  expect(api.deleteProviderProfile).toHaveBeenCalledWith(profile.id);
});

it("tests a saved profile's connection from the list", async () => {
  vi.mocked(api.providerProfileModels).mockResolvedValue({ models: ['llama3.1', 'llama3.2'] });
  const user = userEvent.setup();
  renderKeys();

  await user.click(
    await screen.findByRole('button', { name: `Test connection for ${profile.name}` }),
  );

  expect(api.providerProfileModels).toHaveBeenCalledWith(profile.id);
  expect(await screen.findByText(/2 model\(s\) available/)).toBeVisible();
});

it('surfaces a failed connection test for a saved profile', async () => {
  vi.mocked(api.providerProfileModels).mockRejectedValue(new Error('boom'));
  const user = userEvent.setup();
  renderKeys();

  await user.click(
    await screen.findByRole('button', { name: `Test connection for ${profile.name}` }),
  );

  expect(await screen.findByText('Could not reach that endpoint.')).toBeVisible();
});
