import { Settings2 } from 'lucide-react';
import { useState } from 'react';
import { InlineNotice } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';
import { InputField, SelectField } from '../../components/ui/FormField';
import type { StagedChange } from './InterfaceEditor';
import type { BgpNeighborEntry, RouterNetworkEntry } from './configCatalog';

interface RoutingFormProps {
  onPreview: (change: StagedChange) => void;
  previewBusy: boolean;
  /** Cleared by the parent whenever a new change is staged. */
  onDirty: () => void;
  /** "Apply" or "Preview", depending on the window's apply mode. */
  submitLabel: string;
}

/**
 * One network statement in a RIP, EIGRP or OSPF process, plus RIP's version.
 *
 * The protocol comes from the tree entry, so the operator never assembles
 * "ospf 1" by hand. Each field submits on its own because a Change Plan
 * carries exactly one change type -- the version and the network are two
 * different ones, and staging them together would be a backend change.
 */
export function RouterNetworkForm({
  entry,
  onPreview,
  previewBusy,
  onDirty,
  submitLabel,
}: RoutingFormProps & { entry: RouterNetworkEntry }) {
  const [processId, setProcessId] = useState('');
  const [network, setNetwork] = useState('');
  const [action, setAction] = useState<'add' | 'remove'>('add');
  const [version, setVersion] = useState('');

  const isRip = entry.protocol === 'rip';
  const target = isRip ? 'rip' : `${entry.protocol} ${processId.trim()}`;
  const missingProcess = !isRip && processId.trim() === '';
  const removing = action === 'remove';

  return (
    <div className="config-window__form">
      {isRip ? null : (
        <InputField
          label="Process ID"
          inputMode="numeric"
          value={processId}
          onChange={(event) => {
            setProcessId(event.target.value);
            onDirty();
          }}
          placeholder="1"
          hint="1-65535. Local to this device -- it does not have to match its neighbours."
        />
      )}

      {isRip ? (
        // Same shape as an interface field: a control and its own submit.
        <div className="interface-editor__field">
          <SelectField
            label="Version"
            value={version}
            onChange={(event) => {
              setVersion(event.target.value);
              onDirty();
            }}
            hint="v1 and v2 do not interoperate, so changing this drops every adjacency the process has."
          >
            <option value="">Select</option>
            <option value="2">2</option>
            <option value="1">1</option>
          </SelectField>
          <Button
            size="small"
            busy={previewBusy}
            disabled={version === ''}
            onClick={() =>
              onPreview({
                changeType: 'router_rip_version',
                target: 'rip',
                desiredValue: version,
              })
            }
          >
            <Settings2 size={13} /> {submitLabel} version
          </Button>
        </div>
      ) : null}

      <SelectField
        label="Action"
        value={action}
        onChange={(event) => {
          setAction(event.target.value === 'remove' ? 'remove' : 'add');
          onDirty();
        }}
      >
        <option value="add">Add this network</option>
        <option value="remove">Remove this network</option>
      </SelectField>

      <InputField
        label="Network"
        value={network}
        onChange={(event) => {
          setNetwork(event.target.value);
          onDirty();
        }}
        placeholder={entry.placeholder}
        hint={entry.hint}
      />

      <InlineNotice
        tone="warning"
        title={removing ? 'Removing withdraws what it advertises' : 'Starting a process is part of this change'}
      >
        {removing
          ? 'Whatever reaches this network through this device stops reaching it. The process must already carry the statement -- withdrawing one it does not have would roll back by adding it.'
          : `If ${isRip ? 'RIP' : target} is not running yet, this starts it -- and the rollback then removes the whole process, not just this network.`}
      </InlineNotice>

      <Button
        size="small"
        busy={previewBusy}
        disabled={missingProcess || network.trim() === ''}
        onClick={() =>
          onPreview({
            changeType: removing ? 'router_network_remove' : 'router_network',
            target,
            desiredValue: network.trim(),
          })
        }
      >
        <Settings2 size={13} /> {submitLabel} network
      </Button>
    </div>
  );
}

/**
 * One BGP peer. A device runs a single BGP process, so the local AS is part of
 * the target rather than something that can differ per neighbour.
 */
export function BgpNeighborForm({
  entry,
  onPreview,
  previewBusy,
  onDirty,
  submitLabel,
}: RoutingFormProps & { entry: BgpNeighborEntry }) {
  const [localAs, setLocalAs] = useState('');
  const [peer, setPeer] = useState('');
  const [remoteAs, setRemoteAs] = useState('');

  const incomplete = [localAs, peer, remoteAs].some((value) => value.trim() === '');

  return (
    <div className="config-window__form">
      <InputField
        label="Local AS"
        inputMode="numeric"
        value={localAs}
        onChange={(event) => {
          setLocalAs(event.target.value);
          onDirty();
        }}
        placeholder="65001"
        hint={entry.hint}
      />
      <InputField
        label="Neighbour address"
        value={peer}
        onChange={(event) => {
          setPeer(event.target.value);
          onDirty();
        }}
        placeholder="192.0.2.2"
      />
      <InputField
        label="Remote AS"
        inputMode="numeric"
        value={remoteAs}
        onChange={(event) => {
          setRemoteAs(event.target.value);
          onDirty();
        }}
        placeholder="65002"
      />
      <InlineNotice tone="warning" title="A session can move a lot of reachability at once">
        If BGP is not running yet this starts it, and the rollback then removes the whole process.
        Re-pointing a peer that already exists withdraws it first, because IOS will not hold two
        remote-as values for one neighbour.
      </InlineNotice>
      <Button
        size="small"
        busy={previewBusy}
        disabled={incomplete}
        onClick={() =>
          onPreview({
            changeType: 'bgp_neighbor',
            target: `bgp ${localAs.trim()}`,
            desiredValue: `${peer.trim()} remote-as ${remoteAs.trim()}`,
          })
        }
      >
        <Settings2 size={13} /> {submitLabel} neighbour
      </Button>
    </div>
  );
}
