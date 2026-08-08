from __future__ import annotations

import asyncio

import pytest

from app.drivers.telnet import TelnetTerminalSession

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
ECHO, SGA, TERMINAL_TYPE, NAWS = 1, 3, 24, 31


class FakeReader:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, _size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class FakeWriter:
    def __init__(self) -> None:
        self.written = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.written.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def _session(chunks: list[bytes]) -> tuple[TelnetTerminalSession, FakeWriter]:
    writer = FakeWriter()
    session = TelnetTerminalSession(
        FakeReader(chunks),  # type: ignore[arg-type]
        writer,  # type: ignore[arg-type]
        close_timeout_seconds=1.0,
    )
    return session, writer


def test_plain_output_passes_through_unchanged() -> None:
    session, _ = _session([b"edge-rtr-01> "])
    assert asyncio.run(session.read(1024)) == "edge-rtr-01> "


def test_echo_and_suppress_go_ahead_are_accepted() -> None:
    """Without these two a console does not behave like a PTY."""
    session, writer = _session([bytes([IAC, WILL, ECHO, IAC, WILL, SGA]) + b"Router>"])

    assert asyncio.run(session.read(1024)) == "Router>"
    assert bytes(writer.written) == bytes([IAC, DO, ECHO, IAC, DO, SGA])


def test_every_other_option_is_refused() -> None:
    session, writer = _session([bytes([IAC, WILL, TERMINAL_TYPE, IAC, DO, NAWS]) + b"x"])

    assert asyncio.run(session.read(1024)) == "x"
    assert bytes(writer.written) == bytes([IAC, DONT, TERMINAL_TYPE, IAC, WONT, NAWS])


def test_negotiation_split_across_reads_is_not_corrupted() -> None:
    """TCP may split an IAC sequence; the tail must be carried over."""
    session, writer = _session([b"ab" + bytes([IAC, WILL]), bytes([ECHO]) + b"cd"])

    assert asyncio.run(session.read(1024)) == "ab"
    assert asyncio.run(session.read(1024)) == "cd"
    assert bytes(writer.written) == bytes([IAC, DO, ECHO])


def test_subnegotiation_is_skipped_and_never_reaches_the_terminal() -> None:
    payload = bytes([IAC, SB, TERMINAL_TYPE, 0, 65, 66, IAC, SE]) + b"prompt#"
    session, _ = _session([payload])
    assert asyncio.run(session.read(1024)) == "prompt#"


def test_escaped_literal_255_is_delivered_once() -> None:
    """IAC IAC is one literal 0xFF byte, which is not valid UTF-8 on its own."""
    session, _ = _session([bytes([IAC, IAC]) + b"!"])
    assert asyncio.run(session.read(1024)) == "�!"


def test_negotiation_only_read_waits_for_real_output() -> None:
    """Returning "" would be read as end-of-session and close the terminal."""
    session, _ = _session([bytes([IAC, WILL, ECHO]), b"ready"])
    assert asyncio.run(session.read(1024)) == "ready"


def test_end_of_stream_returns_empty_string() -> None:
    session, _ = _session([b""])
    assert asyncio.run(session.read(1024)) == ""


def test_user_input_is_sent_as_utf8_and_never_produces_a_stray_iac() -> None:
    """UTF-8 never emits 0xFF, so no input can be misread as a command byte."""
    session, writer = _session([])
    asyncio.run(session.write("a\xffb"))
    assert bytes(writer.written) == "a\xffb".encode()
    assert 0xFF not in writer.written


def test_close_is_idempotent() -> None:
    session, writer = _session([])
    asyncio.run(session.close())
    asyncio.run(session.close())
    assert writer.closed


def test_resize_is_a_no_op_without_naws() -> None:
    session, writer = _session([])
    session.resize(200, 50)
    assert bytes(writer.written) == b""


@pytest.mark.parametrize("partial", [bytes([IAC]), bytes([IAC, SB, TERMINAL_TYPE])])
def test_incomplete_trailing_sequences_do_not_raise(partial: bytes) -> None:
    session, _ = _session([b"hi" + partial, b"", b""])
    assert asyncio.run(session.read(1024)) == "hi"
