import os
import glob
import asyncio
import json
from typing import Dict, Optional
from utils.subprocess_utils import SubprocessManager
import logging

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
            raise FileNotFoundError(f"No JAR file found matching {jar_pattern}")
        self.launcher_jar = jar_files[0]
        
        self.config_path = os.path.join(jdtls_base_path, "config_linux")
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config directory not found at {self.config_path}")

    async def initialize(self):
        async with self.lock:
            if self.subprocess is not None:
                return

            os.makedirs(self.base_workspace_dir, exist_ok=True)
            
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

            self.subprocess = SubprocessManager(cmd)
            await self.subprocess.start()

    async def process_message(self, workspace_id: str, message: str) -> Optional[str]:
        try:
            message_obj = json.loads(message)
            method = message_obj.get("method")
            msg_id = message_obj.get("id")
            
            if workspace_id not in self.workspaces:
                await self._init_workspace(workspace_id)
            
            await self.subprocess.send(message)
            
            if msg_id is not None:
                return await self._wait_for_response(msg_id)
            return None
                
        except json.JSONDecodeError:
            return self._create_error_response(None, -32700, "Parse error")
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            return self._create_error_response(None, -32603, "Internal error")

    async def _init_workspace(self, workspace_id: str):
        workspace_path = os.path.join(self.base_workspace_dir, workspace_id)
        os.makedirs(workspace_path, exist_ok=True)
        
        java_file = os.path.join(workspace_path, "Main.java")
        if not os.path.exists(java_file):
            with open(java_file, "w") as f:
                f.write("""public class Main {
    public static void main(String[] args) {
        System.out.println("Hello, World!");
    }
}""")
        
        self.workspaces[workspace_id] = {"path": workspace_path}

    async def _wait_for_response(self, msg_id, timeout=10.0) -> Optional[str]:
        if not self.subprocess:
            return None
        return await self.subprocess.receive(msg_id, timeout)

    def _create_error_response(self, msg_id, code: int, message: str) -> str:
        return json.dumps({
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message}
        })

    async def cleanup_workspace(self, workspace_id: str):
        if workspace_id in self.workspaces:
            del self.workspaces[workspace_id]

    async def cleanup(self):
        async with self.lock:
            if self.subprocess:
                await self.subprocess.stop()
                self.subprocess = None