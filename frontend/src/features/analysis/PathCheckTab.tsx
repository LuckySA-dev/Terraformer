import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../../api/network';
import { ApiError } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { InputField, SelectField } from '../../components/ui/FormField';

export function PathCheckTab({ snapshotId }: { snapshotId: string }) {
  const [sourceDeviceId, setSourceDeviceId] = useState('');
  const [destinationIp, setDestinationIp] = useState('');
  const devices = useQuery({ queryKey: ['devices'], queryFn: () => api.devices() });
  const check = useMutation({
    mutationFn: () => api.pathCheck(snapshotId, sourceDeviceId, destinationIp),
  });

  return (
    <div className="stack-form">
      <div className="form-grid form-grid--two">
        <SelectField
          label="Source device"
          value={sourceDeviceId}
          onChange={(event) => setSourceDeviceId(event.target.value)}
        >
          <option value="">Select a device</option>
          {(devices.data ?? []).map((device) => (
            <option key={device.id} value={device.id}>
              {device.name}
            </option>
          ))}
        </SelectField>
        <InputField
          label="Destination IPv4"
          placeholder="198.51.100.10"
          value={destinationIp}
          onChange={(event) => setDestinationIp(event.target.value)}
        />
      </div>
      <Button
        variant="primary"
        onClick={() => check.mutate()}
        busy={check.isPending}
        disabled={sourceDeviceId === '' || destinationIp === ''}
      >
        Check path
      </Button>
      {check.isError ? (
        <div className="connection-test__result connection-test__result--error" role="alert">
          <span>
            {check.error instanceof ApiError ? check.error.message : 'The check failed.'}
          </span>
        </div>
      ) : null}
      {check.data === undefined ? null : (
        <div className="analysis-trace">
          <strong>{check.data.disposition}</strong>
          <ol>
            {check.data.hops.map((hop, index) => (
              <li key={`${hop.hostname}-${String(index)}`}>
                <span className="mono">{hop.hostname}</span> {hop.action} — {hop.detail}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
