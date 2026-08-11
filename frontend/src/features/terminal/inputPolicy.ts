export type LineEnding = 'raw' | 'cr' | 'lf' | 'crlf';

export interface TerminalInputPolicy {
  lineEnding: LineEnding;
  localEcho: boolean;
  confirmMultiline: boolean;
}

export interface PreparedTerminalInput {
  data: string;
  lineCount: number;
  characterCount: number;
  byteCount: number;
  containsUnsafeControl: boolean;
  requiresConfirmation: boolean;
}

const outputNewline = { cr: '\r', lf: '\n', crlf: '\r\n' } as const;

// A control byte alone only means "not printable text" for a genuine single
// keystroke (Backspace, a Ctrl+letter chord, or an escape-prefixed arrow/function
// key). The longest standard xterm CSI encoding — a modified function key like
// Shift+F5 (`\x1b[15;2~`) — is 8 characters. A short input that's entirely a
// control/escape sequence is indistinguishable from a real keystroke, since
// there's no surrounding text for a byte to hide in; the danger this guards
// against is a control byte embedded inside longer pasted text, which this
// length gate still catches.
const MAX_SINGLE_KEYSTROKE_CHARACTERS = 8;

export function prepareTerminalInput(
  input: string,
  policy: TerminalInputPolicy,
): PreparedTerminalInput {
  const normalized = input.replaceAll('\r\n', '\n').replaceAll('\r', '\n');
  const lines = normalized.split('\n');
  if (lines.length > 1 && lines.at(-1) === '') lines.pop();
  const lineCount = Math.max(1, lines.length);
  const characterCount = Array.from(input).length;
  const data = policy.lineEnding === 'raw'
    ? input
    : normalized.replaceAll('\n', outputNewline[policy.lineEnding]);
  const byteCount = new TextEncoder().encode(data).byteLength;
  const containsUnsafeControl = Array.from(input).some((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return (codePoint < 0x20 && codePoint !== 0x09 && codePoint !== 0x0a && codePoint !== 0x0d)
      || (codePoint >= 0x7f && codePoint <= 0x9f);
  });
  return {
    data,
    lineCount,
    characterCount,
    byteCount,
    containsUnsafeControl,
    requiresConfirmation: policy.confirmMultiline
      && (
        lineCount > 1
        || characterCount > 1_024
        || (containsUnsafeControl && characterCount > MAX_SINGLE_KEYSTROKE_CHARACTERS)
      ),
  };
}

export function parseBaudRate(value: string): number | null {
  const baudRate = Number(value);
  return Number.isInteger(baudRate) && baudRate > 0 && baudRate <= 0xffff_ffff
    ? baudRate
    : null;
}
