import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChangePlanCard } from '../src/features/inventory/ChangePlanCard';
import type { ChangePlan } from '../src/types/api';

const plan: ChangePlan = {
  id: 'a1b2c3d4-df32-4a9e-9df0-6e6f8a2b6a11',
  device_id: '2ad0db14-5a87-4147-a4e7-c98f88322464',
  status: 'draft',
  safety_level: 'C',
  risk: 'low',
  source: 'manual',
  failure_code: null,
  applied_at: null,
  steps: [
    {
      id: 'step-1',
      change_type: 'interface_description',
      target: 'GigabitEthernet0/1',
      previous_value: null,
      desired_value: 'uplink',
      rendered_commands: 'interface GigabitEthernet0/1\n description uplink',
      inverse_commands: 'interface GigabitEthernet0/1\n no description',
    },
  ],
  created_at: '2026-08-24T00:00:00Z',
  updated_at: '2026-08-24T00:00:00Z',
};

it('renders risk, safety level, and the rendered commands', () => {
  render(<ChangePlanCard plan={plan} onApply={vi.fn()} applyBusy={false} applySuccess={false} />);

  expect(screen.getByText('low risk')).toBeVisible();
  expect(screen.getByText(/Safety level C/)).toBeVisible();
  expect(screen.getByText(/interface GigabitEthernet0\/1/)).toBeVisible();
});

it('calls onApply with the plan id when clicked', async () => {
  const user = userEvent.setup();
  const onApply = vi.fn();
  render(<ChangePlanCard plan={plan} onApply={onApply} applyBusy={false} applySuccess={false} />);

  await user.click(screen.getByRole('button', { name: /apply/i }));

  expect(onApply).toHaveBeenCalledWith(plan.id);
});

it('disables Apply once the plan is no longer a draft', () => {
  render(
    <ChangePlanCard
      plan={{ ...plan, status: 'applied' }}
      onApply={vi.fn()}
      applyBusy={false}
      applySuccess={false}
    />,
  );

  expect(screen.getByRole('button', { name: /apply/i })).toBeDisabled();
});
