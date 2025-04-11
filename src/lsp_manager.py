import os
import glob
import asyncio
from utils.subprocess_utils import SubprocessManager
import logging
import json
from typing import Dict, Optional
from logger import setup_logging
import traceback

setup_logging()
logger = logging.getLogger(__name__)

class LSPManager:
    def __init__(self, jdtls_base_path: str, base_workspace_dir: str):
        self.jdtls_base_path = jdtls_base_path
        self.base_workspace_dir = base_workspace_dir
        self.subprocess: Optional[SubprocessManager] = None
        self.workspaces: Dict[str, dict] = {}
        self.lock = asyncio.Lock()
        
        jar_pattern = os.path.join(jdtls_base_path, "plugins", "org.eclipse.equinox.launcher_*.jar")
        jar_files = glob.glob(jar_pattern)
        if not jar_files:
            logger.error(f"No JAR file found matching {jar_pattern}\n{traceback.format_exc()}")
            raise FileNotFoundError(f"No JAR file found matching {jar_pattern}")
        self.launcher_jar = jar_files[0]
        
        self.config_path = os.path.join(jdtls_base_path, "config_linux")
        if not os.path.exists(self.config_path):
            logger.error(f"Config directory not found at {self.config_path}\n{traceback.format_exc()}")
            raise FileNotFoundError(f"Config directory not found at {self.config_path}")
        logger.debug(f"LSPManager initialized with launcher_jar={self.launcher_jar}, config_path={self.config_path}")

    async def initialize(self):
        max_retries = 3
        retry_delay = 5.0
        for attempt in range(max_retries):
            try:
                async with self.lock:
                    if self.subprocess is not None:
                        logger.debug("Subprocess already initialized, skipping")
                        return

                    os.makedirs(self.base_workspace_dir, exist_ok=True)
                    logger.debug(f"Created base workspace directory: {self.base_workspace_dir}")
                    
                    cmd = [
                        "java",
                        "-Declipse.application=org.eclipse.jdt.ls.core.id1",
                        "-Dosgi.bundles.defaultStartLevel=4",
                        "-Declipse.product=org.eclipse.jdt.ls.core.product",
                        "-Dlog.level=ALL",
                        "-Xms1G",
                        "-Xmx2G",
                        "-jar", self.launcher_jar,
                        "-configuration", self.config_path,
                        "-data", self.base_workspace_dir,
                        "--add-modules=ALL-SYSTEM",
                        "--add-opens", "java.base/java.util=ALL-UNNAMED",
                        "--add-opens", "java.base/java.lang=ALL-UNNAMED"
                    ]
                    logger.debug(f"Starting JDT LS with command: {' '.join(cmd)}")

                    self.subprocess = SubprocessManager(cmd)
                    await self.subprocess.start()
                    logger.info(f"JDT LS process started with workspace {self.base_workspace_dir}")
                    return  # Success
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {str(e)}\n{traceback.format_exc()}")
                if self.subprocess:
                    await self.subprocess.stop()
                    self.subprocess = None
                if attempt < max_retries - 1:
                    logger.info(f"Retrying initialization after {retry_delay}s")
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"All {max_retries} attempts failed")
                    raise RuntimeError(f"JDT LS initialization failed after {max_retries} attempts: {str(e)}")

    async def process_message(self, workspace_id: str, message: str) -> Optional[str]:
        try:
            message_obj = json.loads(message)
            method = message_obj.get("method")
            msg_id = message_obj.get("id")
            logger.debug(f"Processing message for workspace_id={workspace_id}: {message[:200]}...")
            
            if workspace_id not in self.workspaces:
                logger.debug(f"Initializing new workspace for {workspace_id}")
                await self._init_workspace(workspace_id)
            
            await self.subprocess.send(message)
            logger.debug(f"Message sent to JDT LS: {message[:200]}...")
            
            if msg_id is not None:
                logger.debug(f"Waiting for response with ID {msg_id}")
                return await self._wait_for_response(msg_id)
            return None
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error for workspace_id={workspace_id}: {str(e)} - Message: {message[:200]}\n{traceback.format_exc()}")
            return self._create_error_response(None, -32700, "Parse error")
        except Exception as e:
            logger.error(f"Error processing message for workspace_id={workspace_id}: {str(e)}\n{traceback.format_exc()}")
            return self._create_error_response(None, -32603, "Internal error")

    async def _init_workspace(self, workspace_id: str):
        try:
            workspace_path = os.path.join(self.base_workspace_dir, workspace_id)
            os.makedirs(workspace_path, exist_ok=True)
            logger.debug(f"Created workspace directory: {workspace_path}")
            
            java_file = os.path.join(workspace_path, "Main.java")
            if not os.path.exists(java_file):
                with open(java_file, "w") as f:
                    f.write("""public class Main {
    public static void main(String[] args) {
        System.out.println("Hello, World!");
    }
}
""")
                logger.debug(f"Created default Java file: {java_file}")
            
            self.workspaces[workspace_id] = {"path": workspace_path}
            logger.info(f"Workspace initialized for {workspace_id}")
        except Exception as e:
            logger.error(f"Error initializing workspace {workspace_id}: {str(e)}\n{traceback.format_exc()}")
            raise

    async def _wait_for_response(self, msg_id, timeout=15.0) -> Optional[str]:
        try:
            if not self.subprocess:
                logger.error(f"No subprocess available for response ID {msg_id}\n{traceback.format_exc()}")
                return None
            response = await self.subprocess.receive(msg_id, timeout)
            logger.debug(f"Received response for ID {msg_id}: {response[:200]}...")
            return response
        except Exception as e:
            logger.error(f"Error waiting for response ID {msg_id}: {str(e)}\n{traceback.format_exc()}")
            return None

    def _create_error_response(self, msg_id, code: int, message: str) -> str:
        response = json.dumps({
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": code,
                "message": message
            }
        })
        logger.debug(f"Created error response: {response}")
        return response

    async def cleanup_workspace(self, workspace_id: str):
        try:
            if workspace_id in self.workspaces:
                del self.workspaces[workspace_id]
                logger.info(f"Cleaned up workspace {workspace_id}")
        except Exception as e:
            logger.error(f"Error cleaning up workspace {workspace_id}: {str(e)}\n{traceback.format_exc()}")

    async def cleanup(self):
        try:
            async with self.lock:
                if self.subprocess:
                    await self.subprocess.stop()
                    self.subprocess = None
                    logger.info("LSP subprocess cleaned up")
        except Exception as e:
            logger.error(f"Error in cleanup: {str(e)}\n{traceback.format_exc()}")