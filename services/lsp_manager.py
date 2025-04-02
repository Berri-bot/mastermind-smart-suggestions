import subprocess
import threading
import queue
import json
import time
from pathlib import Path
from config import config
from logger import get_logger

logger = get_logger("lsp_manager")

class LSPManager:
    _java_process = None
    _java_queue = queue.Queue()
    _java_lock = threading.Lock()
    _java_request_id = 1

    @classmethod
    def initialize_servers(cls):
        logger.info("Initializing LSP servers...")
        try:
            cls._start_java_server()
            threading.Thread(target=cls._read_java_output, daemon=True).start()
            threading.Thread(target=cls._read_java_errors, daemon=True).start()
            # Wait longer for server to stabilize
            time.sleep(10)
            logger.info("LSP servers initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize LSP servers: {str(e)}", exc_info=True)
            raise

    @classmethod
    def _start_java_server(cls):
        logger.info("Starting Java LSP server...")
        try:
            jar_files = list((config.JDT_HOME / "plugins").glob("org.eclipse.equinox.launcher_*.jar"))
            if not jar_files:
                logger.error(f"No JDT launcher JAR found in {config.JDT_HOME}/plugins")
                raise FileNotFoundError(f"No JDT launcher JAR found in {config.JDT_HOME}/plugins")
            jar_path = jar_files[0]
            logger.info(f"Using Java LSP JAR: {jar_path}")

            cmd = [
                str(config.JDK_HOME / "bin" / "java"),
                "-Declipse.application=org.eclipse.jdt.ls.core.id1",
                "-Dosgi.bundles.defaultStartLevel=4",
                "-Declipse.product=org.eclipse.jdt.ls.core.product",
                "-Dlog.level=ALL",
                "-Xmx2G",
                "-jar", str(jar_path),
                "-configuration", str(config.JDT_CONFIG),
                "-data", str(config.WORKSPACE_DIR / "java_workspace")
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
            logger.info(f"Java LSP process started with PID: {cls._java_process.pid}")
            # Wait longer to ensure server is ready
            time.sleep(10)
            if cls._java_process.poll() is not None:
                error_output = cls._java_process.stderr.read().decode('utf-8', errors='replace')
                logger.error(f"Java LSP process terminated early. Error output: {error_output}")
                raise RuntimeError(f"Java LSP server failed to start: {error_output or 'No error output'}")
            logger.info("Java LSP server running successfully")
        except Exception as e:
            logger.error(f"Failed to start Java LSP server: {str(e)}", exc_info=True)
            raise

    @classmethod
    def _read_java_output(cls):
        logger.info("Starting Java LSP output reader...")
        buffer = b''
        while True:
            try:
                data = cls._java_process.stdout.read(4096)
                if not data:
                    logger.warning("Java LSP stdout closed")
                    break
                buffer += data
                while b'Content-Length:' in buffer:
                    try:
                        length_end = buffer.index(b'\r\n\r\n') + 4
                        length_str = buffer[:length_end].decode('utf-8').split(': ')[1].split('\r\n')[0]
                        content_length = int(length_str)
                        if len(buffer) >= length_end + content_length:
                            message = buffer[length_end:length_end + content_length].decode('utf-8')
                            logger.debug(f"Java LSP output: {message}")
                            cls._java_queue.put(json.loads(message))
                            buffer = buffer[length_end + content_length:]
                        else:
                            break
                    except (ValueError, IndexError) as e:
                        logger.error(f"Error parsing LSP message: {str(e)} - Buffer: {buffer[:100]}")
                        buffer = b''  # Reset buffer on parse error
                        break
            except Exception as e:
                logger.error(f"Error reading Java LSP output: {str(e)}", exc_info=True)
                break

    @classmethod
    def _read_java_errors(cls):
        logger.info("Starting Java LSP error reader...")
        while True:
            line = cls._java_process.stderr.readline()
            if not line:
                logger.warning("Java LSP stderr closed")
                break
            logger.error(f"Java LSP stderr: {line.decode('utf-8').strip()}")

    @classmethod
    def send_java_request(cls, message: dict) -> dict:
        with cls._java_lock:
            try:
                message_id = cls._java_request_id
                cls._java_request_id += 1
                message["id"] = message_id
                message["jsonrpc"] = "2.0"  # Ensure jsonrpc is set
                message_str = json.dumps(message)
                headers = f"Content-Length: {len(message_str)}\r\n\r\n".encode('utf-8')
                logger.debug(f"Sending Java LSP request (ID: {message_id}): {message_str}")
                cls._java_process.stdin.write(headers + message_str.encode('utf-8'))
                cls._java_process.stdin.flush()
                
                response = cls._wait_for_response(message_id)
                if response is None:
                    logger.error(f"Timeout waiting for Java LSP response (ID: {message_id})")
                    return {"error": {"code": -32603, "message": "Timeout waiting for LSP response"}}
                logger.debug(f"Received Java LSP response (ID: {message_id}): {json.dumps(response)}")
                return response
            except Exception as e:
                logger.error(f"Error sending Java request: {str(e)}", exc_info=True)
                return {"error": {"code": -32603, "message": str(e)}}

    @classmethod
    def send_java_notification(cls, message: dict):
        with cls._java_lock:
            try:
                message["jsonrpc"] = "2.0"
                message_str = json.dumps(message)
                headers = f"Content-Length: {len(message_str)}\r\n\r\n".encode('utf-8')
                logger.debug(f"Sending Java LSP notification: {message_str}")
                cls._java_process.stdin.write(headers + message_str.encode('utf-8'))
                cls._java_process.stdin.flush()
            except Exception as e:
                logger.error(f"Error sending Java notification: {str(e)}", exc_info=True)

    @classmethod
    def _wait_for_response(cls, request_id: int) -> dict:
        start_time = time.time()
        timeout = 20  # Increased timeout to 20 seconds
        while time.time() - start_time < timeout:
            try:
                response = cls._java_queue.get(timeout=0.5)
                logger.debug(f"Checking response: {response}")
                if response.get("id") == request_id:
                    return response
                else:
                    logger.warning(f"Received unmatched response: {response}")
                    cls._java_queue.put(response)  # Put back unmatched responses
            except queue.Empty:
                continue
        return None

    @classmethod
    def shutdown(cls):
        logger.info("Shutting down LSP servers...")
        if cls._java_process:
            cls._java_process.terminate()
            cls._java_process.wait(timeout=5)
            logger.info("Java LSP server terminated")