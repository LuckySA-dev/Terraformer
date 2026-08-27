import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Send } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../../api/client';
import { api } from '../../api/network';
import { AppState, InlineNotice, QueryErrorState } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';
import { InputField, SelectField } from '../../components/ui/FormField';
import { ChatTranscript } from './ChatTranscript';
import { ModeToggle } from './ModeToggle';
import { useAssistantChat } from './useAssistantChat';

// Mirrors MAX_AUTO_APPLIES_PER_SESSION in the backend. This copy only stops
// the UI from firing a request that the server would reject anyway -- the
// limit that actually holds is counted server-side against the session, so a
// page reload cannot hand out a fresh allowance.
const MAX_AUTO_APPLIES_PER_SESSION = 5;

interface AssistantChatPanelProps {
  /** Pins the conversation to one device. Omit for a workspace-wide chat. */
  deviceId?: string | undefined;
  /** Shown above the composer to explain what this particular chat can see. */
  scopeHint: string;
  onOpenInventory?: (() => void) | undefined;
}

export function AssistantChatPanel({
  deviceId,
  scopeHint,
  onOpenInventory,
}: AssistantChatPanelProps) {
  const queryClient = useQueryClient();
  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [selectedModelId, setSelectedModelId] = useState('');
  const [activeSessionId, setActiveSessionId] = useState<string>();
  const [draft, setDraft] = useState('');
  const autoAppliedPlanIds = useRef(new Set<string>());

  const scope = deviceId === undefined ? 'workspace' : 'device';

  const profiles = useQuery({
    queryKey: ['provider-profiles'],
    queryFn: api.providerProfiles,
    retry: false,
  });
  // Scoped server-side: a device's chats must never include another device's,
  // and the workspace chat must not be buried under every device conversation.
  const sessions = useQuery({
    queryKey: ['assistant-sessions', scope, deviceId ?? null],
    queryFn: () => api.assistantSessions(scope, deviceId),
    retry: false,
  });
  const profileModels = useQuery({
    queryKey: ['provider-profile-models', selectedProfileId],
    queryFn: () => api.providerProfileModels(selectedProfileId),
    enabled: selectedProfileId !== '',
    retry: false,
  });

  const activeSession = sessions.data?.find((item) => item.id === activeSessionId);
  const chat = useAssistantChat(activeSessionId, activeSession?.mode ?? 'confirm');
  // The server's count is the only count that matters -- it is what the apply
  // endpoint enforces, and it survives a reload. The ref below is just
  // in-flight dedupe so one plan is not fired twice before the refetch lands.
  const autoAppliesUsed = activeSession?.auto_apply_count ?? 0;

  const createSession = useMutation({
    mutationFn: ({ profileId, modelId }: { profileId: string; modelId: string }) =>
      api.createAssistantSession(profileId, modelId, deviceId),
    onSuccess: async (created) => {
      setActiveSessionId(created.id);
      await queryClient.invalidateQueries({ queryKey: ['assistant-sessions'] });
    },
  });

  const applyChangePlan = useMutation({
    // The session id travels only with an Auto-fired apply: that is what the
    // server charges against the allowance. A human pressing Apply sends
    // none and is never rate-limited.
    mutationFn: ({ planId, automatic }: { planId: string; automatic: boolean }) =>
      api.applyChangePlan(planId, automatic ? activeSessionId : undefined),
    onSettled: async () => {
      // Refetch so the remaining-allowance figure reflects what the server
      // just counted rather than a local guess.
      await queryClient.invalidateQueries({ queryKey: ['assistant-sessions'] });
    },
  });
  // Derived from the mutation rather than mirrored into state: one source of
  // truth, and no setState inside the auto-apply effect.
  const applyingPlanId = applyChangePlan.isPending
    ? applyChangePlan.variables.planId
    : undefined;
  // A failed apply used to be silent -- the card simply stopped spinning, so
  // a locked device, an exhausted Auto allowance or an unreachable switch all
  // looked identical to success.
  const applyFailure =
    applyChangePlan.isError
      ? {
          planId: applyChangePlan.variables.planId,
          message: applyChangePlan.error.message,
        }
      : undefined;

  useEffect(() => {
    if (chat.mode !== 'auto') return;
    const unapplied = chat.transcript.filter(
      (entry) => entry.role === 'change_plan' && entry.plan !== undefined,
    );
    for (const entry of unapplied) {
      const planId = entry.plan?.plan_id;
      if (planId === undefined || autoAppliedPlanIds.current.has(planId)) continue;
      if (autoAppliesUsed >= MAX_AUTO_APPLIES_PER_SESSION) {
        chat.setMode('confirm', false);
        break;
      }
      autoAppliedPlanIds.current.add(planId);
      applyChangePlan.mutate({ planId, automatic: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- chat.setMode/transcript identity changes every render; re-running on mode alone is the intent
  }, [chat.mode, chat.transcript]);

  const gatewayDisabled =
    (profiles.error instanceof ApiError && profiles.error.code === 'ai_gateway_disabled_by_policy') ||
    (sessions.error instanceof ApiError && sessions.error.code === 'ai_gateway_disabled_by_policy');

  if (gatewayDisabled) {
    return (
      <AppState
        kind="unsupported"
        title="The assistant is turned off"
        message="This local deployment has AI_GATEWAY_ENABLED=false (the default). Set it to true in .env and restart the stack to turn the assistant on."
        compact
      />
    );
  }

  if (profiles.isPending || sessions.isPending) {
    return <AppState kind="loading" title="Loading assistant" message="Reading chat metadata…" compact />;
  }
  if (profiles.isError) {
    return <QueryErrorState error={profiles.error} onRetry={() => void profiles.refetch()} compact />;
  }
  if (sessions.isError) {
    return <QueryErrorState error={sessions.error} onRetry={() => void sessions.refetch()} compact />;
  }

  // The gate the whole feature hangs on: no key, no AI anywhere.
  if (profiles.data.length === 0) {
    return (
      <AppState
        kind="empty"
        title="Add an API key first"
        message="The assistant needs a provider profile before it can help here. Open the Assistant tab in the sidebar and add one -- you only need an API key."
      />
    );
  }

  if (activeSessionId === undefined) {
    const previous = sessions.data;
    return (
      <div className="assistant-panel__start">
        <InlineNotice tone="info" title="What this chat can see">
          {scopeHint}
        </InlineNotice>
        <SelectField
          label="Provider profile"
          value={selectedProfileId}
          onChange={(event) => {
            setSelectedProfileId(event.target.value);
            setSelectedModelId('');
          }}
        >
          <option value="">Choose a profile…</option>
          {profiles.data.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </SelectField>
        {selectedProfileId === '' ? null : (
          <>
            <InputField
              label="Model"
              placeholder="gpt-4o, claude-opus-5, llama3.1…"
              autoComplete="off"
              list={`assistant-models-${scope}`}
              value={selectedModelId}
              onChange={(event) => setSelectedModelId(event.target.value)}
              hint={
                profileModels.isPending
                  ? 'Loading available models…'
                  : profileModels.isError
                    ? 'Could not fetch the model list -- type the model ID by hand.'
                    : profileModels.data.models.length > 0
                      ? `${String(profileModels.data.models.length)} model(s) available -- pick one or type your own.`
                      : 'The provider returned no models -- type the model ID by hand.'
              }
            />
            <datalist id={`assistant-models-${scope}`}>
              {profileModels.data?.models.map((model) => <option key={model} value={model} />)}
            </datalist>
          </>
        )}
        <Button
          variant="primary"
          busy={createSession.isPending}
          disabled={selectedProfileId === '' || selectedModelId.trim() === ''}
          onClick={() =>
            createSession.mutate({
              profileId: selectedProfileId,
              modelId: selectedModelId.trim(),
            })
          }
        >
          New chat
        </Button>
        {createSession.error === null ? null : (
          <div className="form-error" role="alert">
            {createSession.error.message}
          </div>
        )}
        {previous.length === 0 ? null : (
          <div className="assistant-panel__history">
            <span className="field__hint">Earlier conversations here</span>
            {previous.map((item) => (
              <button
                key={item.id}
                type="button"
                className="assistant-panel__history-item"
                onClick={() => setActiveSessionId(item.id)}
              >
                <strong>{item.model_id}</strong>
                <small>{new Date(item.created_at).toLocaleString()}</small>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="assistant-page__chat">
      <div className="assistant-panel__toolbar">
        <ModeToggle
          mode={chat.mode}
          onRequestChange={chat.setMode}
          autoAppliesRemaining={Math.max(0, MAX_AUTO_APPLIES_PER_SESSION - autoAppliesUsed)}
        />
        <Button size="small" onClick={() => setActiveSessionId(undefined)}>
          Leave chat
        </Button>
      </div>
      {activeSession && !activeSession.supports_tool_calling ? (
        <InlineNotice tone="warning" title="No device tools for this model">
          This model didn&apos;t report tool-calling support, so it can chat but can&apos;t read
          devices or draft Change Plans. Start a new chat with a different model for that.
        </InlineNotice>
      ) : null}
      {chat.connectionState === 'closed' ? (
        <InlineNotice tone="warning" title="Disconnected">
          The assistant connection closed. Start a new chat to keep going -- this conversation is
          saved and will reload.
        </InlineNotice>
      ) : null}
      {chat.pendingModeError === undefined ? null : (
        <div className="form-error" role="alert">
          {chat.pendingModeError}
        </div>
      )}
      <ChatTranscript
        entries={chat.transcript}
        onApplyPlan={(planId) => applyChangePlan.mutate({ planId, automatic: false })}
        applyingPlanId={applyingPlanId}
        applyFailure={applyFailure}
        sessionId={activeSessionId}
        onOpenInventory={onOpenInventory ?? (() => undefined)}
      />
      <form
        className="assistant-page__composer"
        onSubmit={(event) => {
          event.preventDefault();
          if (draft.trim() === '') return;
          chat.sendMessage(draft);
          setDraft('');
        }}
      >
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          aria-label="Message"
          placeholder="Ask about this, or request a change..."
        />
        <Button type="submit">
          <Send size={16} /> Send
        </Button>
      </form>
    </div>
  );
}
