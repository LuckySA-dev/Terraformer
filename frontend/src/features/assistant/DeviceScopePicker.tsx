import { Check, ChevronDown, Cpu } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { Device } from '../../types/api';

interface DeviceScopePickerProps {
  devices: Device[];
  /** Selected device ids. Empty means every registered device. */
  value: string[];
  onChange: (deviceIds: string[]) => void;
  disabled?: boolean;
  busy?: boolean;
}

/**
 * Which devices the conversation is about.
 *
 * Context, not enforcement: it saves the operator pasting UUIDs so they can
 * say "shut SW1 and SW2 down", and the backend puts the names in the system
 * prompt. Every tool still takes an explicit device id and every change still
 * goes through preview and a human confirmation, so the label deliberately
 * does not promise the model is fenced in.
 */
export function DeviceScopePicker({
  devices,
  value,
  onChange,
  disabled = false,
  busy = false,
}: DeviceScopePickerProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return undefined;
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

  const selected = devices.filter((device) => value.includes(device.id));
  const label =
    value.length === 0
      ? 'All devices'
      : selected.length === 0
        ? `${String(value.length)} selected`
        : selected.map((device) => device.name).join(', ');

  const toggle = (deviceId: string) => {
    onChange(
      value.includes(deviceId)
        ? value.filter((id) => id !== deviceId)
        : [...value, deviceId],
    );
  };

  return (
    <div className="model-picker device-scope" ref={root}>
      <button
        type="button"
        className="model-picker__trigger"
        onClick={() => setOpen((current) => !current)}
        disabled={disabled || busy}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Devices: ${label}`}
      >
        <Cpu size={12} />
        <span className="model-picker__label">{label}</span>
        <ChevronDown size={12} />
      </button>
      {!open ? null : (
        <div className="model-picker__menu" role="menu">
          <button
            type="button"
            role="menuitem"
            className={value.length === 0 ? 'model-picker__item is-selected' : 'model-picker__item'}
            onClick={() => {
              onChange([]);
              setOpen(false);
            }}
          >
            <span>All devices</span>
            {value.length === 0 ? <Check size={12} /> : null}
          </button>
          {devices.length === 0 ? (
            <p className="model-picker__empty">No devices registered yet.</p>
          ) : (
            <div className="model-picker__group">
              <span className="model-picker__group-label">Only these</span>
              {devices.map((device) => (
                <button
                  key={device.id}
                  type="button"
                  role="menuitemcheckbox"
                  aria-checked={value.includes(device.id)}
                  className={
                    value.includes(device.id)
                      ? 'model-picker__item is-selected'
                      : 'model-picker__item'
                  }
                  // Stays open: picking "SW1 and SW2" is two clicks, and
                  // closing after the first would make the second a re-open.
                  onClick={() => toggle(device.id)}
                >
                  <span>{device.name}</span>
                  {value.includes(device.id) ? <Check size={12} /> : null}
                </button>
              ))}
            </div>
          )}
          <p className="model-picker__note">
            Tells the assistant which devices you mean. Every change still needs your review.
          </p>
        </div>
      )}
    </div>
  );
}
