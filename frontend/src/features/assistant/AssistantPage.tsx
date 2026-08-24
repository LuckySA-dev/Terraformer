import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { KeyRound } from 'lucide-react';
import { useState } from 'react';
import { api } from '../../api/network';
import { AppState, QueryErrorState } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';
import { Modal } from '../../components/ui/Modal';
import type { ProviderProfile, ProviderProfileInput } from '../../types/api';
import { ProviderProfileForm } from './ProviderProfileForm';
import { ProviderProfileList } from './ProviderProfileList';

type ProviderDialog =
  | { mode: 'list' }
  | { mode: 'create' }
  | { mode: 'edit'; profile: ProviderProfile }
  | null;

export function AssistantPage() {
  const queryClient = useQueryClient();
  const [providerDialog, setProviderDialog] = useState<ProviderDialog>(null);
  const [deleteTarget, setDeleteTarget] = useState<ProviderProfile>();

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

      {sessions.isPending ? (
        <AppState kind="loading" title="Loading sessions" message="Reading assistant session metadata…" compact />
      ) : sessions.isError ? (
        <QueryErrorState error={sessions.error} onRetry={() => void sessions.refetch()} compact />
      ) : null}

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
