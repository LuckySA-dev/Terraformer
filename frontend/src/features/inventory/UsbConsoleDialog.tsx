import { useState } from 'react';
import { AppState } from '../../components/ui/AppState';
import { InputField, SelectField } from '../../components/ui/FormField';
import { TerminalSession } from '../terminal/TerminalSession';
import { parseBaudRate } from '../terminal/inputPolicy';
import { TerminalTransportError } from '../terminal/transport';
import {
  getBrowserSerialApi,
  getUsbSerialCapability,
  UsbSerialTransport,
  type SerialApi,
  type UsbSerialCapability,
} from '../terminal/UsbSerialTransport';

interface UsbConsoleDialogProps {
  serialApi?: SerialApi;
  capability?: UsbSerialCapability;
}

interface UsbConsoleSettings {
  baudSelection: '9600' | '19200' | '38400' | '57600' | '115200' | 'custom';
  customBaud: string;
  lineEnding: 'cr' | 'lf' | 'crlf';
  localEcho: boolean;
}

const DEFAULT_USB_SETTINGS: UsbConsoleSettings = {
  baudSelection: '9600',
  customBaud: '',
  lineEnding: 'cr',
  localEcho: false,
};

const capabilityCopy = {
  browser_unsupported: {
    title: 'Web Serial is unavailable',
    message: 'Chrome or Edge is required',
  },
  secure_context_required: {
    title: 'Secure context required',
    message: 'A secure context is required',
  },
  serial_policy_blocked: {
    title: 'Serial access blocked',
    message: 'Serial access is blocked by policy',
  },
} as const;

export function UsbConsoleDialog({ serialApi, capability }: UsbConsoleDialogProps) {
  const [settings, setSettings] = useState(DEFAULT_USB_SETTINGS);
  const activeSerialApi = serialApi ?? getBrowserSerialApi();
  const activeCapability = capability ?? getUsbSerialCapability();

  if (!activeCapability.available) {
    const copy = capabilityCopy[activeCapability.code];
    return <AppState kind="unsupported" title={copy.title} message={copy.message} />;
  }

  const baudRate = parseBaudRate(
    settings.baudSelection === 'custom' ? settings.customBaud : settings.baudSelection,
  );
  const settingsForm = (
    <div className="usb-console-settings">
      <SelectField
        label="Baud rate"
        value={settings.baudSelection}
        onChange={(event) => setSettings((current) => ({
          ...current,
          baudSelection: event.target.value as UsbConsoleSettings['baudSelection'],
        }))}
      >
        {[9600, 19200, 38400, 57600, 115200].map((value) => (
          <option key={value} value={String(value)}>{value}</option>
        ))}
        <option value="custom">Custom</option>
      </SelectField>
      {settings.baudSelection === 'custom' ? (
        <InputField
          label="Custom baud rate"
          type="number"
          min={1}
          max={0xffff_ffff}
          value={settings.customBaud}
          onChange={(event) => setSettings((current) => ({
            ...current,
            customBaud: event.target.value,
          }))}
          error={baudRate === null ? 'Enter a whole baud rate from 1 to 4294967295.' : undefined}
        />
      ) : null}
      <SelectField
        label="Line ending"
        value={settings.lineEnding}
        onChange={(event) => setSettings((current) => ({
          ...current,
          lineEnding: event.target.value as UsbConsoleSettings['lineEnding'],
        }))}
      >
        <option value="cr">CR</option>
        <option value="lf">LF</option>
        <option value="crlf">CRLF</option>
      </SelectField>
      <label className="usb-console-echo">
        <input
          type="checkbox"
          checked={settings.localEcho}
          onChange={(event) => setSettings((current) => ({
            ...current,
            localEcho: event.target.checked,
          }))}
        />
        Local echo
      </label>
      <p>8 data bits · 1 stop bit · no parity · no flow control</p>
    </div>
  );

  return (
    <TerminalSession
      createTransport={() => {
        if (activeSerialApi === undefined || baudRate === null) {
          throw new TerminalTransportError(
            'invalid_serial_settings',
            'Serial settings are invalid',
          );
        }
        return new UsbSerialTransport(activeSerialApi, {
          baudRate,
          dataBits: 8,
          stopBits: 1,
          parity: 'none',
          flowControl: 'none',
        });
      }}
      warningTitle="USB Direct Mode — commands can change hardware"
      warningBody="Commands are sent exactly as entered and can modify, restart, or erase the attached device. There is no preview, rollback, recording, or automatic recovery."
      acknowledgementLabel="I am authorized to access this attached device and understand the risk"
      openLabel="Open USB Direct Mode"
      requireAuthorization
      inputPolicy={{
        lineEnding: settings.lineEnding,
        localEcho: settings.localEcho,
        confirmMultiline: true,
      }}
      ariaLabel="Manual USB console"
      note="Serial content stays in this browser tab and is destroyed when the session closes."
      openDisabled={baudRate === null || activeSerialApi === undefined}
      configuration={settingsForm}
      onReset={() => setSettings(DEFAULT_USB_SETTINGS)}
    />
  );
}
