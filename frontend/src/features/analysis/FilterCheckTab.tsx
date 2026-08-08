import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../../api/network';
import { ApiError } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { InputField, SelectField } from '../../components/ui/FormField';

export function FilterCheckTab({ snapshotId }: { snapshotId: string }) {
  const [deviceId, setDeviceId] = useState('');
  const [filterName, setFilterName] = useState('');
  const [destinationIp, setDestinationIp] = useState('');
  const [protocol, setProtocol] = useState<'tcp' | 'udp' | 'icmp'>('tcp');
  const [destinationPort, setDestinationPort] = useState('');
  const devices = useQuery({ queryKey: ['devices'], queryFn: () => api.devices() });
  const check = useMutation({
    mutationFn: () =>
      api.filterCheck(snapshotId, {
        device_id: deviceId,
        filter_name: filterName,
        destination_ip: destinationIp,
        protocol,
        ...(destinationPort === '' ? {} : { destination_port: Number(destinationPort) }),
      }),
  });

  const canSubmit = deviceId !== '' && filterName !== '' && destinationIp !== '';

  return (
    <div className="stack-form">
      <div className="form-grid form-grid--two">
        <SelectField
          label="Device"
          value={deviceId}
          onChange={(event) => setDeviceId(event.target.value)}
        >
          <option value="">Select a device</option>
          {(devices.data ?? []).map((device) => (
            <option key={device.id} value={device.id}>
              {device.name}
            </option>
          ))}
        </SelectField>
        <InputField
          label="Filter (ACL) name"
          placeholder="BLOCK_GUEST"
          value={filterName}
          onChange={(event) => setFilterName(event.target.value)}
        />
      </div>
      <div className="form-grid form-grid--two">
        <InputField
          label="Destination IPv4"
          placeholder="198.51.100.10"
          value={destinationIp}
          onChange={(event) => setDestinationIp(event.target.value)}
        />
        <SelectField
          label="Protocol"
          value={protocol}
          onChange={(event) => setProtocol(event.target.value as 'tcp' | 'udp' | 'icmp')}
        >
          <option value="tcp">TCP</option>
          <option value="udp">UDP</option>
          <option value="icmp">ICMP</option>
        </SelectField>
      </div>
      <InputField
        label="Destination port (optional)"
        type="number"
        inputMode="numeric"
        min={1}
        max={65_535}
        value={destinationPort}
        onChange={(event) => setDestinationPort(event.target.value)}
      />
      <Button
        variant="primary"
        onClick={() => check.mutate()}
        busy={check.isPending}
        disabled={!canSubmit}
      >
        Check filter
      </Button>
      {check.isError ? (
        <div className="connection-test__result connection-test__result--error" role="alert">
          <span>
            {check.error instanceof ApiError ? check.error.message : 'The check failed.'}
          </span>
        </div>
      ) : null}
      {check.data === undefined ? null : (
        <div
          className={`connection-test__result ${
            check.data.permitted
              ? 'connection-test__result--success'
              : 'connection-test__result--error'
          }`}
          role="status"
        >
          <strong>{check.data.permitted ? 'Permitted' : 'Denied'}</strong>
          {check.data.matched_line === null ? null : (
            <span className="mono">{check.data.matched_line}</span>
          )}
        </div>
      )}
    </div>
  );
}
