import asyncio
import json
import logging
import re
from typing import Optional, Dict, Any, Callable

logger = logging.getLogger(__name__)

class SubprocessManager:
    def __init__(self, command: list):
        self.command = command
        self.process: Optional[asyncio.subprocess.Process] = None
        self._buffer = bytearray()
        self._content_length = -1
        self._running = False
        self._response_map: Dict[Any, asyncio.Future] = {}
        self._notification_callback: Optional[Callable] = None

    def set_notification_callback(self, callback: Callable):
        self._notification_callback = callback

    async def start(self):
        try:
            logger.info(f"Starting subprocess with command: {' '.join(self.command)}")
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            self._running = True
            logger.info(f"Subprocess started with PID {self.process.pid}")
            asyncio.create_task(self._read_stdout())
            asyncio.create_task(self._read_stderr())
        except Exception as e:
            logger.error(f"Failed to start subprocess: {str(e)}", exc_info=True)
            raise

    async def send(self, message: str):
        if not self._running or not self.process or not self.process.stdin:
            logger.error("Cannot send message: Subprocess not running")
            raise RuntimeError("Subprocess not running")
        content = message.encode('utf-8')
        headers = f"Content-Length: {len(content)}\r\n\r\n".encode('utf-8')
        try:
            self.process.stdin.write(headers + content)
            await self.process.stdin.drain()
            logger.debug(f"Sent message to JDT LS: {message[:200]}...")
        except Exception as e:
            logger.error(f"Failed to send message: {str(e)}", exc_info=True)
            raise

    async def receive(self, msg_id: Any, timeout: float = 10.0) -> Optional[str]:
        if not self._running or msg_id is None:
            logger.warning(f"Cannot receive for ID {msg_id}: Subprocess not running or invalid ID")
            return None
        future = asyncio.get_event_loop().create_future()
        self._response_map[msg_id] = future
        try:
            response = await asyncio.wait_for(future, timeout)
            logger.debug(f"Received response for ID {msg_id}: {json.dumps(response)[:200]}...")
            return json.dumps(response)
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for response ID {msg_id} after {timeout}s")
            return None
        finally:
            if msg_id in self._response_map:
                del self._response_map[msg_id]

    async def _read_stdout(self):
        while self._running and self.process and not self.process.stdout.at_eof():
            try:
                data = await self.process.stdout.read(4096)
                if not data:
                    break
                logger.debug(f"Received {len(data)} bytes from stdout: {data[:200].decode('utf-8', 'replace')}...")
                self._buffer.extend(data)
                logger.debug(f"Buffer size now {len(self._buffer)}")
                await self._process_buffer()
            except Exception as e:
                logger.error(f"Error reading stdout: {str(e)}", exc_info=True)
                break

    async def _process_buffer(self):
        while len(self._buffer) > 0:
            if self._content_length < 0:
                header_end = self._buffer.find(b'\r\n\r\n')
                if header_end == -1:
                    logger.debug(f"No header end found in buffer of size {len(self._buffer)}")
                    return
                headers = self._buffer[:header_end].decode('utf-8')
                self._buffer = self._buffer[header_end + 4:]
                match = re.search(r'Content-Length: (\d+)', headers)
                if match:
                    self._content_length = int(match.group(1))
                    logger.debug(f"Parsed Content-Length: {self._content_length}")
                else:
                    logger.error(f"Invalid headers: {headers}")
                    self._buffer.clear()
                    return

            if len(self._buffer) >= self._content_length:
                message_bytes = self._buffer[:self._content_length]
                self._buffer = self._buffer[self._content_length:]
                self._content_length = -1
                message_str = message_bytes.decode('utf-8', 'replace')
                logger.debug(f"Raw message received from JDT LS: {message_str[:200]}...")
                try:
                    message = json.loads(message_str)
                    msg_id = message.get("id")
                    if msg_id in self._response_map:
                        logger.debug(f"Matched response for ID {msg_id}: {json.dumps(message)[:200]}...")
                        self._response_map[msg_id].set_result(message)
                    elif self._notification_callback and "method" in message:
                        logger.debug(f"Processing notification: {json.dumps(message)[:200]}...")
                        await self._notification_callback(message)
                    else:
                        logger.warning(f"Unhandled message: {message_str[:200]}...")
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse message: {message_str[:200]}... - {str(e)}")
            else:
                logger.debug(f"Buffer size {len(self._buffer)} < Content-Length {self._content_length}, waiting for more data")
                break

    async def _read_stderr(self):
        while self._running and self.process and not self.process.stderr.at_eof():
            try:
                line = await self.process.stderr.readline()
                if line:
                    logger.warning(f"JDT LS stderr: {line.decode('utf-8').strip()}")
            except Exception as e:
                logger.error(f"Error reading stderr: {str(e)}", exc_info=True)

    async def stop(self):
        if not self._running or not self.process:
            logger.info("Subprocess already stopped")
            return
        self._running = False
        try:
            self.process.terminate()
            await asyncio.wait_for(self.process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Termination timed out, forcing kill")
            self.process.kill()
            await self.process.wait()
        except Exception as e:
            logger.error(f"Error stoppingtransition process: {str(e)}", exc_info=True)
        finally:
            self.process = None
            logger.info("Subprocess stopped")

    def get_output(self):
        stdout, stderr = "", ""
        if self.process:
            stdout = self.process.stdout.read().decode('utf-8', 'replace') if self.process.stdout else ""
            stderr = self.process.stderr.read().decode('utf-8', 'replace') if self.process.stderr else ""
        return stdout, stderr