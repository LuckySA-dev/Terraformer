import {
  parseBaudRate,
  prepareTerminalInput,
} from '../src/features/terminal/inputPolicy';

describe('terminal input policy', () => {
  it.each([
    ['show version\r\nshow clock\r\n', 'cr' as const, 'show version\rshow clock\r'],
    ['show version\rshow clock', 'lf' as const, 'show version\nshow clock'],
    ['show version\nshow clock', 'crlf' as const, 'show version\r\nshow clock'],
  ])('normalizes mixed newlines before applying %s output', (input, lineEnding, expected) => {
    expect(prepareTerminalInput(input, { lineEnding, localEcho: false, confirmMultiline: true }))
      .toEqual({ data: expected, lineCount: 2, requiresConfirmation: true });
  });

  it('ignores one final empty segment but counts an intentional blank line', () => {
    expect(prepareTerminalInput('show version\n', {
      lineEnding: 'lf', localEcho: false, confirmMultiline: true,
    }).lineCount).toBe(1);
    expect(prepareTerminalInput('show version\n\n', {
      lineEnding: 'lf', localEcho: false, confirmMultiline: true,
    }).lineCount).toBe(2);
  });

  it('preserves raw SSH input', () => {
    expect(prepareTerminalInput('\r', {
      lineEnding: 'raw', localEcho: false, confirmMultiline: false,
    })).toEqual({ data: '\r', lineCount: 1, requiresConfirmation: false });
  });

  it.each([
    ['9600', 9600],
    ['115200', 115200],
    ['4294967295', 4294967295],
  ])('accepts unsigned-long baud %s', (value, expected) => {
    expect(parseBaudRate(value)).toBe(expected);
  });

  it.each(['', '0', '-1', '1.5', '4294967296', 'not-a-number'])('rejects invalid baud %s', (value) => {
      expect(parseBaudRate(value)).toBeNull();
  });
});
