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
import type { ProviderProfileTestResult } from './ProviderProfileList';

type ProviderDialog = { mode: 'create' } | { mode: 'edit'; profile: ProviderProfile } | null;

/**
 * Provider keys, reachable from inside the conversation.
 *
 * Adding a key is a rare, one-off act; picking a model is constant. Keeping
 * keys behind the model picker means the common action is one click and the
 * rare one is still never more than two -- and neither leaves the chat.
 */
export function ProviderKeysDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [providerDialog, setProviderDialog] = useState<ProviderDialog>(null);
  const [deleteTarget, setDeleteTarget] = useState<ProviderProfile>();

  const profiles = useQuery({
    queryKey: ['provider-profiles'],
    queryFn: api.providerProfiles,
    retry: false,
    enabled: open,
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
            ...(input.provider_type !== undefined ? { provider_type: input.provider_type } : {}),
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

  const testProfile = useMutation({
    mutationFn: (profile: ProviderProfile) => api.providerProfileModels(profile.id),
  });
  const profileTestResult: ProviderProfileTestResult | undefined =
    testProfile.variables === undefined
      ? undefined
      : testProfile.isSuccess
        ? {
            profileId: testProfile.variables.id,
            ok: true,
            message:
              testProfile.data.models.length > 0
                ? `Reachable -- ${String(testProfile.data.models.length)} model(s) available.`
                : 'Reachable, but the provider returned no models.',
          }
        : testProfile.isError
          ? {
              profileId: testProfile.variables.id,
              ok: false,
              message: 'Could not reach that endpoint.',
            }
          : undefined;

  return (
    <>
      <Modal
        open={open && providerDialog === null && deleteTarget === undefined}
        title="Provider keys"
        description="Add a key once, then pick any of its models from the composer. This app never runs or bundles a model."
        onClose={onClose}
        size="large"
      >
        {profiles.isPending ? (
          <AppState kind="loading" title="Loading profiles" message="Reading provider metadata…" compact />
        ) : profiles.isError ? (
          <QueryErrorState error={profiles.error} onRetry={() => void profiles.refetch()} compact />
        ) : (
          <div className="provider-keys-panel">
            <ProviderProfileList
              profiles={profiles.data}
              onCreate={() => setProviderDialog({ mode: 'create' })}
              onEdit={(profile) => setProviderDialog({ mode: 'edit', profile })}
              onDelete={setDeleteTarget}
              onTest={(profile) => testProfile.mutate(profile)}
              testingProfileId={testProfile.isPending ? testProfile.variables.id : undefined}
              testResult={profileTestResult}
            />
          </div>
        )}
      </Modal>

      <Modal
        open={providerDialog !== null}
        title={providerDialog?.mode === 'edit' ? 'Edit provider profile' : 'New provider profile'}
        description="Pick your provider and paste its API key -- the base URL is filled in for you."
        onClose={() => setProviderDialog(null)}
      >
        {providerDialog === null ? null : (
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
        )}
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
    </>
  );
}
