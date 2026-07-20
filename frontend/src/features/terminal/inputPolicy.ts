export type LineEnding = 'raw' | 'cr' | 'lf' | 'crlf';

export interface TerminalInputPolicy {
  lineEnding: LineEnding;
  localEcho: boolean;
  confirmMultiline: boolean;
}

export interface PreparedTerminalInput {
  data: string;
  lineCount: number;
  requiresConfirmation: boolean;
}

const outputNewline = { cr: '\r', lf: '\n', crlf: '\r\n' } as const;

export function prepareTerminalInput(
  input: string,
  policy: TerminalInputPolicy,
): PreparedTerminalInput {
  if (policy.lineEnding === 'raw') {
    return { data: input, lineCount: 1, requiresConfirmation: false };
  }
  const normalized = input.replaceAll('\r\n', '\n').replaceAll('\r', '\n');
  const lines = normalized.split('\n');
  if (lines.length > 1 && lines.at(-1) === '') lines.pop();
  const lineCount = Math.max(1, lines.length);
  return {
    data: normalized.replaceAll('\n', outputNewline[policy.lineEnding]),
    lineCount,
    requiresConfirmation: policy.confirmMultiline && lineCount > 1,
  };
}

export function parseBaudRate(value: string): number | null {
  const baudRate = Number(value);
  return Number.isInteger(baudRate) && baudRate > 0 && baudRate <= 0xffff_ffff
    ? baudRate
    : null;
}
