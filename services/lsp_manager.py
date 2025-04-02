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
    _java_process: Optional[subprocess.Popen] = None
    _java_queue: queue.Queue = queue.Queue()
    _java_lock: threading.Lock = threading.Lock()
    _java_request_id: int = 1
    _initialized: bool = False

    @classmethod
    def initialize_servers(cls) -> None:
        """Initialize all LSP servers with proper error handling"""
        logger.info("Initializing LSP servers...")
        try:
            cls._start_java_server()
            
            # Start reader threads
            threading.Thread(
                target=cls._read_java_output,
                name="JavaLSP-Output-Reader",
                daemon=True
            ).start()
            
            threading.Thread(
                target=cls._read_java_errors,
                name="JavaLSP-Error-Reader",
                daemon=True
            ).start()

            # Verify server is ready
            if not cls._verify_server_ready():
                raise RuntimeError("Java LSP server failed to become ready")
            
            cls._initialized = True
            logger.info("LSP servers initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize LSP servers", exc_info=True)
            cls.shutdown()
            raise

    @classmethod
    def _verify_server_ready(cls, timeout: int = 30) -> bool:
        """Verify the server is ready by sending a simple request"""
        logger.info("Verifying Java LSP server readiness...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                response = cls.send_java_request({
                    "method": "initialize",
                    "params": {
                        "processId": os.getpid(),
                        "rootUri": f"file://{config.WORKSPACE_DIR}",
                        "capabilities": {},
                        "workspaceFolders": [
                            {"uri": f"file://{config.WORKSPACE_DIR}", "name": "workspace"}
                        ]
                    }
                })
                
                if response and not response.get("error"):
                    logger.info("Java LSP server is ready")
                    return True
                
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Server readiness check failed: {str(e)}")
                time.sleep(1)
        
        logger.error("Java LSP server readiness verification timeout")
        return False

    @classmethod
    def _start_java_server(cls) -> None:
        """Start the Java LSP server process with proper configuration"""
        logger.info("Starting Java LSP server...")
        
        try:
            # Build the command
            cmd = [
                str(config.JDK_HOME / "bin" / "java"),
                "-Declipse.application=org.eclipse.jdt.ls.core.id1",
                "-Dosgi.bundles.defaultStartLevel=4",
                "-Declipse.product=org.eclipse.jdt.ls.core.product",
                "-Dlog.level=ALL",
                "-Xmx2G",
                "-jar", str(config.JDT_LAUNCHER),
                "-configuration", str(config.JDT_CONFIG),
                "-data", str(config.WORKSPACE_DIR / "java_workspace"),
                "--add-modules=ALL-SYSTEM",
                "--add-opens", "java.base/java.util=ALL-UNNAMED",
                "--add-opens", "java.base/java.lang=ALL-UNNAMED"
            ]
            
            logger.debug(f"Java LSP command: {' '.join(cmd)}")
            
            # Prepare environment
            env = os.environ.copy()
            env["JAVA_HOME"] = str(config.JDK_HOME)
            env["WORKSPACE"] = str(config.WORKSPACE_DIR)
            
            # Start the process
            cls._java_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                text=False,
                env=env
            )
            
            logger.info(f"Java LSP server started with PID: {cls._java_process.pid}")
            
            # Verify process is running
            time.sleep(2)
            if cls._java_process.poll() is not None:
                error_output = cls._java_process.stderr.read().decode('utf-8', errors='replace')
                logger.error(f"Java LSP process terminated. Exit code: {cls._java_process.returncode}")
                logger.error(f"Error output:\n{error_output}")
                raise RuntimeError(f"Java LSP server failed to start: {error_output or 'Unknown error'}")
            
        except Exception as e:
            logger.error("Failed to start Java LSP server", exc_info=True)
            if cls._java_process:
                cls._java_process.terminate()
            raise RuntimeError(f"Java LSP server failed to start: {str(e)}")

    @classmethod
    def _read_java_output(cls) -> None:
        """Thread for reading stdout from Java LSP server"""
        logger.info("Starting Java LSP output reader thread")
        buffer = b''
        
        try:
            while cls._java_process and cls._java_process.poll() is None:
                try:
                    # Read available data
                    data = os.read(cls._java_process.stdout.fileno(), 4096)
                    if not data:
                        time.sleep(0.1)
                        continue
                    
                    buffer += data
                    
                    # Process complete messages
                    while True:
                        # Check for complete header
                        header_end = buffer.find(b'\r\n\r\n')
                        if header_end == -1:
                            break
                        
                        # Parse content length
                        headers = buffer[:header_end].decode('utf-8')
                        content_length = 0
                        
                        for line in headers.split('\r\n'):
                            if line.startswith('Content-Length:'):
                                content_length = int(line[len('Content-Length:'):].strip())
                                break
                        
                        # Check if we have complete message
                        message_start = header_end + 4
                        message_end = message_start + content_length
                        
                        if len(buffer) < message_end:
                            break
                        
                        # Extract and process message
                        message = buffer[message_start:message_end].decode('utf-8')
                        try:
                            message_json = json.loads(message)
                            logger.debug(f"Received LSP message: {json.dumps(message_json, indent=2)}")
                            cls._java_queue.put(message_json)
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse LSP message: {str(e)}\nMessage: {message[:200]}...")
                        
                        # Remove processed message from buffer
                        buffer = buffer[message_end:]
                
                except Exception as e:
                    logger.error(f"Error reading Java LSP output: {str(e)}", exc_info=True)
                    time.sleep(1)
        
        except Exception as e:
            logger.error("Java LSP output reader thread crashed", exc_info=True)
        finally:
            logger.info("Java LSP output reader thread exiting")

    @classmethod
    def _read_java_errors(cls) -> None:
        """Thread for reading stderr from Java LSP server"""
        logger.info("Starting Java LSP error reader thread")
        
        try:
            while cls._java_process and cls._java_process.poll() is None:
                try:
                    line = cls._java_process.stderr.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
                    
                    error_line = line.decode('utf-8', errors='replace').strip()
                    if error_line:
                        logger.error(f"Java LSP error: {error_line}")
                except Exception as e:
                    logger.error(f"Error reading Java LSP stderr: {str(e)}", exc_info=True)
                    time.sleep(1)
        
        except Exception as e:
            logger.error("Java LSP error reader thread crashed", exc_info=True)
        finally:
            logger.info("Java LSP error reader thread exiting")

    @classmethod
    def send_java_request(cls, message: Dict[str, Any]) -> Dict[str, Any]:
        """Send a request to the Java LSP server and wait for response"""
        with cls._java_lock:
            if not cls._initialized:
                raise RuntimeError("Java LSP server not initialized")
            
            if cls._java_process is None or cls._java_process.poll() is not None:
                raise RuntimeError("Java LSP server is not running")
            
            try:
                message_id = cls._java_request_id
                cls._java_request_id += 1
                
                message["id"] = message_id
                message["jsonrpc"] = "2.0"
                
                message_str = json.dumps(message)
                headers = f"Content-Length: {len(message_str)}\r\n\r\n".encode('utf-8')
                full_message = headers + message_str.encode('utf-8')
                
                logger.debug(f"Sending Java LSP request (ID: {message_id}): {message_str}")
                
                cls._java_process.stdin.write(full_message)
                cls._java_process.stdin.flush()
                
                return cls._wait_for_response(message_id)
            
            except Exception as e:
                logger.error(f"Error sending Java request: {str(e)}", exc_info=True)
                return {"error": {"code": -32603, "message": str(e)}}

    @classmethod
    def send_java_notification(cls, message: Dict[str, Any]) -> None:
        """Send a notification to the Java LSP server"""
        with cls._java_lock:
            if not cls._initialized:
                raise RuntimeError("Java LSP server not initialized")
            
            if cls._java_process is None or cls._java_process.poll() is not None:
                raise RuntimeError("Java LSP server is not running")
            
            try:
                message["jsonrpc"] = "2.0"
                message_str = json.dumps(message)
                headers = f"Content-Length: {len(message_str)}\r\n\r\n".encode('utf-8')
                
                logger.debug(f"Sending Java LSP notification: {message_str}")
                
                cls._java_process.stdin.write(headers + message_str.encode('utf-8'))
                cls._java_process.stdin.flush()
            
            except Exception as e:
                logger.error(f"Error sending Java notification: {str(e)}", exc_info=True)
                raise

    @classmethod
    def _wait_for_response(cls, request_id: int, timeout: int = 30) -> Dict[str, Any]:
        """Wait for a response with the given request ID"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                response = cls._java_queue.get(timeout=0.5)
                
                if response.get("id") == request_id:
                    return response
                
                # Put back unmatched responses
                cls._java_queue.put(response)
                logger.debug(f"Received unmatched response (expected ID: {request_id}): {json.dumps(response)}")
            
            except queue.Empty:
                if cls._java_process.poll() is not None:
                    raise RuntimeError("Java LSP server terminated while waiting for response")
                continue
        
        raise TimeoutError(f"Timeout waiting for response (ID: {request_id})")

    @classmethod
    def shutdown(cls) -> None:
        """Shutdown all LSP servers"""
        logger.info("Shutting down LSP servers...")
        
        try:
            if cls._java_process:
                # Send exit notification if possible
                if cls._initialized:
                    try:
                        cls.send_java_notification({"method": "exit", "params": {}})
                        time.sleep(1)
                    except Exception as e:
                        logger.warning(f"Error sending exit notification: {str(e)}")
                
                # Terminate the process
                try:
                    cls._java_process.terminate()
                    cls._java_process.wait(timeout=5)
                    logger.info(f"Java LSP server terminated (exit code: {cls._java_process.returncode})")
                except subprocess.TimeoutExpired:
                    cls._java_process.kill()
                    logger.warning("Java LSP server forcefully killed")
        
        except Exception as e:
            logger.error("Error during LSP server shutdown", exc_info=True)
        finally:
            cls._java_process = None
            cls._initialized = False
            logger.info("LSP servers shutdown complete")