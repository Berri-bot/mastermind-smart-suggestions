import asyncio
import json
import logging
from typing import Optional, Dict, Callable

logger = logging.getLogger(__name__)

class SubprocessManager:
    def __init__(self, command: list):
        self.command = command
        self.process: Optional[asyncio.subprocess.Process] = None
        self._buffer = bytearray()
        self._responses: Dict[int, asyncio.Future] = {}
        self._notification_callback: Optional[Callable] = None
        self._running = False

    def set_notification_callback(self, callback: Callable):
        self._notification_callback = callback

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        self._running = True
        asyncio.create_task(self._read_stdout())
        asyncio.create_task(self._read_stderr())
        logger.info(f"Subprocess started with PID {self.process.pid}")

    async def send(self, message: str):
        if not self._running or not self.process.stdin:
            raise RuntimeError("Subprocess not running")
        content = message.encode("utf-8")
        headers = f"Content-Length: {len(content)}\r\n\r\n".encode("utf-8")
        self.process.stdin.write(headers + content)
        await self.process.stdin.drain()
        logger.debug(f"Sent: {message[:200]}...")

    async def receive(self, msg_id: int, timeout: float = 10.0) -> Optional[str]:
        future = asyncio.get_event_loop().create_future()
        self._responses[msg_id] = future
        try:
            response = await asyncio.wait_for(future, timeout)
            return json.dumps(response)
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for msg_id {msg_id}")
            return None
        finally:
            self._responses.pop(msg_id, None)

    async def _read_stdout(self):
        while self._running and not self.process.stdout.at_eof():
            line = await self.process.stdout.readline()
            if not line:
                break
            message_str = line.decode("utf-8").strip()
            if "Content-Length" in message_str:
                continue  # Skip header lines
            try:
                message = json.loads(message_str)
                msg_id = message.get("id")
                if msg_id in self._responses:
                    self._responses[msg_id].set_result(message)
                elif self._notification_callback and "method" in message:
                    await self._notification_callback(message)
            except json.JSONDecodeError:
                logger.debug(f"Ignoring non-JSON output: {message_str}")

    async def _read_stderr(self):
        while self._running and not self.process.stderr.at_eof():
            line = await self.process.stderr.readline()
            if line:
                logger.warning(f"JDT LS stderr: {line.decode('utf-8').strip()}")

    async def stop(self):
        if self._running:
            self._running = False
            self.process.terminate()
            await self.process.wait()
            logger.info("Subprocess stopped")