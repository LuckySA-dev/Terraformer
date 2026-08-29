import { ChangePlanCard } from '../inventory/ChangePlanCard';
import { ConsoleSuggestionCard } from './ConsoleSuggestionCard';
import type { AssistantTranscriptEntry } from './useAssistantChat';

interface ChatTranscriptProps {
  entries: AssistantTranscriptEntry[];
  onApplyPlan: (planId: string) => void;
  applyingPlanId?: string | undefined;
  /** Which plan the last apply failed on, and why. */
  applyFailure?: { planId: string; message: string } | undefined;
  sessionId: string;
  onOpenInventory: () => void;
}

const FENCE_PATTERN = /```[a-z]*\n([\s\S]*?)```/g;

function splitFencedBlocks(content: string): { text: string; commands: string[] } {
  const commands: string[] = [];
  const text = content.replace(FENCE_PATTERN, (_match, code: string) => {
    commands.push(code.trim());
    return '';
  });
  return { text: text.trim(), commands };
}

/**
 * One line describing what a tool returned.
 *
 * The payload used to be pretty-printed into the transcript in full, which was
 * tolerable when every tool read one device and unreadable once `get_topology`
 * could return the whole network -- the answer ended up hundreds of lines below
 * the question. The detail is still one click away.
 */
function summariseToolResult(payload: Record<string, unknown> | undefined): string {
  if (payload === undefined) return 'no result';
  if (typeof payload.error === 'string') return payload.error;
  const counts = Object.entries(payload)
    .filter((pair): pair is [string, unknown[]] => Array.isArray(pair[1]))
    .map(([key, value]) => `${String(value.length)} ${key.replaceAll('_', ' ')}`);
  if (counts.length > 0) return counts.join(', ');
  return `${String(Object.keys(payload).length)} fields`;
}

export function ChatTranscript({
  entries,
  onApplyPlan,
  applyingPlanId,
  applyFailure,
  sessionId,
  onOpenInventory,
}: ChatTranscriptProps) {
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
                {...(applyFailure?.planId === entry.plan.plan_id
                  ? { applyError: applyFailure.message }
                  : {})}
                applySuccess={false}
              />
            </div>
          );
        }
        if (entry.role === 'assistant' && entry.content) {
          const { text, commands } = splitFencedBlocks(entry.content);
          return (
            <div key={entry.id} className="chat-transcript__entry chat-transcript__entry--assistant">
              {text === '' ? null : <p>{text}</p>}
              {commands.map((command, index) => (
                <ConsoleSuggestionCard
                  key={`${entry.id}-command-${String(index)}`}
                  command={command}
                  sessionId={sessionId}
                  onOpenInventory={onOpenInventory}
                />
              ))}
            </div>
          );
        }
        if (entry.role === 'compacted') {
          return (
            <details key={entry.id} className="chat-transcript__compacted">
              <summary>
                Earlier turns compacted — what they established is carried forward
              </summary>
              <p>{entry.content}</p>
            </details>
          );
        }
        if (entry.role === 'tool') {
          return (
            <details key={entry.id} className="chat-transcript__entry chat-transcript__entry--tool">
              <summary>
                <span className="chat-transcript__tool-name">{entry.toolName ?? 'tool'}</span>
                <span className="chat-transcript__tool-summary">
                  {summariseToolResult(entry.toolPayload)}
                </span>
              </summary>
              {entry.toolPayload ? <pre>{JSON.stringify(entry.toolPayload, null, 2)}</pre> : null}
            </details>
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
