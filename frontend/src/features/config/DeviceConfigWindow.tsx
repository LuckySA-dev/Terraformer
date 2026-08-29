import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Lock, Save, Settings2, ShieldCheck, Terminal, Undo2, X, Zap } from 'lucide-react';
import { useState } from 'react';
import { api } from '../../api/network';
import { AppState, InlineNotice } from '../../components/ui/AppState';
import { Badge, type BadgeTone } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { InputField, SelectField } from '../../components/ui/FormField';
import type { ChangePlan, ChangePlanStatus, Device, Job } from '../../types/api';
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

/**
 * Auto sends the change the moment it renders; Confirm stages the plan and
 * waits for a second click. Auto is the default: filling the form and pressing
 * the button is already the operator's decision, and a preview that is always
 * accepted is a click rather than a choice.
 */
type ApplyMode = 'auto' | 'confirm';

/**
 * What the operator is told for each state a plan can land on. Apply runs in
 * the worker, so this is the only place the window can report what actually
 * happened on the device.
 */
const OUTCOME: Record<ChangePlanStatus, { tone: 'ok' | 'bad' | 'wait'; text: string }> = {
  draft: { tone: 'wait', text: 'Queued for the worker.' },
  applying: { tone: 'wait', text: 'Sending to the device…' },
  applied: { tone: 'ok', text: 'Applied. The post-check read the new value back from the device.' },
  failed: { tone: 'bad', text: 'The device rejected it. Nothing was changed to put back.' },
  rolled_back: {
    tone: 'bad',
    text: 'It failed, and the inverse commands were sent to put the device back.',
  },
  rollback_failed: {
    tone: 'bad',
    text: 'It failed and the rollback failed too. The device is in an unknown state -- check it directly.',
  },
};

function ApplyOutcome({
  plan,
  busy,
  error,
}: {
  plan: ChangePlan;
  busy: boolean;
  error?: string | undefined;
}) {
  // `busy` covers the gap between the click and the worker picking the plan
  // up, when the row still reads 'draft'.
  const outcome = busy && plan.status === 'draft' ? OUTCOME.applying : OUTCOME[plan.status];
  return (
    <div className={`config-outcome config-outcome--${outcome.tone}`} role="status">
      <strong>{outcome.text}</strong>
      {plan.failure_code === null ? null : (
        <span className="config-outcome__code mono">{plan.failure_code}</span>
      )}
      {error === undefined ? null : <span className="form-error">{error}</span>}
    </div>
  );
}

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
  const [applyMode, setApplyMode] = useState<ApplyMode>('auto');
  const { position, frameRef, dragHandlers } = useDraggableWindow(
    initialPosition ?? { x: 132, y: 78 },
  );

  const entry = findEntry(entryId) ?? FIRST_AVAILABLE_ENTRY;

  const interfaces = useQuery({
    queryKey: ['devices', device.id, 'interfaces'],
    queryFn: () => api.interfaces(device.id),
    retry: false,
  });
  // Apply is queued to the worker, so the status a plan lands on arrives after
  // the request that queued it. Without this the window said "Apply queued"
  // and then never mentioned the change again -- the operator had no way to
  // learn from here whether the device took it.
  const history = useQuery({
    queryKey: ['change-plans', device.id],
    queryFn: () => api.listChangePlans(device.id),
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.status === 'applying') === true ? 1_000 : false,
  });
  const apply = useMutation<Job, Error, string>({
    mutationFn: (planId: string) => api.applyChangePlan(planId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['change-plans', device.id] });
    },
  });
  // Both mutations name their generics: inference collapsed TError to `never`
  // once these two started referring to each other, which hid the very errors
  // these forms exist to show.
  const preview = useMutation<ChangePlan, Error, StagedChange>({
    mutationFn: (staged: StagedChange) =>
      api.previewChange({
        device_id: device.id,
        change_type: staged.changeType,
        target: staged.target,
        desired_value: staged.desiredValue,
      }),
    onSuccess: (created) => {
      setPlan(created);
      if (applyMode === 'auto') apply.mutate(created.id);
    },
  });

  const previewSimple = () => {
    // Unreachable through the UI -- an unavailable entry renders no form --
    // but the guard keeps that a property of this function rather than of
    // the markup that happens to call it.
    // Both the generic target/value form and the global one-value form go
    // through here; the interface editor and save action stage their own.
    if (!entry.available) return;
    if (entry.kind !== undefined && entry.kind !== 'global-text') return;
    preview.mutate({ changeType: entry.changeType, target, desiredValue });
  };
  const saveConfig = useMutation({
    mutationFn: () => api.saveRunningConfig(device.id),
  });

  const canApply = device.capabilities.some((item) => item.name === 'apply' && item.supported);

  /**
   * The live row for the staged plan. The copy returned by preview is a
   * snapshot whose status stays 'draft' forever, so reading status off it left
   * Apply clickable on a plan that had already been sent.
   */
  const staged = plan === null ? null : (history.data?.find((item) => item.id === plan.id) ?? plan);
  const applyStarted = apply.isPending || apply.isSuccess || apply.isError;
  const submitLabel = applyMode === 'auto' ? 'Apply' : 'Preview';
  /** What the equivalent-commands pane says about the staged plan right now. */
  const commandsBadge: { tone: BadgeTone; text: string } =
    staged === null
      ? { tone: 'neutral', text: 'NOTHING STAGED' }
      : staged.status === 'applied'
        ? { tone: 'success', text: 'ON THE DEVICE' }
        : staged.status === 'failed' ||
            staged.status === 'rolled_back' ||
            staged.status === 'rollback_failed'
          ? { tone: 'danger', text: 'FAILED' }
          : applyStarted
            ? { tone: 'warning', text: 'SENDING' }
            : { tone: 'warning', text: 'NOT YET SENT' };

  // Also clears the mutations: their error and success state outlived the form
  // that produced them, so a failed preview stayed on screen after switching
  // to an unrelated entry.
  const resetPlan = () => {
    setPlan(null);
    preview.reset();
    apply.reset();
  };
  const selectEntry = (next: ConfigEntry) => {
    setEntryId(next.id);
    setTarget('');
    setDesiredValue('');
    resetPlan();
  };

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
            onPreview={(change) => preview.mutate(change)}
            submitLabel={submitLabel}
          />
        </div>
      );
    }
    if (entry.kind === 'save-config') {
      return (
        <div className="config-window__form">
          <InlineNotice tone="warning" title="No preview, and no way back">
            This writes the running configuration over startup-config. It changes nothing that is
            running now -- what it changes is that the current state survives a reload, which is
            the recovery path you would otherwise still have. The previous startup-config is gone
            once this succeeds, so there is nothing to roll back and no plan to review first.
          </InlineNotice>
          <Button
            size="small"
            variant="danger"
            busy={saveConfig.isPending}
            onClick={() => saveConfig.mutate()}
          >
            <Save size={14} /> Write to startup-config
          </Button>
          {saveConfig.error === null ? null : (
            <div className="form-error" role="alert">{saveConfig.error.message}</div>
          )}
          {!saveConfig.isSuccess ? null : (
            <div className="mini-result mini-result--success" role="status">
              <Check size={14} />
              <span>The device confirmed the save.</span>
            </div>
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
            <Settings2 size={14} /> {submitLabel}
          </Button>
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
        ) : entry.changeType === 'static_route' ? (
          <InputField
            label="Destination prefix"
            value={target}
            onChange={(event) => {
              setTarget(event.target.value);
              resetPlan();
            }}
            placeholder="10.10.0.0/16"
            hint="The prefix length is required -- 10.10.0.0 on its own would be read as a single host, not a network. Use 0.0.0.0/0 for a default route."
          />
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
        ) : entry.changeType === 'interface_trunk_vlans' ? (
          <InputField
            label="Allowed VLANs"
            value={desiredValue}
            onChange={(event) => {
              setDesiredValue(event.target.value);
              resetPlan();
            }}
            placeholder="1,10,20-30"
            hint="Replaces the whole list -- any VLAN left out stops crossing this link. A port that is not already trunking is switched to trunk mode, and the rollback puts the mode back."
          />
        ) : entry.changeType === 'static_route' ? (
          <InputField
            label="Next hop"
            value={desiredValue}
            onChange={(event) => {
              setDesiredValue(event.target.value);
              resetPlan();
            }}
            placeholder="192.0.2.1"
            hint="An IPv4 address, or an exit interface name. If this prefix already has a route, the old one is withdrawn in the same change rather than left beside the new one."
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
          <Settings2 size={14} /> {submitLabel}
        </Button>
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

      <div className="mode-toggle config-window__mode">
        <span className="mode-toggle__label">On submit</span>
        <Button
          {...(applyMode === 'auto' ? { variant: 'primary' as const } : {})}
          size="small"
          onClick={() => setApplyMode('auto')}
          title="The change is sent to the device as soon as it renders"
        >
          <Zap size={12} /> Send it
        </Button>
        <Button
          {...(applyMode === 'confirm' ? { variant: 'primary' as const } : {})}
          size="small"
          onClick={() => setApplyMode('confirm')}
          title="Stage the plan and wait for a second click"
        >
          <ShieldCheck size={12} /> Review first
        </Button>
      </div>

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
        <div className="config-window__pane">
          {renderForm()}
          {preview.error === null ? null : (
            <div className="form-error" role="alert">{preview.error.message}</div>
          )}
          {staged === null || !entry.available || entry.kind === 'save-config' ? null : applyStarted ? (
            <ApplyOutcome
              plan={staged}
              busy={apply.isPending}
              error={apply.error?.message}
            />
          ) : applyMode === 'confirm' ? (
            // Reached only before apply has started, so it carries no apply
            // error or success of its own -- once either exists, applyStarted
            // is true and the branch above renders instead.
            <ChangePlanCard
              plan={staged}
              onApply={(planId) => apply.mutate(planId)}
              applyBusy={false}
              applySuccess={false}
            />
          ) : null}
        </div>
      </div>

      {/* Packet Tracer keeps an equivalent-commands pane pinned to the bottom.
          Here it also carries the inverse commands, which is what a Level C
          rollback would actually send and is shown nowhere else in the UI --
          so the pane says something the plan card above it does not. */}
      <footer className="config-window__commands">
        <div className="config-window__commands-head">
          <Terminal size={12} />
          <strong>Equivalent IOS commands</strong>
          <Badge tone={commandsBadge.tone}>{commandsBadge.text}</Badge>
        </div>
        <pre className="config-window__command-list" aria-label="Equivalent IOS commands">
          {staged === null
            ? 'Stage a change to see the exact commands it sends.'
            : linesOf(staged, 'rendered_commands')}
        </pre>
        {staged === null ? null : (
          <>
            <div className="config-window__commands-head">
              <Undo2 size={12} />
              <strong>Rollback would send</strong>
            </div>
            <pre className="config-window__command-list" aria-label="Rollback commands">
              {linesOf(staged, 'inverse_commands')}
            </pre>
          </>
        )}
      </footer>
    </div>
  );
}
