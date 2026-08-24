import { Pencil, Plus, Trash2 } from 'lucide-react';
import type { ProviderProfile } from '../../types/api';
import { AppState } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';

interface ProviderProfileListProps {
  profiles: ProviderProfile[];
  onCreate: () => void;
  onEdit: (profile: ProviderProfile) => void;
  onDelete: (profile: ProviderProfile) => void;
}

export function ProviderProfileList({ profiles, onCreate, onEdit, onDelete }: ProviderProfileListProps) {
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
                <small>
                  {profile.model_id} · {profile.base_url}
                </small>
              </div>
              <div className="credential-row__actions">
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
    </div>
  );
}
