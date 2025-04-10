import asyncio
import json
import logging
import re
from typing import Optional, Dict, Any, Callable
from logger import setup_logging
import traceback

setup_logging()
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
        logger.debug(f"SubprocessManager initialized with command: {' '.join(command)}")

    def set_notification_callback(self, callback: Callable):
        self._notification_callback = callback
        logger.debug("Notification callback set")

    async def start(self):
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            logger.debug(f"Subprocess created with PID {self.process.pid}")
            self._running = True
            asyncio.create_task(self._read_stdout())
            asyncio.create_task(self._read_stderr())
            # Check if process dies immediately
            await asyncio.sleep(1)
            if self.process.returncode is not None:
                logger.error(f"Subprocess exited immediately with code {self.process.returncode}")
                raise RuntimeError(f"Subprocess failed to start, exit code: {self.process.returncode}")
            logger.info(f"Subprocess started with PID {self.process.pid}")
        except Exception as e:
            logger.error(f"Error starting subprocess: {str(e)}\n{traceback.format_exc()}")
            raise

    async def send(self, message: str):
        try:
            if not self._running or not self.process or not self.process.stdin:
                logger.error(f"Cannot send message: Subprocess not running\n{traceback.format_exc()}")
                raise RuntimeError("Subprocess not running")
            content = message.encode('utf-8')
            headers = f"Content-Length: {len(content)}\r\n\r\n".encode('utf-8')
            self.process.stdin.write(headers + content)
            await self.process.stdin.drain()
            logger.debug(f"Sent message to JDT LS: {message[:200]}...")
        except Exception as e:
            logger.error(f"Failed to send message: {str(e)}\n{traceback.format_exc()}")
            raise

    async def receive(self, msg_id: Any, timeout: float = 10.0) -> Optional[str]:
        try:
            if not self._running or msg_id is None:
                logger.warning(f"Cannot receive for ID {msg_id}: Subprocess not running or invalid ID\n{traceback.format_exc()}")
                return None
            future = asyncio.get_event_loop().create_future()
            self._response_map[msg_id] = future
            response = await asyncio.wait_for(future, timeout)
            logger.debug(f"Received response for ID {msg_id}: {json.dumps(response)[:200]}...")
            return json.dumps(response)
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for response ID {msg_id} after {timeout}s\n{traceback.format_exc()}")
            return None
        except Exception as e:
            logger.error(f"Error receiving for ID {msg_id}: {str(e)}\n{traceback.format_exc()}")
            return None
        finally:
            if msg_id in self._response_map:
                del self._response_map[msg_id]
                logger.debug(f"Cleaned up response map for ID {msg_id}")

    async def _read_stdout(self):
        try:
            while self._running and self.process and not self.process.stdout.at_eof():
                data = await self.process.stdout.read(4096)
                if not data:
                    logger.debug("No more data from stdout, breaking")
                    break
                self._buffer.extend(data)
                logger.debug(f"Read {len(data)} bytes from stdout, buffer size now {len(self._buffer)}")
                await self._process_buffer()
        except Exception as e:
            logger.error(f"Error reading stdout: {str(e)}\n{traceback.format_exc()}")
            raise

    async def _process_buffer(self):
        try:
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
                        logger.error(f"Invalid headers: {headers}\n{traceback.format_exc()}")
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
                        logger.error(f"Failed to parse message: {message_str[:200]}... - {str(e)}\n{traceback.format_exc()}")
                else:
                    logger.debug(f"Buffer size {len(self._buffer)} < Content-Length {self._content_length}, waiting for more data")
                    break
        except Exception as e:
            logger.error(f"Error processing buffer: {str(e)}\n{traceback.format_exc()}")

    async def _read_stderr(self):
        try:
            while self._running and self.process and not self.process.stderr.at_eof():
                line = await self.process.stderr.readline()
                if line:
                    stderr_line = line.decode('utf-8').strip()
                    logger.warning(f"JDT LS stderr: {stderr_line}")
        except Exception as e:
            logger.error(f"Error reading stderr: {str(e)}\n{traceback.format_exc()}")

    async def stop(self):
        try:
            if not self._running or not self.process:
                logger.info("Subprocess already stopped")
                return
            self._running = False
            self.process.terminate()
            await asyncio.wait_for(self.process.wait(), timeout=5.0)
            logger.info("Subprocess terminated gracefully")
        except asyncio.TimeoutError:
            logger.warning(f"Termination timed out, forcing kill\n{traceback.format_exc()}")
            self.process.kill()
            await self.process.wait()
        except Exception as e:
            logger.error(f"Error stopping process: {str(e)}\n{traceback.format_exc()}")
        finally:
            self.process = None
            logger.info("Subprocess stopped")