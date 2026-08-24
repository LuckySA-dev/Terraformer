import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '../src/api/network';
import { ConsoleSuggestionCard } from '../src/features/assistant/ConsoleSuggestionCard';

vi.mock('../src/api/network', () => ({
  api: { stageCommand: vi.fn() },
}));

beforeEach(() => {
  // jsdom does not implement the Clipboard API (navigator.clipboard is
  // undefined by default) -- stub just enough that the component's
  // await doesn't throw. The visible "Copied" text (gated on this await
  // succeeding) is the assertion that actually proves the call happened;
  // this jsdom environment does not make the stub itself spyable.
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: () => Promise.resolve() },
    configurable: true,
  });
});

it('checks the blocklist, copies to clipboard, and opens Inventory', async () => {
  vi.mocked(api.stageCommand).mockResolvedValue({ allowed: true });
  const onOpenInventory = vi.fn();
  const user = userEvent.setup();
  render(
    <ConsoleSuggestionCard
      command="interface GigabitEthernet0/1"
      sessionId="session-1"
      onOpenInventory={onOpenInventory}
    />,
  );

  await user.click(screen.getByRole('button', { name: /copy and open inventory/i }));

  expect(await screen.findByText(/copied/i)).toBeVisible();
  expect(api.stageCommand).toHaveBeenCalledWith('session-1', 'interface GigabitEthernet0/1');
  expect(onOpenInventory).toHaveBeenCalled();
});

it('shows a withheld notice instead of a working button for a blocked command', async () => {
  vi.mocked(api.stageCommand).mockRejectedValue(
    Object.assign(new Error('This command matches a blocked pattern (erase/reload/format/factory-reset)'), {
      code: 'blocked_command',
    }),
  );
  const onOpenInventory = vi.fn();
  const user = userEvent.setup();
  render(
    <ConsoleSuggestionCard command="erase startup-config" sessionId="session-1" onOpenInventory={onOpenInventory} />,
  );

  await user.click(screen.getByRole('button', { name: /copy and open inventory/i }));

  expect(await screen.findByText(/withheld/i)).toBeVisible();
  expect(onOpenInventory).not.toHaveBeenCalled();
});

it('does not claim a command was blocked when only the clipboard failed', async () => {
  vi.mocked(api.stageCommand).mockResolvedValue({ allowed: true });
  const onOpenInventory = vi.fn();
  const user = userEvent.setup();
  // Must come after setup(): user-event installs its own working clipboard
  // stub, which would otherwise mask the failure this test is about.
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: () => Promise.reject(new Error('clipboard denied')) },
    configurable: true,
  });
  render(
    <ConsoleSuggestionCard
      command="interface GigabitEthernet0/1"
      sessionId="session-1"
      onOpenInventory={onOpenInventory}
    />,
  );

  await user.click(screen.getByRole('button', { name: /copy and open inventory/i }));

  // The safety check passed -- saying "withheld" here would be a lie about
  // the command, not just a clipboard hiccup.
  expect(await screen.findByText(/blocked the clipboard/i)).toBeVisible();
  expect(screen.queryByText(/withheld/i)).not.toBeInTheDocument();
});
