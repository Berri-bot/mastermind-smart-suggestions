import asyncio
import json
import logging
import re
from typing import Optional, Dict, Any, Callable, Tuple
import os

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
        self._stdout_lines = []
        self._stderr_lines = []

    def set_notification_callback(self, callback: Callable):
        """Set callback for handling notifications from the subprocess"""
        self._notification_callback = callback

    async def start(self):
        """Start the subprocess and begin monitoring stdout/stderr"""
        try:
            logger.info(f"Starting subprocess with command: {' '.join(self.command)}")
            logger.info(f"Current working directory: {os.getcwd()}")
            logger.info(f"Environment PATH: {os.getenv('PATH')}")
            
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=os.environ
            )
            
            self._running = True
            logger.info(f"Subprocess started with PID {self.process.pid}")
            
            # Start monitoring tasks
            asyncio.create_task(self._read_stdout())
            asyncio.create_task(self._read_stderr())
            
        except Exception as e:
            logger.error(f"Failed to start subprocess: {str(e)}", exc_info=True)
            raise RuntimeError(f"Subprocess startup failed: {str(e)}")

    async def send(self, message: str):
        """Send a message to the subprocess"""
        if not self._running or not self.process or not self.process.stdin:
            logger.error("Cannot send message: Subprocess not running")
            raise RuntimeError("Subprocess not running")
            
        content = message.encode('utf-8')
        headers = f"Content-Length: {len(content)}\r\n\r\n".encode('utf-8')
        
        try:
            self.process.stdin.write(headers + content)
            await self.process.stdin.drain()
            logger.debug(f"Sent message to subprocess: {message[:200]}...")
        except Exception as e:
            logger.error(f"Failed to send message: {str(e)}", exc_info=True)
            raise RuntimeError(f"Message send failed: {str(e)}")

    async def receive(self, msg_id: Any, timeout: float = 60.0) -> Optional[dict]:
        """Wait for a response with the given message ID"""
        if not self._running or msg_id is None:
            logger.warning(f"Cannot receive for ID {msg_id}: Subprocess not running or invalid ID")
            return None
            
        future = asyncio.get_event_loop().create_future()
        self._response_map[msg_id] = future
        
        try:
            response = await asyncio.wait_for(future, timeout)
            logger.debug(f"Received response for ID {msg_id}: {json.dumps(response)[:200]}...")
            return response
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for response ID {msg_id} after {timeout}s")
            return None
        finally:
            if msg_id in self._response_map:
                del self._response_map[msg_id]

    async def _read_stdout(self):
        """Continuously read from subprocess stdout"""
        buffer_lines = []
        while self._running and self.process and not self.process.stdout.at_eof():
            try:
                data = await self.process.stdout.read(4096)
                if not data:
                    logger.warning("Subprocess stdout closed")
                    break
                    
                self._buffer.extend(data)
                decoded = data.decode('utf-8', 'replace')
                buffer_lines.extend(decoded.splitlines())
                self._stdout_lines.extend(decoded.splitlines())
                
                # Keep buffer manageable
                if len(buffer_lines) > 100:
                    buffer_lines = buffer_lines[-100:]
                if len(self._stdout_lines) > 1000:
                    self._stdout_lines = self._stdout_lines[-1000:]
                    
                await self._process_buffer()
                
            except Exception as e:
                logger.error(f"Stdout read error: {str(e)}", exc_info=True)
                break
                
        logger.info("Subprocess stdout monitoring ended")

    async def _process_buffer(self):
        """Process the buffer to extract complete messages"""
        while len(self._buffer) > 0:
            if self._content_length < 0:
                # Look for headers
                header_end = self._buffer.find(b'\r\n\r\n')
                if header_end == -1:
                    return
                    
                headers = self._buffer[:header_end].decode('utf-8')
                self._buffer = self._buffer[header_end + 4:]
                
                # Extract content length
                match = re.search(r'Content-Length: (\d+)', headers)
                if match:
                    self._content_length = int(match.group(1))
                    logger.debug(f"Content-Length: {self._content_length}")
                else:
                    logger.error(f"Invalid headers: {headers}")
                    self._buffer.clear()
                    return

            if len(self._buffer) >= self._content_length:
                # Complete message received
                message_bytes = self._buffer[:self._content_length]
                self._buffer = self._buffer[self._content_length:]
                self._content_length = -1
                
                try:
                    message_str = message_bytes.decode('utf-8', 'replace')
                    logger.debug(f"Raw message: {message_str[:200]}...")
                    message = json.loads(message_str)
                    
                    # Handle response or notification
                    msg_id = message.get("id")
                    if msg_id in self._response_map:
                        logger.debug(f"Matched response for ID {msg_id}")
                        self._response_map[msg_id].set_result(message)
                    elif self._notification_callback and "method" in message:
                        logger.debug(f"Processing notification: {message.get('method')}")
                        await self._notification_callback(message)
                    else:
                        logger.warning(f"Unhandled message: {message_str[:200]}...")
                        
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse message: {message_bytes[:200]}... Error: {str(e)}")
                except Exception as e:
                    logger.error(f"Error processing message: {str(e)}", exc_info=True)

    async def _read_stderr(self):
        """Continuously read from subprocess stderr"""
        error_lines = []
        while self._running and self.process and not self.process.stderr.at_eof():
            try:
                line = await self.process.stderr.readline()
                if line:
                    decoded = line.decode('utf-8', 'replace').strip()
                    error_lines.append(decoded)
                    self._stderr_lines.append(decoded)
                    logger.error(f"Subprocess ERROR: {decoded}")
                    
                    # Keep buffer manageable
                    if len(error_lines) > 100:
                        error_lines = error_lines[-100:]
                    if len(self._stderr_lines) > 1000:
                        self._stderr_lines = self._stderr_lines[-1000:]
                        
            except Exception as e:
                logger.error(f"Stderr read error: {str(e)}", exc_info=True)
                break
                
        logger.info("Subprocess stderr monitoring ended")
        logger.error(f"Last error lines:\n{'\n'.join(error_lines[-20:])}")

    def get_output(self) -> Tuple[str, str]:
        """Get captured stdout and stderr output"""
        stdout = '\n'.join(self._stdout_lines) if self._stdout_lines else ""
        stderr = '\n'.join(self._stderr_lines) if self._stderr_lines else ""
        return stdout, stderr

    async def stop(self):
        """Gracefully stop the subprocess"""
        if not self._running or not self.process:
            logger.info("Subprocess already stopped")
            return
            
        self._running = False
        try:
            logger.info("Initiating subprocess shutdown")
            
            # Send shutdown request if process is still alive
            if self.process.returncode is None:
                shutdown_msg = {"jsonrpc": "2.0", "id": 9999, "method": "shutdown"}
                await self.send(json.dumps(shutdown_msg))
                
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("Graceful shutdown timed out, terminating")
                    self.process.terminate()
                    await self.process.wait()
                    
            logger.info(f"Subprocess exited with code {self.process.returncode}")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {str(e)}", exc_info=True)
            try:
                self.process.kill()
                await self.process.wait()
            except:
                pass
        finally:
            self.process = None
            logger.info("Subprocess fully stopped")