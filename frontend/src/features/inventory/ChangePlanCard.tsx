import { Check, ShieldCheck } from 'lucide-react';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import type { ChangePlan } from '../../types/api';

interface ChangePlanCardProps {
  plan: ChangePlan;
  onApply: (planId: string) => void;
  applyBusy: boolean;
  applyError?: string | undefined;
  applySuccess: boolean;
}

export function ChangePlanCard({ plan, onApply, applyBusy, applyError, applySuccess }: ChangePlanCardProps) {
  return (
    <div className="configure-preview">
      <div>
        <Badge tone={plan.risk === 'high' ? 'danger' : 'success'}>{plan.risk} risk</Badge>
        <Badge tone="neutral">Safety level {plan.safety_level} · best effort</Badge>
      </div>
      {plan.steps.map((step) => (
        <div key={step.id} className="configure-preview__step">
          <p>
            {step.target}: <span className="mono">{step.previous_value ?? '(none)'}</span> →{' '}
            <span className="mono">{step.desired_value}</span>
          </p>
          <pre>{step.rendered_commands}</pre>
        </div>
      ))}
      <Button
        variant="primary"
        size="small"
        onClick={() => onApply(plan.id)}
        busy={applyBusy}
        disabled={plan.status !== 'draft'}
      >
        <ShieldCheck size={14} /> Apply
      </Button>
      {applyError === undefined ? null : (
        <div className="form-error" role="alert">
          {applyError}
        </div>
      )}
      {applySuccess ? (
        <div className="mini-result mini-result--success" role="status">
          <Check size={14} />
          <span>Apply queued. The status below updates when the worker finishes.</span>
        </div>
      ) : null}
    </div>
  );
}
