import { ArrowLeft, Pencil, Settings2 } from 'lucide-react';
import { useState } from 'react';
import { AppState } from '../../components/ui/AppState';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { InputField, SelectField } from '../../components/ui/FormField';
import type { ChangeType, DeviceInterface } from '../../types/api';

export interface StagedChange {
  changeType: ChangeType;
  target: string;
  desiredValue: string;
}

interface InterfaceEditorProps {
  interfaces: DeviceInterface[];
  loading: boolean;
  /** Staged for preview. One change type per plan -- the API takes one. */
  onPreview: (change: StagedChange) => void;
  previewBusy: boolean;
  /** Cleared by the parent whenever a new change is staged. */
  onDirty: () => void;
  /** "Apply" or "Preview", depending on the window's apply mode. */
  submitLabel: string;
}

const adminLabel = (iface: DeviceInterface): string =>
  iface.admin_up === null ? 'unknown' : iface.admin_up ? 'up' : 'down';

/**
 * The interface list, and the editor that opens on one of its rows.
 *
 * Description, port status and access VLAN used to be three separate entries
 * in the category tree, each starting from an empty form: the operator had to
 * know the current value and retype it to change one field. Here the row is
 * picked once and every field starts on what the device actually reported, so
 * a change is an edit rather than a re-entry.
 *
 * Each field previews on its own because a Change Plan carries one change
 * type. Staging them together would have to be a backend change, not a UI one.
 */
export function InterfaceEditor({
  interfaces,
  loading,
  onPreview,
  previewBusy,
  onDirty,
  submitLabel,
}: InterfaceEditorProps) {
  const [editingName, setEditingName] = useState<string | null>(null);
  const [description, setDescription] = useState('');
  const [adminState, setAdminState] = useState('');
  const [accessVlan, setAccessVlan] = useState('');

  const editing = interfaces.find((iface) => iface.name === editingName) ?? null;

  const startEditing = (iface: DeviceInterface) => {
    setEditingName(iface.name);
    // Pre-fill from observed state. `?? ''` rather than a placeholder: an
    // empty description is a real value, and typing over a placeholder would
    // silently send the placeholder text to the device.
    setDescription(iface.description ?? '');
    setAdminState(iface.admin_up === null ? '' : iface.admin_up ? 'up' : 'down');
    // Access VLAN is not part of the interface read, so there is nothing
    // truthful to pre-fill it with. Left blank and labelled.
    setAccessVlan('');
    onDirty();
  };

  if (loading) {
    return <AppState kind="loading" title="Reading interfaces" message="Loading observed interface state…" compact />;
  }

  if (interfaces.length === 0) {
    return (
      <AppState
        kind="empty"
        title="No interfaces recorded"
        message="Refresh observed state on this device to collect its interface inventory first."
        compact
      />
    );
  }

  if (editing === null) {
    return (
      <div className="interface-table-wrap">
        <table className="interface-table">
          <caption className="sr-only">Interfaces on this device</caption>
          <thead>
            <tr>
              <th scope="col">Interface</th>
              <th scope="col">Description</th>
              <th scope="col">Admin</th>
              <th scope="col">Link</th>
              <th scope="col">IPv4</th>
              <th scope="col" />
            </tr>
          </thead>
          <tbody>
            {interfaces.map((iface) => (
              <tr key={iface.id}>
                <td className="mono">{iface.name}</td>
                <td>{iface.description ?? <span className="interface-table__empty">—</span>}</td>
                <td>
                  <Badge tone={iface.admin_up === false ? 'danger' : iface.admin_up ? 'success' : 'neutral'} dot>
                    {adminLabel(iface)}
                  </Badge>
                </td>
                <td>
                  <Badge tone={iface.oper_up ? 'success' : 'neutral'} dot>
                    {iface.oper_up === null ? 'unknown' : iface.oper_up ? 'up' : 'down'}
                  </Badge>
                </td>
                <td className="mono">
                  {iface.ipv4_addresses.length === 0
                    ? <span className="interface-table__empty">—</span>
                    : iface.ipv4_addresses.join(', ')}
                </td>
                <td>
                  <Button size="small" onClick={() => startEditing(iface)}>
                    <Pencil size={12} /> Edit
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const stage = (changeType: ChangeType, desiredValue: string) => {
    onPreview({ changeType, target: editing.name, desiredValue });
  };
  const currentAdmin = adminLabel(editing);

  return (
    <div className="interface-editor">
      <div className="interface-editor__head">
        <Button size="small" variant="ghost" onClick={() => setEditingName(null)}>
          <ArrowLeft size={13} /> All interfaces
        </Button>
        <strong className="mono">{editing.name}</strong>
        <Badge tone={editing.oper_up ? 'success' : 'neutral'} dot>
          link {editing.oper_up === null ? 'unknown' : editing.oper_up ? 'up' : 'down'}
        </Badge>
      </div>

      <div className="interface-editor__field">
        <InputField
          label="Description"
          value={description}
          onChange={(event) => {
            setDescription(event.target.value);
            onDirty();
          }}
          hint={
            editing.description === null
              ? 'No description on the device right now.'
              : `Currently "${editing.description}".`
          }
        />
        <Button
          size="small"
          busy={previewBusy}
          disabled={description === (editing.description ?? '')}
          onClick={() => stage('interface_description', description)}
        >
          <Settings2 size={13} /> {submitLabel}
        </Button>
      </div>

      <div className="interface-editor__field">
        <SelectField
          label="Port status"
          value={adminState}
          onChange={(event) => {
            setAdminState(event.target.value);
            onDirty();
          }}
          hint={`Device reports admin ${currentAdmin}.`}
        >
          <option value="">Select</option>
          <option value="up">up</option>
          <option value="down">down</option>
        </SelectField>
        <Button
          size="small"
          busy={previewBusy}
          disabled={adminState === '' || adminState === currentAdmin}
          onClick={() => stage('interface_admin_state', adminState)}
        >
          <Settings2 size={13} /> {submitLabel}
        </Button>
      </div>

      <div className="interface-editor__field">
        <InputField
          label="Access VLAN"
          inputMode="numeric"
          value={accessVlan}
          onChange={(event) => {
            setAccessVlan(event.target.value);
            onDirty();
          }}
          placeholder="20"
          hint="Not part of the interface read, so this starts blank rather than showing a guess. The VLAN must already exist on the switch."
        />
        <Button
          size="small"
          busy={previewBusy}
          disabled={accessVlan.trim() === ''}
          onClick={() => stage('interface_access_vlan', accessVlan.trim())}
        >
          <Settings2 size={13} /> {submitLabel}
        </Button>
      </div>

      <div className="interface-editor__field interface-editor__field--readonly">
        <div>
          <span className="field__label-text">IPv4 address</span>
          <p className="mono">
            {editing.ipv4_addresses.length === 0 ? '—' : editing.ipv4_addresses.join(', ')}
          </p>
          <span className="field__hint">
            Read-only. Changing the address a device is managed on can cut the session applying it,
            so it needs its own guard before this becomes editable.
          </span>
        </div>
      </div>
    </div>
  );
}
