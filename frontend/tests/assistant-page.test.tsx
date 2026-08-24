import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { api } from '../src/api/network';
import { AssistantPage } from '../src/features/assistant/AssistantPage';
import type { ProviderProfile } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    providerProfiles: vi.fn(),
    createProviderProfile: vi.fn(),
    updateProviderProfile: vi.fn(),
    deleteProviderProfile: vi.fn(),
    probeProviderProfile: vi.fn(),
    assistantSessions: vi.fn(),
    createAssistantSession: vi.fn(),
  },
}));

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

beforeEach(() => {
  vi.mocked(api.assistantSessions).mockResolvedValue([]);
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

  expect(await screen.findByText('No provider profiles yet')).toBeVisible();
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
