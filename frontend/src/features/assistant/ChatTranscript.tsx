import { ChangePlanCard } from '../inventory/ChangePlanCard';
import type { AssistantTranscriptEntry } from './useAssistantChat';

interface ChatTranscriptProps {
  entries: AssistantTranscriptEntry[];
  onApplyPlan: (planId: string) => void;
  applyingPlanId?: string | undefined;
}

export function ChatTranscript({ entries, onApplyPlan, applyingPlanId }: ChatTranscriptProps) {
  return (
    <div className="chat-transcript" role="log" aria-label="Assistant conversation">
      {entries.map((entry) => {
        if (entry.role === 'change_plan' && entry.plan) {
          return (
            <div key={entry.id} className="chat-transcript__entry chat-transcript__entry--plan">
              <ChangePlanCard
                plan={{
                  id: entry.plan.plan_id,
                  device_id: '',
                  status: entry.plan.status as never,
                  safety_level: entry.plan.safety_level as never,
                  risk: entry.plan.risk as never,
                  source: 'ai_generated',
                  failure_code: null,
                  applied_at: null,
                  steps: entry.plan.steps.map((step, index) => ({
                    id: `${entry.id}-step-${String(index)}`,
                    change_type: 'interface_description',
                    target: step.target,
                    previous_value: null,
                    desired_value: step.desired_value,
                    rendered_commands: step.rendered_commands,
                    inverse_commands: '',
                  })),
                  created_at: '',
                  updated_at: '',
                }}
                onApply={onApplyPlan}
                applyBusy={applyingPlanId === entry.plan.plan_id}
                applySuccess={false}
              />
            </div>
          );
        }
        return (
          <div key={entry.id} className={`chat-transcript__entry chat-transcript__entry--${entry.role}`}>
            {entry.content}
          </div>
        );
      })}
    </div>
  );
}
