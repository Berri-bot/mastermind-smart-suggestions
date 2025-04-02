import subprocess
import threading
import queue
import json
import time
import os
from pathlib import Path
from typing import Dict, Optional, Any
from config import config
from logger import get_logger

logger = get_logger("lsp_manager")

class LSPManager:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._process: Optional[subprocess.Popen] = None
        self._queue: queue.Queue = queue.Queue()
        self._lock: threading.Lock = threading.Lock()
        self._request_id: int = 1
        self._initialized: bool = False

        self._start_server()
        threading.Thread(target=self._read_output, name="JavaLSP-Output-Reader", daemon=True).start()
        threading.Thread(target=self._read_errors, name="JavaLSP-Error-Reader", daemon=True).start()
        self.initialize()

    def _start_server(self) -> None:
        cmd = [
            str(config.JDK_HOME / "bin" / "java"),
            "-Declipse.application=org.eclipse.jdt.ls.core.id1",
            "-Dosgi.bundles.defaultStartLevel=4",
            "-Declipse.product=org.eclipse.jdt.ls.core.product",
            "-Dlog.level=ALL",
            "-Xmx2G",
            "-jar", str(config.JDT_LAUNCHER),
            "-configuration", str(config.JDT_CONFIG),
            "-data", str(self.workspace),
            "--add-modules=ALL-SYSTEM",
            "--add-opens", "java.base/java.util=ALL-UNNAMED",
            "--add-opens", "java.base/java.lang=ALL-UNNAMED"
        ]
        env = os.environ.copy()
        env["JAVA_HOME"] = str(config.JDK_HOME)
        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            text=False,
            env=env
        )
        logger.info(f"Java LSP server started for workspace {self.workspace} with PID: {self._process.pid}")
        time.sleep(2)
        if self._process.poll() is not None:
            error_output = self._process.stderr.read().decode('utf-8', errors='replace')
            raise RuntimeError(f"Java LSP server failed to start: {error_output or 'Unknown error'}")

    def initialize(self) -> None:
        response = self.send_request({
            "method": "initialize",
            "params": {
                "processId": os.getpid(),
                "rootUri": f"file://{self.workspace}",
                "capabilities": {
                    "textDocument": {"completion": {"completionItem": {"snippetSupport": True}}},
                    "workspace": {"configuration": True}
                },
                "workspaceFolders": [{"uri": f"file://{self.workspace}", "name": "workspace"}]
            }
        })
        if response and not response.get("error"):
            self.send_notification({"method": "initialized", "params": {}})
            self._initialized = True
            logger.info(f"Java LSP server initialized for workspace: {self.workspace}")
        else:
            error = response.get("error", {"message": "Unknown error"}) if response else {"message": "No response"}
            self.shutdown()
            raise RuntimeError(f"Java LSP initialization failed: {error['message']}")

    def send_request(self, message: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                raise RuntimeError("Java LSP server is not running")
            if message.get("method") != "initialize" and not self._initialized:
                raise RuntimeError("Java LSP server not initialized")
            message_id = self._request_id
            self._request_id += 1
            message["id"] = message_id
            message["jsonrpc"] = "2.0"
            message_str = json.dumps(message)
            headers = f"Content-Length: {len(message_str)}\r\n\r\n".encode('utf-8')
            self._process.stdin.write(headers + message_str.encode('utf-8'))
            self._process.stdin.flush()
            return self._wait_for_response(message_id)

    def send_notification(self, message: Dict[str, Any]) -> None:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                raise RuntimeError("Java LSP server is not running")
            message["jsonrpc"] = "2.0"
            message_str = json.dumps(message)
            headers = f"Content-Length: {len(message_str)}\r\n\r\n".encode('utf-8')
            self._process.stdin.write(headers + message_str.encode('utf-8'))
            self._process.stdin.flush()

    def _wait_for_response(self, request_id: int, timeout: int = 30) -> Dict[str, Any]:
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = self._queue.get(timeout=0.5)
                if response.get("id") == request_id:
                    return response
                self._queue.put(response)
            except queue.Empty:
                if self._process.poll() is not None:
                    raise RuntimeError("Java LSP server terminated")
        raise TimeoutError(f"Timeout waiting for response (ID: {request_id})")

    def _read_output(self) -> None:
        buffer = b''
        while self._process and self._process.poll() is None:
            try:
                data = os.read(self._process.stdout.fileno(), 4096)
                if not data:
                    time.sleep(0.1)
                    continue
                buffer += data
                while True:
                    header_end = buffer.find(b'\r\n\r\n')
                    if header_end == -1:
                        break
                    headers = buffer[:header_end].decode('utf-8')
                    content_length = int([line.split(': ')[1] for line in headers.split('\r\n') if 'Content-Length' in line][0])
                    message_start = header_end + 4
                    message_end = message_start + content_length
                    if len(buffer) < message_end:
                        break
                    message = buffer[message_start:message_end].decode('utf-8')
                    message_json = json.loads(message)
                    logger.debug(f"Received LSP message: {json.dumps(message_json, indent=2)}")
                    self._queue.put(message_json)
                    buffer = buffer[message_end:]
            except Exception as e:
                logger.error(f"Error reading Java LSP output: {e}", exc_info=True)
                time.sleep(1)

    def _read_errors(self) -> None:
        while self._process and self._process.poll() is None:
            try:
                line = self._process.stderr.readline().decode('utf-8', errors='replace').strip()
                if line:
                    logger.error(f"Java LSP error: {line}")
            except Exception as e:
                logger.error(f"Error reading Java LSP stderr: {e}", exc_info=True)
                time.sleep(1)

    def shutdown(self) -> None:
        if self._process:
            try:
                if self._initialized:
                    self.send_notification({"method": "exit", "params": {}})
                    time.sleep(1)
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            finally:
                self._process = None
                self._initialized = False
                logger.info(f"Java LSP server shut down for workspace: {self.workspace}")