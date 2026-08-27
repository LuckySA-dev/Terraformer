import { Check, ChevronDown, KeyRound, Loader2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { ProviderProfile } from '../../types/api';

export interface ModelChoice {
  profileId: string;
  modelId: string;
}

interface ModelPickerProps {
  profiles: ProviderProfile[];
  /** Model ids per profile id, as reported by each provider. */
  modelsByProfile: Record<string, string[] | undefined>;
  value: ModelChoice | null;
  onChange: (choice: ModelChoice) => void;
  onManageKeys: () => void;
  /** True while a switch is in flight, so the trigger can show progress. */
  busy?: boolean;
  disabled?: boolean;
  /** Called when a profile's list is needed and has not been fetched yet. */
  onNeedModels?: (profileId: string) => void;
}

/**
 * The model selector that sits in the composer, the way Cursor, opencode and
 * Claude Code place it -- next to the message you are about to send, rather
 * than in a settings screen you have to leave the conversation for.
 *
 * Profiles are grouped headers rather than a separate control: an operator
 * thinks "which model", not "which of my API keys, then which model".
 */
export function ModelPicker({
  profiles,
  modelsByProfile,
  value,
  onChange,
  onManageKeys,
  busy = false,
  disabled = false,
  onNeedModels,
}: ModelPickerProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    // Pointerdown, not click: a click listener would also catch the very click
    // that opened the menu on some browsers and close it immediately.
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && root.current?.contains(event.target) !== true) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    for (const profile of profiles) {
      if (modelsByProfile[profile.id] === undefined) onNeedModels?.(profile.id);
    }
  }, [open, profiles, modelsByProfile, onNeedModels]);

  const activeProfile = profiles.find((profile) => profile.id === value?.profileId);
  const label = value === null ? 'Choose a model' : value.modelId;

  return (
    <div className="model-picker" ref={root}>
      <button
        type="button"
        className="model-picker__trigger"
        onClick={() => setOpen((current) => !current)}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Model: ${label}`}
      >
        {busy ? <Loader2 size={12} className="model-picker__spin" /> : null}
        <span className="model-picker__label">{label}</span>
        {activeProfile === undefined ? null : (
          <span className="model-picker__provider">{activeProfile.name}</span>
        )}
        <ChevronDown size={12} />
      </button>
      {!open ? null : (
        <div className="model-picker__menu" role="menu">
          {profiles.length === 0 ? (
            <p className="model-picker__empty">No provider key yet.</p>
          ) : (
            profiles.map((profile) => {
              const models = modelsByProfile[profile.id];
              return (
                <div key={profile.id} className="model-picker__group">
                  <span className="model-picker__group-label">{profile.name}</span>
                  {models === undefined ? (
                    <span className="model-picker__note">Loading models…</span>
                  ) : models.length === 0 ? (
                    <span className="model-picker__note">
                      This provider returned no model list.
                    </span>
                  ) : (
                    models.map((modelId) => {
                      const selected =
                        value?.profileId === profile.id && value.modelId === modelId;
                      return (
                        <button
                          key={`${profile.id}:${modelId}`}
                          type="button"
                          role="menuitem"
                          className={
                            selected ? 'model-picker__item is-selected' : 'model-picker__item'
                          }
                          onClick={() => {
                            setOpen(false);
                            if (!selected) onChange({ profileId: profile.id, modelId });
                          }}
                        >
                          <span>{modelId}</span>
                          {selected ? <Check size={12} /> : null}
                        </button>
                      );
                    })
                  )}
                </div>
              );
            })
          )}
          <button
            type="button"
            role="menuitem"
            className="model-picker__manage"
            onClick={() => {
              setOpen(false);
              onManageKeys();
            }}
          >
            <KeyRound size={12} /> Manage provider keys
          </button>
        </div>
      )}
    </div>
  );
}
