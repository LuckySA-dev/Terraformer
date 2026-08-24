import { useState } from 'react';
import { Button } from '../../components/ui/Button';
import { Modal } from '../../components/ui/Modal';
import type { AssistantSessionMode } from '../../types/api';

interface ModeToggleProps {
  mode: AssistantSessionMode;
  onRequestChange: (mode: AssistantSessionMode, riskAcknowledged: boolean) => void;
}

export function ModeToggle({ mode, onRequestChange }: ModeToggleProps) {
  const [confirmingAuto, setConfirmingAuto] = useState(false);

  return (
    <div className="mode-toggle">
      <Button
        {...(mode === 'confirm' ? { variant: 'primary' as const } : {})}
        onClick={() => onRequestChange('confirm', false)}
      >
        Confirm
      </Button>
      <Button {...(mode === 'auto' ? { variant: 'primary' as const } : {})} onClick={() => setConfirmingAuto(true)}>
        Auto
      </Button>

      <Modal
        open={confirmingAuto}
        title="Enable Auto mode?"
        description="The assistant will apply Change Plans without asking you to confirm each one, up to a per-session limit. You are choosing to accept that risk. Console command suggestions still always require you to review and send them yourself."
        onClose={() => setConfirmingAuto(false)}
        size="small"
        footer={
          <>
            <Button onClick={() => setConfirmingAuto(false)}>Cancel</Button>
            <Button
              variant="danger"
              onClick={() => {
                onRequestChange('auto', true);
                setConfirmingAuto(false);
              }}
            >
              I understand the risk -- enable Auto
            </Button>
          </>
        }
      />
    </div>
  );
}
