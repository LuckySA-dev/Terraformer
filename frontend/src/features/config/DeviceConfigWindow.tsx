import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Lock, Settings2, Terminal, Undo2, X } from 'lucide-react';
import { useState } from 'react';
import { api } from '../../api/network';
import { AppState, InlineNotice } from '../../components/ui/AppState';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { InputField, SelectField } from '../../components/ui/FormField';
import type { ChangePlan, Device } from '../../types/api';
import { ChangePlanCard } from '../inventory/ChangePlanCard';
import { InterfaceEditor, type StagedChange } from './InterfaceEditor';
import {
  CONFIG_SECTIONS,
  FIRST_AVAILABLE_ENTRY,
  entriesInSection,
  findEntry,
  type ConfigEntry,
} from './configCatalog';
import { useDraggableWindow } from './useDraggableWindow';

interface DeviceConfigWindowProps {
  device: Device;
  onClose: () => void;
  /** Overridable so a test can place the window deterministically. */
  initialPosition?: { x: number; y: number };
}

/** Splits the stored newline-joined command text into displayable lines. */
const linesOf = (plan: ChangePlan, field: 'rendered_commands' | 'inverse_commands'): string =>
  plan.steps
    .flatMap((step) => step[field].split('\n'))
    .filter((line) => line !== '')
    .join('\n');

export function DeviceConfigWindow({
  device,
  onClose,
  initialPosition,
}: DeviceConfigWindowProps) {
  const queryClient = useQueryClient();
  const [entryId, setEntryId] = useState(FIRST_AVAILABLE_ENTRY.id);
  const [target, setTarget] = useState('');
  const [desiredValue, setDesiredValue] = useState('');
  const [plan, setPlan] = useState<ChangePlan | null>(null);
  const { position, frameRef, dragHandlers } = useDraggableWindow(
    initialPosition ?? { x: 132, y: 78 },
  );

  const entry = findEntry(entryId) ?? FIRST_AVAILABLE_ENTRY;

  const interfaces = useQuery({
    queryKey: ['devices', device.id, 'interfaces'],
    queryFn: () => api.interfaces(device.id),
    retry: false,
  });
  const preview = useMutation({
    mutationFn: (staged: StagedChange) =>
      api.previewChange({
        device_id: device.id,
        change_type: staged.changeType,
        target: staged.target,
        desired_value: staged.desiredValue,
      }),
    onSuccess: setPlan,
  });

  const previewSimple = () => {
    // Unreachable through the UI -- an unavailable entry renders no form --
    // but the guard keeps that a property of this function rather than of
    // the markup that happens to call it.
    if (!entry.available || entry.kind === 'interface-editor') return;
    preview.mutate({ changeType: entry.changeType, target, desiredValue });
  };
  const apply = useMutation({
    mutationFn: (planId: string) => api.applyChangePlan(planId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['change-plans', device.id] });
    },
  });

  const canApply = device.capabilities.some((item) => item.name === 'apply' && item.supported);

  const selectEntry = (next: ConfigEntry) => {
    setEntryId(next.id);
    setTarget('');
    setDesiredValue('');
    setPlan(null);
  };
  const resetPlan = () => setPlan(null);

  const renderForm = () => {
    if (!entry.available) {
      return (
        <div className="config-window__unavailable">
          <AppState
            kind="empty"
            title={`${entry.label} is not available yet`}
            message={entry.reason}
          />
        </div>
      );
    }
    if (!canApply) {
      return (
        <AppState
          kind="empty"
          title="Structured configuration unavailable"
          message="This driver has no verified apply capability for this vendor yet."
        />
      );
    }
    if (entry.kind === 'interface-editor') {
      return (
        <div className="config-window__form">
          <InterfaceEditor
            interfaces={interfaces.data ?? []}
            loading={interfaces.isPending}
            previewBusy={preview.isPending}
            onDirty={resetPlan}
            onPreview={(staged) => preview.mutate(staged)}
          />
          {preview.error === null ? null : (
            <div className="form-error" role="alert">{preview.error.message}</div>
          )}
          {plan === null ? null : (
            <ChangePlanCard
              plan={plan}
              onApply={(planId) => apply.mutate(planId)}
              applyBusy={apply.isPending}
              applyError={apply.error?.message}
              applySuccess={apply.isSuccess}
            />
          )}
        </div>
      );
    }
    if (entry.kind === 'global-text') {
      return (
        <div className="config-window__form">
          <InputField
            label={entry.valueLabel}
            value={desiredValue}
            onChange={(event) => {
              setDesiredValue(event.target.value);
              resetPlan();
            }}
            placeholder={entry.placeholder}
            hint={entry.hint}
          />
          <Button
            size="small"
            onClick={previewSimple}
            busy={preview.isPending}
            disabled={desiredValue.trim() === ''}
          >
            <Settings2 size={14} /> Preview
          </Button>
          {preview.error === null ? null : (
            <div className="form-error" role="alert">{preview.error.message}</div>
          )}
          {plan === null ? null : (
            <ChangePlanCard
              plan={plan}
              onApply={(planId) => apply.mutate(planId)}
              applyBusy={apply.isPending}
              applyError={apply.error?.message}
              applySuccess={apply.isSuccess}
            />
          )}
        </div>
      );
    }
    return (
      <div className="config-window__form">
        {entry.targetsInterface ? (
          <SelectField
            label="Interface"
            value={target}
            onChange={(event) => {
              setTarget(event.target.value);
              resetPlan();
            }}
          >
            <option value="">Select an interface</option>
            {(interfaces.data ?? []).map((iface) => (
              <option key={iface.id} value={iface.name}>
                {iface.name}
              </option>
            ))}
          </SelectField>
        ) : (
          <InputField
            label="VLAN id"
            inputMode="numeric"
            value={target}
            onChange={(event) => {
              setTarget(event.target.value);
              resetPlan();
            }}
            placeholder="10"
            hint="1-4094, excluding the 1002-1005 range IOS reserves."
          />
        )}
        {entry.changeType === 'vlan_name' ? (
          <InputField
            label="VLAN name"
            value={desiredValue}
            onChange={(event) => {
              setDesiredValue(event.target.value);
              resetPlan();
            }}
            placeholder="USERS"
            hint="Letters, digits, hyphen and underscore only."
          />
        ) : entry.changeType === 'interface_access_vlan' ? (
          <InputField
            label="Access VLAN id"
            inputMode="numeric"
            value={desiredValue}
            onChange={(event) => {
              setDesiredValue(event.target.value);
              resetPlan();
            }}
            placeholder="20"
            hint="The VLAN must already exist on this switch -- create it first if it does not."
          />
        ) : entry.changeType === 'interface_admin_state' ? (
          <SelectField
            label="Port status"
            value={desiredValue}
            onChange={(event) => {
              setDesiredValue(event.target.value);
              resetPlan();
            }}
          >
            <option value="">Select</option>
            <option value="up">up</option>
            <option value="down">down</option>
          </SelectField>
        ) : (
          <InputField
            label="Description"
            value={desiredValue}
            onChange={(event) => {
              setDesiredValue(event.target.value);
              resetPlan();
            }}
            placeholder="uplink-to-lab-core"
          />
        )}
        <Button
          size="small"
          onClick={previewSimple}
          busy={preview.isPending}
          disabled={target === '' || desiredValue === ''}
        >
          <Settings2 size={14} /> Preview
        </Button>
        {preview.error === null ? null : (
          <div className="form-error" role="alert">{preview.error.message}</div>
        )}
        {plan === null ? null : (
          <ChangePlanCard
            plan={plan}
            onApply={(planId) => apply.mutate(planId)}
            applyBusy={apply.isPending}
            applyError={apply.error?.message}
            applySuccess={apply.isSuccess}
          />
        )}
      </div>
    );
  };

  return (
    <div
      ref={frameRef as React.RefObject<HTMLDivElement>}
      className="config-window"
      style={{ left: position.x, top: position.y }}
      role="dialog"
      aria-label={`Configure ${device.name}`}
    >
      <header className="config-window__bar" {...dragHandlers}>
        <span className="config-window__title">
          <Settings2 size={14} />
          <strong>{device.name}</strong>
          <span className="mono">{device.management_address}</span>
        </span>
        <button
          type="button"
          className="icon-button"
          onClick={onClose}
          aria-label="Close configuration window"
        >
          <X size={15} />
        </button>
      </header>

      <InlineNotice tone="warning" title="Best effort, not auto-rollback">
        Preview shows the exact commands and risk before anything is sent. Applying can change the
        device; recovery on failure requires connectivity.
      </InlineNotice>

      <div className="config-window__body">
        <nav className="config-window__tree" aria-label="Configuration categories">
          {CONFIG_SECTIONS.map((section) => (
            <div key={section.id} className="config-window__group">
              <span className="config-window__group-label">{section.label}</span>
              {entriesInSection(section.id).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={
                    item.id === entry.id
                      ? 'config-window__item is-active'
                      : 'config-window__item'
                  }
                  aria-current={item.id === entry.id ? 'true' : undefined}
                  onClick={() => selectEntry(item)}
                >
                  <span>{item.label}</span>
                  {item.available ? null : <Lock size={11} aria-label="Not implemented" />}
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="config-window__pane">{renderForm()}</div>
      </div>

      {/* Packet Tracer keeps an equivalent-commands pane pinned to the bottom.
          Here it also carries the inverse commands, which is what a Level C
          rollback would actually send and is shown nowhere else in the UI --
          so the pane says something the plan card above it does not. */}
      <footer className="config-window__commands">
        <div className="config-window__commands-head">
          <Terminal size={12} />
          <strong>Equivalent IOS commands</strong>
          <Badge tone={plan === null ? 'neutral' : 'warning'}>
            {plan === null ? 'NOTHING STAGED' : 'NOT YET SENT'}
          </Badge>
        </div>
        <pre className="config-window__command-list" aria-label="Equivalent IOS commands">
          {plan === null
            ? 'Preview a change to see the exact commands it would send.'
            : linesOf(plan, 'rendered_commands')}
        </pre>
        {plan === null ? null : (
          <>
            <div className="config-window__commands-head">
              <Undo2 size={12} />
              <strong>Rollback would send</strong>
            </div>
            <pre className="config-window__command-list" aria-label="Rollback commands">
              {linesOf(plan, 'inverse_commands')}
            </pre>
          </>
        )}
      </footer>
    </div>
  );
}
