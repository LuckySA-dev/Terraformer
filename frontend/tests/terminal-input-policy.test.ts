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
      .toEqual({
        data: expected,
        lineCount: 2,
        characterCount: Array.from(input).length,
        byteCount: new TextEncoder().encode(expected).byteLength,
        containsUnsafeControl: false,
        requiresConfirmation: true,
      });
  });

  it('ignores one final empty segment but counts an intentional blank line', () => {
    expect(prepareTerminalInput('show version\n', {
      lineEnding: 'lf', localEcho: false, confirmMultiline: true,
    }).lineCount).toBe(1);
    expect(prepareTerminalInput('show version\n\n', {
      lineEnding: 'lf', localEcho: false, confirmMultiline: true,
    }).lineCount).toBe(2);
  });

  it('detects normalized SSH lines while preserving raw bytes', () => {
    const input = 'show version\r\nshow clock\rreload';
    expect(prepareTerminalInput(input, {
      lineEnding: 'raw', localEcho: false, confirmMultiline: true,
    })).toEqual({
      data: input,
      lineCount: 3,
      characterCount: 31,
      byteCount: 31,
      containsUnsafeControl: false,
      requiresConfirmation: true,
    });
  });

  it('requires confirmation above 1,024 characters', () => {
    expect(prepareTerminalInput('x'.repeat(1_024), {
      lineEnding: 'raw', localEcho: false, confirmMultiline: true,
    }).requiresConfirmation).toBe(false);
    expect(prepareTerminalInput('x'.repeat(1_025), {
      lineEnding: 'raw', localEcho: false, confirmMultiline: true,
    }).requiresConfirmation).toBe(true);
  });

  it.each(['\0', '\u001b', '\u007f', '\u0085'])('flags unsafe control %j', (control) => {
    const prepared = prepareTerminalInput(`show${control}version`, {
      lineEnding: 'raw', localEcho: false, confirmMultiline: true,
    });
    expect(prepared.containsUnsafeControl).toBe(true);
    expect(prepared.requiresConfirmation).toBe(true);
  });

  it('allows tab, carriage return, and line feed controls', () => {
    expect(prepareTerminalInput('\t\r\n', {
      lineEnding: 'raw', localEcho: false, confirmMultiline: true,
    }).containsUnsafeControl).toBe(false);
  });

  it('counts Unicode characters and UTF-8 bytes separately', () => {
    expect(prepareTerminalInput('🙂', {
      lineEnding: 'raw', localEcho: false, confirmMultiline: true,
    })).toMatchObject({ characterCount: 1, byteCount: 4 });
  });

  it('counts bytes after USB line-ending expansion', () => {
    const input = `${'x'.repeat(2_047)}\n${'y'.repeat(2_048)}`;
    expect(new TextEncoder().encode(input)).toHaveLength(4_096);
    expect(prepareTerminalInput(input, {
      lineEnding: 'crlf', localEcho: false, confirmMultiline: true,
    })).toMatchObject({ byteCount: 4_097, requiresConfirmation: true });
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
