import os
import subprocess
import logging
import threading
import queue
import json
import re
import time
from pathlib import Path
from typing import Dict, Optional
from config import config

logger = logging.getLogger(__name__)

class LSPManager:
    _java_process = None
    _python_process = None
    _java_queue = queue.Queue()
    _python_queue = queue.Queue()
    _java_lock = threading.Lock()
    _python_lock = threading.Lock()
    _java_request_id = 1
    _python_request_id = 1

    @classmethod
    def initialize_servers(cls):
        try:
            logger.info("Initializing LSP servers...")
            cls._start_java_server()
            cls._start_python_server()
            threading.Thread(target=cls._read_java_output, daemon=True).start()
            threading.Thread(target=cls._read_java_errors, daemon=True).start()
            threading.Thread(target=cls._read_python_output, daemon=True).start()
            threading.Thread(target=cls._read_python_errors, daemon=True).start()
            logger.info("LSP servers initialized")
        except Exception as e:
            logger.error(f"Failed to initialize LSP servers: {str(e)}", exc_info=True)
            raise

    @classmethod
    def _start_java_server(cls):
        try:
            jdt_path = config.JDT_HOME
            jar_files = list((jdt_path / "plugins").glob("org.eclipse.equinox.launcher_*.jar"))
            if not jar_files:
                raise FileNotFoundError(f"No JDT launcher JAR found in {jdt_path}/plugins")
            jar_path = jar_files[0]
            logger.info(f"Starting Java LSP with: {jar_path}")

            cmd = [
                str(config.JDK_HOME / "bin" / "java"),
                "-Declipse.application=org.eclipse.jdt.ls.core.id1",
                "-Dosgi.bundles.defaultStartLevel=4",
                "-Declipse.product=org.eclipse.jdt.ls.core.product",
                "-Dlog.level=ALL",
                "-Xmx2G",
                "-XX:+UseG1GC",
                "-XX:+UseStringDeduplication",
                "-Djava.home=" + str(config.JDK_HOME),
                "-jar", str(jar_path),
                "-configuration", str(config.JDT_CONFIG),
                "-data", str(config.WORKSPACE_DIR / "java_workspace"),
                "--add-modules=ALL-SYSTEM",
                "--add-opens", "java.base/java.util=ALL-UNNAMED",
                "--add-opens", "java.base/java.lang=ALL-UNNAMED",
                "-noverify"
            ]
            logger.debug(f"Java LSP command: {' '.join(cmd)}")
            cls._java_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                text=False
            )
            time.sleep(5)  # Give server time to start
            if cls._java_process.poll() is not None:
                error = cls._java_process.stderr.read().decode()
                raise RuntimeError(f"Java LSP server failed to start: {error}")
            logger.info(f"Java LSP server started with PID: {cls._java_process.pid}")
        except Exception as e:
            logger.error(f"Failed to start Java LSP server: {str(e)}", exc_info=True)
            raise

    @classmethod
    def _start_python_server(cls):
        try:
            cmd = config.PYTHON_LSP_CMD
            cls._python_process = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
            )
            logger.info(f"Python LSP server started with PID: {cls._python_process.pid}")
        except Exception as e:
            logger.error(f"Failed to start Python LSP server: {str(e)}", exc_info=True)
            raise

    @classmethod
    def _read_java_output(cls):
        buffer = b''
        header_pattern = re.compile(br'Content-Length: (\d+)\r\n\r\n')
        while True:
            try:
                data = cls._java_process.stdout.read(4096)
                if not data:
                    logger.warning("Java LSP stdout closed")
                    break
                buffer += data
                while True:
                    match = header_pattern.search(buffer)
                    if not match:
                        break
                    content_length = int(match.group(1))
                    header_end = match.end()
                    if len(buffer) >= header_end + content_length:
                        message = buffer[header_end:header_end+content_length].decode('utf-8')
                        try:
                            json_msg = json.loads(message)
                            logger.debug(f"Received Java LSP message: {json_msg}")
                            cls._java_queue.put(json_msg)
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse JSON: {message}")
                        buffer = buffer[header_end+content_length:]
                    else:
                        break
            except Exception as e:
                logger.error(f"Error reading Java LSP output: {str(e)}", exc_info=True)
                break

    @classmethod
    def _read_java_errors(cls):
        while True:
            line = cls._java_process.stderr.readline()
            if not line:
                logger.warning("Java LSP stderr closed")
                break
            logger.error(f"Java LSP error: {line.decode().strip()}")

    @classmethod
    def _read_python_output(cls):
        buffer = ""
        content_length = None
        while True:
            try:
                line = cls._python_process.stdout.readline()
                if not line:
                    logger.warning("Python LSP stdout closed")
                    break
                buffer += line
                if "Content-Length:" in line:
                    content_length = int(line.strip().split(":")[1].strip())
                    buffer = ""
                elif line.strip() == "" and content_length is not None:
                    message = cls._python_process.stdout.read(content_length)
                    try:
                        json_msg = json.loads(message)
                        logger.debug(f"Received Python LSP message: {json_msg}")
                        cls._python_queue.put(json_msg)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse JSON: {message}")
                    content_length = None
                    buffer = ""
            except Exception as e:
                logger.error(f"Error reading Python LSP output: {str(e)}", exc_info=True)
                break

    @classmethod
    def _read_python_errors(cls):
        while True:
            line = cls._python_process.stderr.readline()
            if not line:
                logger.warning("Python LSP stderr closed")
                break
            logger.error(f"Python LSP error: {line.strip()}")

    @classmethod
    def send_java_request(cls, message: dict) -> Optional[dict]:
        with cls._java_lock:
            try:
                message_id = cls._java_request_id
                cls._java_request_id += 1
                message["id"] = message_id
                message_str = json.dumps(message)
                headers = f"Content-Length: {len(message_str)}\r\n\r\n".encode('utf-8')
                logger.debug(f"Sending Java LSP request (ID: {message_id}): {message_str}")
                cls._java_process.stdin.write(headers + message_str.encode('utf-8'))
                cls._java_process.stdin.flush()
                
                # Additional wait for project configuration
                if message.get("method") == "textDocument/completion":
                    time.sleep(0.5)
                
                response = cls._wait_for_response(cls._java_queue, message_id)
                if response is None:
                    logger.error(f"Timeout waiting for Java LSP response (ID: {message_id})")
                else:
                    logger.debug(f"Received Java LSP response (ID: {message_id}): {json.dumps(response)}")
                return response
            except Exception as e:
                logger.error(f"Error sending Java request: {str(e)}", exc_info=True)
                return None

    @classmethod
    def send_java_notification(cls, message: dict) -> None:
        with cls._java_lock:
            try:
                message_str = json.dumps(message)
                headers = f"Content-Length: {len(message_str)}\r\n\r\n".encode('utf-8')
                logger.debug(f"Sending Java LSP notification: {message_str}")
                cls._java_process.stdin.write(headers + message_str.encode('utf-8'))
                cls._java_process.stdin.flush()
            except Exception as e:
                logger.error(f"Error sending Java notification: {str(e)}", exc_info=True)

    @classmethod
    def _wait_for_response(cls, q: queue.Queue, request_id: int) -> Optional[dict]:
        start_time = time.time()
        timeout = 30
        while time.time() - start_time < timeout:
            try:
                response = q.get(timeout=0.1)
                if isinstance(response, dict) and response.get("id") == request_id:
                    return response
                q.put(response)
            except queue.Empty:
                continue
        logger.error(f"Timeout waiting for response to request ID {request_id} after {timeout} seconds")
        return None

    @classmethod
    def shutdown(cls):
        try:
            if cls._java_process:
                cls.send_java_notification({
                    "jsonrpc": "2.0",
                    "method": "exit",
                    "params": {}
                })
                cls._java_process.terminate()
                cls._java_process.wait(timeout=5)
            if cls._python_process:
                cls._python_process.terminate()
                cls._python_process.wait(timeout=5)
            logger.info("LSP servers shutdown")
        except Exception as e:
            logger.error(f"Error during LSP shutdown: {str(e)}", exc_info=True)