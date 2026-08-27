import { Pencil, Plus, PlugZap, Trash2 } from 'lucide-react';
import type { ProviderProfile } from '../../types/api';
import { AppState } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';

export interface ProviderProfileTestResult {
  profileId: string;
  ok: boolean;
  message: string;
}

interface ProviderProfileListProps {
  profiles: ProviderProfile[];
  onCreate: () => void;
  onEdit: (profile: ProviderProfile) => void;
  onDelete: (profile: ProviderProfile) => void;
  onTest: (profile: ProviderProfile) => void;
  testingProfileId?: string | undefined;
  testResult?: ProviderProfileTestResult | undefined;
}

export function ProviderProfileList({
  profiles,
  onCreate,
  onEdit,
  onDelete,
  onTest,
  testingProfileId,
  testResult,
}: ProviderProfileListProps) {
  return (
    <div className="credential-list-stack">
      <div className="credential-list-toolbar">
        <span>{profiles.length} saved {profiles.length === 1 ? 'profile' : 'profiles'}</span>
        <Button size="small" onClick={onCreate}>
          <Plus size={14} /> New profile
        </Button>
      </div>
      {profiles.length === 0 ? (
        <AppState
          kind="empty"
          title="No provider profiles yet"
          message="Add one to connect the assistant to an OpenAI-compatible endpoint."
          compact
        />
      ) : (
        <div className="credential-list">
          {profiles.map((profile) => (
            <div key={profile.id} className="credential-row">
              <div>
                <strong>{profile.name}</strong>
                <small>{profile.base_url}</small>
                {testResult?.profileId === profile.id ? (
                  <span
                    className={`mini-result ${testResult.ok ? 'mini-result--success' : 'mini-result--error'}`}
                    role="status"
                  >
                    {testResult.message}
                  </span>
                ) : null}
              </div>
              <div className="credential-row__actions">
                <Button
                  size="small"
                  variant="ghost"
                  busy={testingProfileId === profile.id}
                  onClick={() => onTest(profile)}
                  aria-label={`Test connection for ${profile.name}`}
                >
                  <PlugZap size={14} /> Test
                </Button>
                <Button
                  size="small"
                  variant="ghost"
                  className="button--icon-only"
                  onClick={() => onEdit(profile)}
                  aria-label={`Edit ${profile.name}`}
                >
                  <Pencil size={14} />
                </Button>
                <Button
                  size="small"
                  variant="ghost"
                  className="button--icon-only"
                  onClick={() => onDelete(profile)}
                  aria-label={`Delete ${profile.name}`}
                >
                  <Trash2 size={14} />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
      <p className="field__hint">
        A profile is just a connection -- you pick the model, and the assistant checks it can
        read devices, each time you start a new chat.
      </p>
    </div>
  );
}
