"""Minimal Telnet client for lab console access.

GNS3 and EVE-NG expose node consoles over Telnet, so a virtual lab cannot be
driven through the SSH-only terminal path.

Deliberately small: this speaks just enough of RFC 854 to keep a Cisco-style
console usable. It is not a general Telnet library.

`telnetlib` is not used — it was deprecated in Python 3.11 and removed in 3.13,
and this project supports up to Python 3.13.

Security position: Telnet is cleartext and carries no host identity, so none of
the SSH host-key pinning applies. Credentials are never sent automatically; the
operator types them into the session, exactly as they would on a physical
console cable. Callers are responsible for enforcing that the device is a lab
device and that the server-side kill switch is on.
"""

from __future__ import annotations

import asyncio
import codecs

# RFC 854 commands.
_IAC = 255
_DONT = 254
_DO = 253
_WONT = 252
_WILL = 251
_SB = 250
_SE = 240

# RFC 857 / RFC 858. Accepting these two is what makes a console behave like a
# PTY: the device echoes typed characters and does not wait for a go-ahead.
_ECHO = 1
_SUPPRESS_GO_AHEAD = 3

_ACCEPTED_SERVER_OPTIONS = frozenset({_ECHO, _SUPPRESS_GO_AHEAD})


class TelnetTerminalSession:
    """A Telnet console shaped like the SSH TerminalSession protocol."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        close_timeout_seconds: float,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._close_timeout_seconds = close_timeout_seconds
        self._closed = False
        # Device output is not guaranteed to split on character boundaries, so
        # decoding is incremental and never raises on a partial sequence.
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        # Holds an IAC sequence that arrived split across two reads.
        self._pending = b""

    async def read(self, size: int) -> str:
        while True:
            chunk = await self._reader.read(size)
            if not chunk:
                return ""
            # Reset before consuming: _consume repopulates _pending when the
            # chunk ends mid-sequence, and clearing afterwards would drop it.
            carried, self._pending = self._pending, b""
            payload, replies = self._consume(carried + chunk)
            if replies:
                self._writer.write(replies)
                await self._writer.drain()
            if payload:
                return self._decoder.decode(payload)
            # The read contained only negotiation; wait for real output rather
            # than returning "", which the relay treats as end-of-session.

    def _consume(self, data: bytes) -> tuple[bytes, bytes]:
        """Split raw bytes into terminal output and negotiation replies."""
        payload = bytearray()
        replies = bytearray()
        index = 0
        length = len(data)
        while index < length:
            byte = data[index]
            if byte != _IAC:
                payload.append(byte)
                index += 1
                continue
            if index + 1 >= length:
                self._pending = data[index:]  # Incomplete; resume next read.
                break
            command = data[index + 1]
            if command == _IAC:  # Escaped literal 0xFF.
                payload.append(_IAC)
                index += 2
                continue
            if command == _SB:
                end = data.find(bytes([_IAC, _SE]), index + 2)
                if end == -1:
                    self._pending = data[index:]
                    break
                # Subnegotiation is answered by refusing the option outright,
                # which is handled by the WILL/DO exchange below.
                index = end + 2
                continue
            if command in (_WILL, _WONT, _DO, _DONT):
                if index + 2 >= length:
                    self._pending = data[index:]
                    break
                replies.extend(self._negotiate(command, data[index + 2]))
                index += 3
                continue
            index += 2  # Any other two-byte command is ignored.
        return bytes(payload), bytes(replies)

    @staticmethod
    def _negotiate(command: int, option: int) -> bytes:
        """Accept only echo and suppress-go-ahead; refuse everything else."""
        if command == _WILL:
            allow = option in _ACCEPTED_SERVER_OPTIONS
            return bytes([_IAC, _DO if allow else _DONT, option])
        if command == _DO:
            # This client offers no options of its own, including NAWS, so
            # resize is a no-op rather than a protocol error.
            return bytes([_IAC, _WONT, option])
        return b""  # WONT/DONT need no reply.

    async def write(self, data: str) -> None:
        # No IAC escaping is needed: UTF-8 never encodes a 0xFF byte, so
        # operator input cannot be misread as the start of a command.
        self._writer.write(data.encode("utf-8"))
        await self._writer.drain()

    def resize(self, columns: int, rows: int) -> None:
        # ponytail: NAWS not negotiated, so the device keeps its default console
        # geometry. Add WILL NAWS plus the subnegotiation if wrapping on wide
        # terminals becomes a problem in practice.
        del columns, rows

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._writer.close()
            await asyncio.wait_for(
                self._writer.wait_closed(), timeout=self._close_timeout_seconds
            )
        except (Exception, asyncio.CancelledError):  # noqa: S110
            pass  # Cleanup errors must not expose raw terminal or transport details.


async def open_telnet_session(
    host: str,
    port: int,
    *,
    connect_timeout_seconds: float,
    close_timeout_seconds: float,
) -> TelnetTerminalSession:
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port), timeout=connect_timeout_seconds
    )
    return TelnetTerminalSession(reader, writer, close_timeout_seconds=close_timeout_seconds)
