import { useState } from 'react';
import { Button } from '../../components/ui/Button';
import { Modal } from '../../components/ui/Modal';
import type { AssistantSessionMode } from '../../types/api';

interface ModeToggleProps {
  mode: AssistantSessionMode;
  onRequestChange: (mode: AssistantSessionMode, riskAcknowledged: boolean) => void;
  /** Auto applies left in this chat, so the choice is made with the real number. */
  autoAppliesRemaining?: number | undefined;
}

export function ModeToggle({ mode, onRequestChange, autoAppliesRemaining }: ModeToggleProps) {
  const [confirmingAuto, setConfirmingAuto] = useState(false);
  const exhausted = autoAppliesRemaining !== undefined && autoAppliesRemaining <= 0;

  return (
    <div className="mode-toggle">
      <span className="mode-toggle__label">Applying changes</span>
      <Button
        {...(mode === 'confirm' ? { variant: 'primary' as const } : {})}
        onClick={() => onRequestChange('confirm', false)}
        title="Every change waits for you to press Apply"
      >
        Ask me first
      </Button>
      <Button
        {...(mode === 'auto' ? { variant: 'primary' as const } : {})}
        onClick={() => setConfirmingAuto(true)}
        disabled={exhausted && mode !== 'auto'}
        title={
          exhausted
            ? 'This chat has used its Auto allowance'
            : 'Changes are applied to the device without asking'
        }
      >
        Auto-apply
      </Button>
      {mode === 'auto' && autoAppliesRemaining !== undefined ? (
        <span className="mode-toggle__remaining">
          {`${String(autoAppliesRemaining)} auto-appl${autoAppliesRemaining === 1 ? 'y' : 'ies'} left`}
        </span>
      ) : null}

      <Modal
        open={confirmingAuto}
        title="Let the assistant apply changes without asking?"
        description={
          autoAppliesRemaining === undefined
            ? 'Change Plans will be sent to the device as soon as the assistant drafts them, with no per-change prompt. You are choosing to accept that risk. Every change is still validated, rendered and logged the same way, and console command suggestions always stay manual.'
            : `Change Plans will be sent to the device as soon as the assistant drafts them, with no per-change prompt. You are choosing to accept that risk. This chat can auto-apply ${String(autoAppliesRemaining)} more time${autoAppliesRemaining === 1 ? '' : 's'} before it switches back to asking you. Every change is still validated, rendered and logged the same way, and console command suggestions always stay manual.`
        }
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
              I accept the risk -- auto-apply
            </Button>
          </>
        }
      />
    </div>
  );
}
