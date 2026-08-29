import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { Send } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../../api/client';
import { api } from '../../api/network';
import { AppState, InlineNotice, QueryErrorState } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';
import { ChatTranscript } from './ChatTranscript';
import { DeviceScopePicker } from './DeviceScopePicker';
import { ModelPicker, type ModelChoice } from './ModelPicker';
import { ModeToggle } from './ModeToggle';
import { ProviderKeysDialog } from './ProviderKeysDialog';
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

/**
 * Commands the panel answers itself, the way a CLI does -- typed into the same
 * line as everything else, answered without a round trip to the model.
 *
 * `/auto` is the risk acceptance. Typing it is the operator saying they will
 * let changes reach the device unattended, which is the same decision the
 * toggle's dialog asks for; there is no second prompt because the command was
 * already deliberate.
 */
const COMMANDS: { name: string; help: string }[] = [
  { name: '/auto', help: 'Apply changes as soon as they are drafted. You accept the risk.' },
  { name: '/manual', help: 'Ask before every apply. This is the default.' },
  {
    name: '/compact',
    help: 'Fold the older turns into a summary to free up context.',
  },
  { name: '/model', help: 'Switch model, or add a provider key.' },
  { name: '/clear', help: 'Start a new conversation.' },
  { name: '/help', help: 'List these commands.' },
];

export function AssistantChatPanel({
  deviceId,
  scopeHint,
  onOpenInventory,
}: AssistantChatPanelProps) {
  const queryClient = useQueryClient();
  const [activeSessionId, setActiveSessionId] = useState<string>();
  const [draft, setDraft] = useState('');
  const [keysOpen, setKeysOpen] = useState(false);
  /** Output from a command the panel answered itself, not from the model. */
  const [commandOutput, setCommandOutput] = useState<string | null>(null);
  const [modelsWanted, setModelsWanted] = useState<string[]>([]);
  // Only used before a session exists. Once one does, the session's own
  // provider/model is the truth -- mirroring it here would let the two drift.
  const [pendingChoice, setPendingChoice] = useState<ModelChoice | null>(null);
  // Same shape as pendingChoice: only consulted before a session exists.
  const [pendingScope, setPendingScope] = useState<string[] | null>(null);
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
  // One query per profile the picker has actually opened, rather than a single
  // query keyed on a "selected" profile: the menu lists every provider's models
  // at once, and refetching on each hover would make it flicker.
  const modelQueries = useQueries({
    queries: modelsWanted.map((profileId) => ({
      queryKey: ['provider-profile-models', profileId],
      queryFn: () => api.providerProfileModels(profileId),
      retry: false,
      staleTime: 5 * 60 * 1000,
    })),
  });
  const modelsByProfile: Record<string, string[] | undefined> = {};
  modelsWanted.forEach((profileId, index) => {
    const result = modelQueries[index];
    // An unreachable provider resolves to an empty list rather than staying
    // "Loading…" forever, so the menu can say so.
    modelsByProfile[profileId] = result?.isError === true ? [] : result?.data?.models;
  });
  const requestModels = useCallback((profileId: string) => {
    setModelsWanted((current) => (current.includes(profileId) ? current : [...current, profileId]));
  }, []);

  // Land on the model the operator used last rather than an empty picker, so a
  // fresh visit to the tab is one keystroke from a question. Sessions come back
  // newest-first. Derived rather than copied into state on mount: mirroring it
  // would need an effect to keep the two in step once the list loads.
  const lastUsed = sessions.data?.[0];
  const defaultChoice: ModelChoice | null =
    lastUsed === undefined
      ? null
      : { profileId: lastUsed.provider_profile_id, modelId: lastUsed.model_id };

  const devices = useQuery({
    queryKey: ['devices'],
    queryFn: api.devices,
    retry: false,
    enabled: deviceId === undefined,
  });

  const activeSession = sessions.data?.find((item) => item.id === activeSessionId);
  const chat = useAssistantChat(activeSessionId, activeSession?.mode ?? 'confirm');
  // The server's count is the only count that matters -- it is what the apply
  // endpoint enforces, and it survives a reload. The ref below is just
  // in-flight dedupe so one plan is not fired twice before the refetch lands.
  const autoAppliesUsed = activeSession?.auto_apply_count ?? 0;

  const createSession = useMutation({
    mutationFn: ({ profileId, modelId }: { profileId: string; modelId: string }) =>
      api.createAssistantSession(profileId, modelId, deviceId, scopeIds),
    onSuccess: async (created) => {
      setActiveSessionId(created.id);
      await queryClient.invalidateQueries({ queryKey: ['assistant-sessions'] });
    },
  });

  const setScope = useMutation({
    mutationFn: (scopeDeviceIds: string[]) => {
      if (activeSessionId === undefined) throw new Error('No conversation to scope yet.');
      return api.updateAssistantSessionScope(activeSessionId, scopeDeviceIds);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['assistant-sessions'] });
    },
  });

  // Switching model keeps the thread: the server repoints the same session and
  // re-probes capabilities, so the conversation above the composer survives.
  const switchModel = useMutation({
    mutationFn: ({ profileId, modelId }: { profileId: string; modelId: string }) => {
      if (activeSessionId === undefined) {
        return api.createAssistantSession(profileId, modelId, deviceId);
      }
      return api.updateAssistantSessionModel(activeSessionId, profileId, modelId);
    },
    onSuccess: async (updated) => {
      setActiveSessionId(updated.id);
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

  const hasKey = profiles.data.length > 0;
  // The model the composer will use: whatever this session already runs on,
  // or the last one picked before a session exists.
  const choice: ModelChoice | null =
    activeSession !== undefined
      ? { profileId: activeSession.provider_profile_id, modelId: activeSession.model_id }
      : (pendingChoice ?? defaultChoice);
  // Same precedence as the model: the live session owns its scope, and the
  // local pick only stands in until one exists.
  const scopeIds: string[] =
    activeSession !== undefined ? activeSession.scope_device_ids : (pendingScope ?? []);

  /** Returns true when the input was a command and must not reach the model. */
  const runCommand = (raw: string): boolean => {
    const [name] = raw.trim().split(/\s+/);
    if (name?.startsWith('/') !== true) return false;
    switch (name) {
      case '/auto':
        if (activeSessionId === undefined) {
          setCommandOutput('Send a message first -- there is no session to switch yet.');
          return true;
        }
        // Typing the command is the acceptance; the toggle's dialog asks for
        // the same thing in a different shape.
        chat.setMode('auto', true);
        setCommandOutput(
          'Auto mode. Changes are applied as soon as they are drafted, up to ' +
            `${String(MAX_AUTO_APPLIES_PER_SESSION)} per conversation. Type /manual to stop.`,
        );
        return true;
      case '/manual':
      case '/confirm':
        if (activeSessionId === undefined) {
          setCommandOutput('Send a message first -- there is no session to switch yet.');
          return true;
        }
        chat.setMode('confirm', false);
        setCommandOutput('Confirm mode. Every apply waits for you.');
        return true;
      case '/compact':
        if (activeSessionId === undefined) {
          setCommandOutput('Nothing to compact yet -- this conversation has not started.');
          return true;
        }
        chat.compact();
        setCommandOutput('Compacting the older turns...');
        return true;
      case '/model':
        setKeysOpen(true);
        setCommandOutput(null);
        return true;
      case '/clear':
        setActiveSessionId(undefined);
        setCommandOutput(null);
        return true;
      case '/help':
        setCommandOutput(COMMANDS.map((item) => `${item.name}  ${item.help}`).join('\n'));
        return true;
      default:
        setCommandOutput(`Unknown command ${name}. Type /help for the list.`);
        return true;
    }
  };

  const submit = (content: string) => {
    if (content.trim() === '') return;
    if (runCommand(content)) return;
    setCommandOutput(null);
    if (activeSessionId !== undefined) {
      chat.sendMessage(content);
      return;
    }
    if (choice === null) return;
    // The session is created behind the first message rather than in front of
    // it: the operator types, and the plumbing catches up. useAssistantChat
    // holds the message until the socket opens.
    chat.sendMessage(content);
    createSession.mutate({ profileId: choice.profileId, modelId: choice.modelId });
  };

  return (
    <div className="assistant-page__chat">
      <div className="assistant-panel__toolbar">
        {/* No scope line here before a chat starts: the empty state below
            already carries the same sentence, and printing it twice was the
            first thing the operator saw. */}
        {activeSessionId === undefined ? null : (
          <ModeToggle
            mode={chat.mode}
            onRequestChange={chat.setMode}
            autoAppliesRemaining={Math.max(0, MAX_AUTO_APPLIES_PER_SESSION - autoAppliesUsed)}
          />
        )}
        <div className="assistant-panel__toolbar-actions">
          {sessions.data.length === 0 ? null : (
            <select
              className="input select assistant-panel__sessions"
              aria-label="Conversation"
              value={activeSessionId ?? ''}
              onChange={(event) => {
                const next = event.target.value;
                setActiveSessionId(next === '' ? undefined : next);
                setDraft('');
              }}
            >
              <option value="">New chat</option>
              {sessions.data.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.model_id} · {new Date(item.created_at).toLocaleString()}
                </option>
              ))}
            </select>
          )}
          {activeSessionId === undefined ? null : (
            <Button size="small" onClick={() => setActiveSessionId(undefined)}>
              New chat
            </Button>
          )}
        </div>
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
      {activeSessionId !== undefined || chat.transcript.length > 0 ? (
        <ChatTranscript
          entries={chat.transcript}
          onApplyPlan={(planId) => applyChangePlan.mutate({ planId, automatic: false })}
          applyingPlanId={applyingPlanId}
          applyFailure={applyFailure}
          sessionId={activeSessionId ?? ''}
          onOpenInventory={onOpenInventory ?? (() => undefined)}
        />
      ) : (
        <div className="assistant-panel__blank">
          {/* The card keeps a readable width of its own: the band around it
              fills the page so the empty state stays centred rather than
              pinned to the top-left of a wide window. */}
          <div className="assistant-page__blank-inner">
            <AppState
              kind="empty"
              title={hasKey ? 'Ask anything' : 'Add a provider key to start'}
              message={hasKey ? scopeHint : 'The assistant proxies to a provider you supply. Pick "Manage provider keys" in the model menu below and paste an API key -- this app never runs or bundles a model.'}
              compact
            />
          </div>
        </div>
      )}
      {createSession.error === null ? null : (
        <div className="form-error" role="alert">{createSession.error.message}</div>
      )}
      {switchModel.error === null ? null : (
        <div className="form-error" role="alert">{switchModel.error.message}</div>
      )}
      {setScope.error === null ? null : (
        <div className="form-error" role="alert">{setScope.error.message}</div>
      )}
      <form
        className="assistant-page__composer"
        onSubmit={(event) => {
          event.preventDefault();
          submit(draft);
          setDraft('');
        }}
      >
        {commandOutput === null ? null : (
          <pre className="assistant-page__command-output" role="status">{commandOutput}</pre>
        )}
        {draft.startsWith('/') ? (
          <ul className="assistant-page__command-hints">
            {COMMANDS.filter((item) => item.name.startsWith(draft.trim().split(/\s+/)[0] ?? '/')).map(
              (item) => (
                <li key={item.name}>
                  <button type="button" onClick={() => setDraft(`${item.name} `)}>
                    <span className="mono">{item.name}</span> {item.help}
                  </button>
                </li>
              ),
            )}
          </ul>
        ) : null}
        <div className="assistant-page__composer-row">
          <span className="assistant-page__prompt" aria-hidden="true">&rsaquo;</span>
          <input
            className="assistant-page__prompt-input"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            aria-label="Message"
            placeholder={
              choice === null
                ? 'Pick a model to start...'
                : 'Ask, request a change, or type / for commands'
            }
            disabled={!hasKey}
          />
          <Button type="submit" disabled={!hasKey || choice === null || draft.trim() === ''}>
            <Send size={16} /> Send
          </Button>
        </div>
        <div className="assistant-page__composer-tools">
          <ModelPicker
            profiles={profiles.data}
            modelsByProfile={modelsByProfile}
            value={choice}
            onChange={(next) => {
              // With no session yet there is nothing to repoint, and creating
              // one here would probe the provider for a chat that may never
              // be sent. Remember the choice and let the first message do it.
              if (activeSessionId === undefined) setPendingChoice(next);
              else switchModel.mutate(next);
            }}
            onManageKeys={() => setKeysOpen(true)}
            onNeedModels={requestModels}
            busy={switchModel.isPending || createSession.isPending}
          />
          {deviceId !== undefined ? null : (
            <DeviceScopePicker
              devices={devices.data ?? []}
              value={scopeIds}
              onChange={(next) => {
                if (activeSessionId === undefined) setPendingScope(next);
                else setScope.mutate(next);
              }}
              busy={setScope.isPending}
              disabled={!hasKey}
            />
          )}
          {activeSession !== undefined && !activeSession.supports_tool_calling ? (
            <span className="assistant-page__composer-note">Chat only — no device tools</span>
          ) : null}
        </div>
      </form>
      <ProviderKeysDialog open={keysOpen} onClose={() => setKeysOpen(false)} />
    </div>
  );
}
