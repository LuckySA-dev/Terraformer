import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { KeyRound, Send } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api } from '../../api/network';
import { AppState, QueryErrorState } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';
import { Modal } from '../../components/ui/Modal';
import { SelectField } from '../../components/ui/FormField';
import type { ProviderProfile, ProviderProfileInput } from '../../types/api';
import { ChatTranscript } from './ChatTranscript';
import { ModeToggle } from './ModeToggle';
import { ProviderProfileForm } from './ProviderProfileForm';
import { ProviderProfileList } from './ProviderProfileList';
import { useAssistantChat } from './useAssistantChat';

type ProviderDialog =
  | { mode: 'list' }
  | { mode: 'create' }
  | { mode: 'edit'; profile: ProviderProfile }
  | null;

// ponytail: session-lifetime in-memory cap, not server-enforced yet -- fine
// for a single-user local app where the operator watching the chat *is*
// the trust boundary; upgrade to a server-checked AssistantSession.auto_apply_count
// (already a column) if this ever needs to hold across tabs/restarts.
const MAX_AUTO_APPLIES_PER_SESSION = 5;

export function AssistantPage() {
  const queryClient = useQueryClient();
  const [providerDialog, setProviderDialog] = useState<ProviderDialog>(null);
  const [deleteTarget, setDeleteTarget] = useState<ProviderProfile>();
  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [activeSessionId, setActiveSessionId] = useState<string>();
  const [draft, setDraft] = useState('');
  const autoAppliedPlanIds = useRef(new Set<string>());
  const [applyingPlanId, setApplyingPlanId] = useState<string>();

  const profiles = useQuery({
    queryKey: ['provider-profiles'],
    queryFn: api.providerProfiles,
    retry: false,
  });
  const sessions = useQuery({
    queryKey: ['assistant-sessions'],
    queryFn: api.assistantSessions,
    retry: false,
  });

  const chat = useAssistantChat(activeSessionId);

  const createSession = useMutation({
    mutationFn: (providerProfileId: string) => api.createAssistantSession(providerProfileId),
    onSuccess: async (created) => {
      setActiveSessionId(created.id);
      await queryClient.invalidateQueries({ queryKey: ['assistant-sessions'] });
    },
  });

  const applyChangePlan = useMutation({
    mutationFn: (planId: string) => api.applyChangePlan(planId),
    onSettled: () => setApplyingPlanId(undefined),
  });

  useEffect(() => {
    if (chat.mode !== 'auto') return;
    const unapplied = chat.transcript.filter(
      (entry) => entry.role === 'change_plan' && entry.plan !== undefined,
    );
    for (const entry of unapplied) {
      const planId = entry.plan?.plan_id;
      if (planId === undefined || autoAppliedPlanIds.current.has(planId)) continue;
      if (autoAppliedPlanIds.current.size >= MAX_AUTO_APPLIES_PER_SESSION) {
        chat.setMode('confirm', false);
        break;
      }
      autoAppliedPlanIds.current.add(planId);
      setApplyingPlanId(planId);
      applyChangePlan.mutate(planId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- chat.setMode/transcript identity changes every render; re-running on mode alone is the intent
  }, [chat.mode, chat.transcript]);

  const saveProfile = useMutation({
    mutationFn: ({
      input,
      current,
    }: {
      input: Partial<ProviderProfileInput>;
      current?: ProviderProfile;
    }) =>
      current !== undefined
        ? api.updateProviderProfile(current.id, input)
        : api.createProviderProfile({
            name: input.name ?? '',
            base_url: input.base_url ?? '',
            model_id: input.model_id ?? '',
            ...(input.api_key !== undefined ? { api_key: input.api_key } : {}),
          }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['provider-profiles'] });
      setProviderDialog(null);
    },
  });

  const deleteProfile = useMutation({
    mutationFn: (profile: ProviderProfile) => api.deleteProviderProfile(profile.id),
    onSuccess: async () => {
      setDeleteTarget(undefined);
      await queryClient.invalidateQueries({ queryKey: ['provider-profiles'] });
    },
  });

  return (
    <div className="assistant-page">
      <header className="assistant-page__header">
        <h1>Assistant</h1>
        <Button onClick={() => setProviderDialog({ mode: 'list' })}>
          <KeyRound size={16} /> Provider profile
        </Button>
      </header>

      {sessions.isPending || profiles.isPending ? (
        <AppState kind="loading" title="Loading assistant" message="Reading assistant session metadata…" compact />
      ) : sessions.isError ? (
        <QueryErrorState error={sessions.error} onRetry={() => void sessions.refetch()} compact />
      ) : profiles.isError ? (
        <QueryErrorState error={profiles.error} onRetry={() => void profiles.refetch()} compact />
      ) : activeSessionId === undefined ? (
        profiles.data.length === 0 ? (
          <AppState
            kind="empty"
            title="No provider profiles yet"
            message="Add a provider profile before starting a chat."
          />
        ) : (
          <div className="assistant-page__new-chat">
            <SelectField
              label="Provider profile"
              value={selectedProfileId}
              onChange={(event) => setSelectedProfileId(event.target.value)}
            >
              <option value="">Choose a profile…</option>
              {profiles.data.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </SelectField>
            <Button
              variant="primary"
              busy={createSession.isPending}
              disabled={selectedProfileId === ''}
              onClick={() => createSession.mutate(selectedProfileId)}
            >
              New chat
            </Button>
            {createSession.error === null ? null : (
              <div className="form-error" role="alert">
                {createSession.error.message}
              </div>
            )}
          </div>
        )
      ) : (
        <div className="assistant-page__chat">
          <ModeToggle mode={chat.mode} onRequestChange={chat.setMode} />
          {chat.pendingModeError === undefined ? null : (
            <div className="form-error" role="alert">
              {chat.pendingModeError}
            </div>
          )}
          <ChatTranscript
            entries={chat.transcript}
            onApplyPlan={(planId) => {
              setApplyingPlanId(planId);
              applyChangePlan.mutate(planId);
            }}
            applyingPlanId={applyingPlanId}
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
              placeholder="Ask about a device, or request a change..."
            />
            <Button type="submit">
              <Send size={16} /> Send
            </Button>
          </form>
        </div>
      )}

      <Modal
        open={providerDialog !== null}
        title={
          providerDialog?.mode === 'edit'
            ? 'Edit provider profile'
            : providerDialog?.mode === 'create'
              ? 'New provider profile'
              : 'Provider profiles'
        }
        description={
          providerDialog?.mode === 'list'
            ? 'BYOK endpoints this application proxies to. No model runs in this application.'
            : 'Point at any OpenAI-compatible endpoint -- OpenAI itself, a self-hosted Ollama, or another compatible server.'
        }
        onClose={() => setProviderDialog(null)}
      >
        {providerDialog?.mode === 'list' ? (
          profiles.isPending ? (
            <AppState kind="loading" title="Loading profiles" message="Reading provider profile metadata…" compact />
          ) : profiles.isError ? (
            <QueryErrorState error={profiles.error} onRetry={() => void profiles.refetch()} compact />
          ) : (
            <ProviderProfileList
              profiles={profiles.data}
              onCreate={() => setProviderDialog({ mode: 'create' })}
              onEdit={(profile) => setProviderDialog({ mode: 'edit', profile })}
              onDelete={setDeleteTarget}
            />
          )
        ) : providerDialog?.mode === 'create' || providerDialog?.mode === 'edit' ? (
          <ProviderProfileForm
            {...(providerDialog.mode === 'edit' ? { profile: providerDialog.profile } : {})}
            onCancel={() => setProviderDialog(null)}
            onSubmit={(input) =>
              saveProfile
                .mutateAsync({
                  input,
                  ...(providerDialog.mode === 'edit' ? { current: providerDialog.profile } : {}),
                })
                .then(() => undefined)
            }
            error={saveProfile.error?.message}
          />
        ) : null}
      </Modal>

      <Modal
        open={deleteTarget !== undefined}
        title="Remove provider profile?"
        description="Assistant sessions using this profile will need a different one to keep chatting."
        onClose={() => setDeleteTarget(undefined)}
        size="small"
        footer={
          <>
            <Button onClick={() => setDeleteTarget(undefined)}>Cancel</Button>
            <Button
              variant="danger"
              busy={deleteProfile.isPending}
              onClick={() => {
                if (deleteTarget !== undefined) deleteProfile.mutate(deleteTarget);
              }}
            >
              Remove profile
            </Button>
          </>
        }
      >
        <div className="delete-summary">
          <div className="device-avatar">
            <KeyRound size={20} />
          </div>
          <div>
            <strong>{deleteTarget?.name}</strong>
          </div>
        </div>
        {deleteProfile.error === null ? null : (
          <div className="form-error" role="alert">
            {deleteProfile.error.message}
          </div>
        )}
      </Modal>
    </div>
  );
}
