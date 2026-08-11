import { Pencil, Plus, Trash2 } from 'lucide-react';
import type { CredentialProfile } from '../../types/api';
import { AppState } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';

interface CredentialListProps {
  credentials: CredentialProfile[];
  onCreate: () => void;
  onEdit: (credential: CredentialProfile) => void;
  onDelete: (credential: CredentialProfile) => void;
}

export function CredentialList({ credentials, onCreate, onEdit, onDelete }: CredentialListProps) {
  return (
    <div className="credential-list-stack">
      <div className="credential-list-toolbar">
        <span>{credentials.length} saved {credentials.length === 1 ? 'profile' : 'profiles'}</span>
        <Button size="small" onClick={onCreate}>
          <Plus size={14} /> New profile
        </Button>
      </div>
      {credentials.length === 0 ? (
        <AppState
          kind="empty"
          title="No credential profiles yet"
          message="Create one to reuse across devices without attaching secrets to a device record."
          compact
        />
      ) : (
        <div className="credential-list">
          {credentials.map((credential) => (
            <div key={credential.id} className="credential-row">
              <div>
                <strong>{credential.name}</strong>
                <small>
                  {credential.has_enable_password ? 'Password and enable password set' : 'Password set'}
                </small>
              </div>
              <div className="credential-row__actions">
                <Button
                  size="small"
                  variant="ghost"
                  className="button--icon-only"
                  onClick={() => onEdit(credential)}
                  aria-label={`Edit ${credential.name}`}
                >
                  <Pencil size={14} />
                </Button>
                <Button
                  size="small"
                  variant="ghost"
                  className="button--icon-only"
                  onClick={() => onDelete(credential)}
                  aria-label={`Delete ${credential.name}`}
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
