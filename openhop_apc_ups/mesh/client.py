"""Async MeshCore Companion TCP client for openHop frame protocol."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .constants import (
    CMD_APP_START,
    CMD_DEVICE_QUERY,
    CMD_SEND_CHANNEL_TXT_MSG,
    CMD_SEND_TXT_MSG,
    CMD_SYNC_NEXT_MESSAGE,
    FRAME_INBOUND_PREFIX,
    FRAME_OUTBOUND_PREFIX,
    PUSH_CODE_MSG_WAITING,
    RESP_CODE_CHANNEL_MSG_RECV,
    RESP_CODE_CHANNEL_MSG_RECV_V3,
    RESP_CODE_CONTACT_MSG_RECV,
    RESP_CODE_CONTACT_MSG_RECV_V3,
    RESP_CODE_CURR_TIME,
    RESP_CODE_ERR,
    RESP_CODE_NO_MORE_MESSAGES,
    RESP_CODE_OK,
    RESP_CODE_SENT,
    TXT_TYPE_PLAIN,
)

logger = logging.getLogger(__name__)


class MeshCoreProtocolError(RuntimeError):
    """Raised when frame protocol invariants are violated."""


@dataclass(frozen=True)
class IncomingMessage:
    sender_prefix: bytes
    text: str
    timestamp: int
    channel_idx: int | None
    is_direct: bool


class MeshCoreClient:
    """Connects to openHop Repeater Companion Frame Server via TCP."""

    def __init__(self, *, host: str = "127.0.0.1", port: int = 5050) -> None:
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = asyncio.Event()
        self._stop_requested = asyncio.Event()
        self._command_lock = asyncio.Lock()
        self._response_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._message_waiting = asyncio.Event()
        self._reader_task: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    async def close(self) -> None:
        self._stop_requested.set()
        self._connected.clear()
        self._message_waiting.set()

        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None

        writer = self._writer
        self._writer = None
        self._reader = None
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def run(
        self,
        on_message: Callable[[IncomingMessage], Awaitable[None]],
        stop_event: asyncio.Event,
    ) -> None:
        backoff = [5, 10, 20, 30, 60]
        index = 0
        logged_not_found = False

        while not stop_event.is_set() and not self._stop_requested.is_set():
            try:
                await self._connect_and_process(on_message, stop_event)
                index = 0
                logged_not_found = False
            except asyncio.CancelledError:
                break
            except (ConnectionRefusedError, OSError) as exc:
                self._connected.clear()
                if not logged_not_found:
                    logger.info(
                        "MeshCore Companion Frame Server not detected at %s:%s (%s). "
                        "Radio alerts will automatically activate when a Companion identity is running.",
                        self._host,
                        self._port,
                        exc,
                    )
                    logged_not_found = True
                else:
                    logger.debug("MeshCore connection retry failed: %s", exc)
            except Exception as exc:
                self._connected.clear()
                logger.warning("MeshCore connection lost: %s", exc)

            if stop_event.is_set() or self._stop_requested.is_set():
                break

            delay = backoff[min(index, len(backoff) - 1)]
            index += 1
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def send_channel_text(self, channel_idx: int, text: str) -> bool:
        """Broadcast a text message on a MeshCore channel (e.g. channel 0)."""
        if not self.connected:
            logger.debug("Cannot send channel text: MeshCore disconnected")
            return False

        msg_bytes = text.encode("utf-8", errors="replace")
        timestamp = int(time.time())
        # CMD_SEND_CHANNEL_TXT_MSG layout:
        # cmd(1) + txt_type(1) + channel_idx(1) + timestamp(4 bytes LE) + text
        payload = (
            bytes([CMD_SEND_CHANNEL_TXT_MSG, TXT_TYPE_PLAIN, channel_idx])
            + struct.pack("<I", timestamp)
            + msg_bytes
        )

        try:
            async with self._command_lock:
                frame = await self._send_command_expect(
                    payload,
                    expected_codes={RESP_CODE_OK, RESP_CODE_ERR},
                    command_label="send_channel_text",
                )
            if frame[0] == RESP_CODE_OK:
                logger.info("MeshCore broadcast to channel %s: %s", channel_idx, text)
                return True
            logger.warning("MeshCore broadcast rejected with code=%s", frame[0])
            return False
        except Exception as exc:
            logger.warning("Failed to broadcast on MeshCore channel %s: %s", channel_idx, exc)
            return False

    async def send_direct_text(self, recipient_prefix: bytes, text: str) -> bool:
        """Send a direct message reply to a contact."""
        if not self.connected:
            return False
        if len(recipient_prefix) < 6:
            raise ValueError("recipient_prefix must contain at least 6 bytes")

        payload = (
            bytes([CMD_SEND_TXT_MSG, TXT_TYPE_PLAIN, 1])
            + struct.pack("<I", 0)
            + recipient_prefix[:6]
            + text.encode("utf-8", errors="replace")
        )

        try:
            async with self._command_lock:
                frame = await self._send_command_expect(
                    payload,
                    expected_codes={RESP_CODE_SENT, RESP_CODE_ERR},
                    command_label="send_direct_text",
                )
            return frame[0] == RESP_CODE_SENT
        except Exception as exc:
            logger.warning("Failed to send direct text: %s", exc)
            return False

    async def _connect_and_process(
        self,
        on_message: Callable[[IncomingMessage], Awaitable[None]],
        stop_event: asyncio.Event,
    ) -> None:
        ports_to_try = [self._port]
        alt_port = 5000 if self._port == 5050 else (5050 if self._port == 5000 else None)
        if alt_port is not None:
            ports_to_try.append(alt_port)

        reader, writer = None, None
        last_exc = None
        for p in ports_to_try:
            try:
                reader, writer = await asyncio.open_connection(self._host, p)
                self._port = p
                break
            except (ConnectionRefusedError, OSError) as exc:
                last_exc = exc

        if reader is None or writer is None:
            raise last_exc or ConnectionError(f"Could not connect to MeshCore on {self._host}:{ports_to_try}")

        self._reader = reader
        self._writer = writer
        self._response_queue = asyncio.Queue()
        self._message_waiting.clear()

        self._reader_task = asyncio.create_task(self._reader_loop(), name="meshcore-reader")
        await self._startup_handshake()

        self._connected.set()
        logger.info("Connected to MeshCore Companion Frame Server at %s:%s", self._host, self._port)

        try:
            while not stop_event.is_set() and not self._stop_requested.is_set():
                try:
                    await asyncio.wait_for(self._message_waiting.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    self._message_waiting.set()

                self._message_waiting.clear()
                await self._drain_messages(on_message)

                if self._reader_task.done():
                    exc = self._reader_task.exception()
                    if exc is not None:
                        raise exc
                    raise ConnectionError("MeshCore reader loop terminated")
        finally:
            await self._teardown_connection()

    async def _startup_handshake(self) -> None:
        async with self._command_lock:
            await self._send_command_expect(
                bytes([CMD_APP_START]) + b"\x00" * 7,
                expected_codes=None,
                command_label="app_start",
            )
            await self._send_command_expect(
                bytes([CMD_DEVICE_QUERY, 3]),
                expected_codes=None,
                command_label="device_query",
            )

    async def _drain_messages(
        self,
        on_message: Callable[[IncomingMessage], Awaitable[None]],
    ) -> None:
        while True:
            async with self._command_lock:
                frame = await self._send_command_expect(
                    bytes([CMD_SYNC_NEXT_MESSAGE]),
                    expected_codes={
                        RESP_CODE_NO_MORE_MESSAGES,
                        RESP_CODE_CHANNEL_MSG_RECV,
                        RESP_CODE_CHANNEL_MSG_RECV_V3,
                        RESP_CODE_CONTACT_MSG_RECV,
                        RESP_CODE_CONTACT_MSG_RECV_V3,
                    },
                    command_label="sync_next_message",
                )

            code = frame[0]
            if code == RESP_CODE_NO_MORE_MESSAGES:
                return

            msg: IncomingMessage | None = None
            if code in {RESP_CODE_CHANNEL_MSG_RECV, RESP_CODE_CHANNEL_MSG_RECV_V3}:
                msg = self._parse_channel_message(frame)
            elif code in {RESP_CODE_CONTACT_MSG_RECV, RESP_CODE_CONTACT_MSG_RECV_V3}:
                msg = self._parse_contact_message(frame)

            if msg is not None:
                try:
                    await on_message(msg)
                except Exception as exc:
                    logger.exception("Error in MeshCore on_message handler: %s", exc)

    def _parse_channel_message(self, frame: bytes) -> IncomingMessage | None:
        # Channel messages: channel_idx is typically byte 1, sender prefix byte 4..10 or 2..8
        if len(frame) < 14:
            return None
        channel_idx = frame[1]
        sender_prefix = frame[2:8]
        timestamp = struct.unpack("<I", frame[8:12])[0]
        text = frame[12:].decode("utf-8", errors="replace").rstrip("\x00")
        return IncomingMessage(
            sender_prefix=sender_prefix,
            text=text,
            timestamp=timestamp,
            channel_idx=channel_idx,
            is_direct=False,
        )

    def _parse_contact_message(self, frame: bytes) -> IncomingMessage | None:
        if len(frame) < 13:
            return None
        sender_prefix = frame[1:7]
        timestamp = struct.unpack("<I", frame[9:13])[0]
        text = frame[13:].decode("utf-8", errors="replace").rstrip("\x00")
        return IncomingMessage(
            sender_prefix=sender_prefix,
            text=text,
            timestamp=timestamp,
            channel_idx=None,
            is_direct=True,
        )

    async def _reader_loop(self) -> None:
        reader = self._reader
        if reader is None:
            raise ConnectionError("Reader not initialized")

        while True:
            prefix = await reader.readexactly(1)
            if prefix[0] != FRAME_OUTBOUND_PREFIX:
                raise MeshCoreProtocolError(f"Unexpected frame prefix: {prefix[0]:#x}")

            length_bytes = await reader.readexactly(2)
            length = struct.unpack("<H", length_bytes)[0]
            payload = await reader.readexactly(length)

            if not payload:
                continue

            code = payload[0]
            if code >= 0x80:
                if code == PUSH_CODE_MSG_WAITING:
                    self._message_waiting.set()
                continue

            await self._response_queue.put(payload)

    async def _send_command(self, payload: bytes) -> None:
        writer = self._writer
        if writer is None:
            raise ConnectionError("MeshCore socket not connected")
        frame = bytes([FRAME_INBOUND_PREFIX]) + struct.pack("<H", len(payload)) + payload
        writer.write(frame)
        await writer.drain()

    async def _send_command_expect(
        self,
        payload: bytes,
        *,
        expected_codes: set[int] | None,
        command_label: str,
    ) -> bytes:
        await self._send_command(payload)
        while True:
            frame = await asyncio.wait_for(self._response_queue.get(), timeout=15.0)
            if not frame:
                continue
            if frame[0] == RESP_CODE_CURR_TIME:
                continue
            if expected_codes is None or frame[0] in expected_codes:
                return frame

    async def _teardown_connection(self) -> None:
        self._connected.clear()
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._reader = None
