import json
import logging
import os
import shutil
from typing import Optional
from fastapi import WebSocket
from utils.subprocess_utils import SubprocessManager

logger = logging.getLogger(__name__)

class ConnectionHandler:
    def __init__(
        self,
        websocket: WebSocket,
        interview_id: str,
        language: str,
        launcher_jar: str,
        config_path: str,
        base_workspace_dir: str
    ):
        self.websocket = websocket
        self.interview_id = interview_id
        self.language = language
        self.launcher_jar = launcher_jar
        self.config_path = config_path
        self.base_workspace_dir = base_workspace_dir
        self.workspace_path = os.path.join(base_workspace_dir, interview_id)
        self.subprocess: Optional[SubprocessManager] = None
        self.initialized = False
        self.next_id = 1

    async def initialize(self):
        try:
            if os.path.exists(self.workspace_path):
                shutil.rmtree(self.workspace_path, ignore_errors=True)
            os.makedirs(self.workspace_path, exist_ok=True)
            self._create_project_files()

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
                "-data", self.workspace_path,
                "--add-modules=ALL-SYSTEM",
                "--add-opens", "java.base/java.util=ALL-UNNAMED",
                "--add-opens", "java.base/java.lang=ALL-UNNAMED"
            ]

            self.subprocess = SubprocessManager(cmd)
            self.subprocess.set_notification_callback(self._handle_notification)
            await self.subprocess.start()

            init_msg = {
                "jsonrpc": "2.0",
                "id": self.next_id,
                "method": "initialize",
                "params": {
                    "processId": None,
                    "rootUri": f"file://{self.workspace_path}",
                    "capabilities": {
                        "textDocument": {
                            "synchronization": {"openClose": True, "change": 2, "save": {"includeText": True}},
                            "completion": {"completionItem": {"snippetSupport": True}},
                            "publishDiagnostics": {"relatedInformation": True}
                        },
                        "workspace": {"didChangeConfiguration": {"dynamicRegistration": True}, "workspaceFolders": True}
                    },
                    "workspaceFolders": [{"uri": f"file://{self.workspace_path}", "name": self.interview_id}]
                }
            }

            self.next_id += 1
            await self.subprocess.send(json.dumps(init_msg))
            response = await self.subprocess.receive(self.next_id - 1, timeout=30.0)
            if response:
                self.initialized = True
                logger.info(f"JDT LS initialized for {self.interview_id}")
                await self.websocket.send_text(response)
                await self.subprocess.send(json.dumps({"jsonrpc": "2.0", "method": "initialized", "params": {}}))
                await self._open_initial_file()
            else:
                raise RuntimeError("No response from JDT LS during initialization")
        except Exception as e:
            logger.error(f"Initialization failed for {self.interview_id}: {str(e)}", exc_info=True)
            raise

    def _create_project_files(self):
        src_path = os.path.join(self.workspace_path, "src")
        os.makedirs(src_path, exist_ok=True)
        java_file = os.path.join(src_path, "Main.java")
        with open(java_file, "w") as f:
            f.write("""public class Main {
    public static void main(String[] args) {
        System.out.println("Hello, World!");
    }
}""")
        project_file = os.path.join(self.workspace_path, ".project")
        with open(project_file, "w") as f:
            f.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<projectDescription>
    <name>{self.interview_id}</name>
    <buildSpec>
        <buildCommand>
            <name>org.eclipse.jdt.core.javabuilder</name>
        </buildCommand>
    </buildSpec>
    <natures>
        <nature>org.eclipse.jdt.core.javanature</nature>
    </natures>
</projectDescription>""")
        classpath_file = os.path.join(self.workspace_path, ".classpath")
        with open(classpath_file, "w") as f:
            f.write("""<?xml version="1.0" encoding="UTF-8"?>
<classpath>
    <classpathentry kind="src" path="src"/>
    <classpathentry kind="con" path="org.eclipse.jdt.launching.JRE_CONTAINER"/>
    <classpathentry kind="output" path="bin"/>
</classpath>""")

    async def _open_initial_file(self):
        did_open_msg = {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": f"file://{self.workspace_path}/src/Main.java",
                    "languageId": "java",
                    "version": 1,
                    "text": open(f"{self.workspace_path}/src/Main.java").read()
                }
            }
        }
        await self.subprocess.send(json.dumps(did_open_msg))

    async def handle_message(self, message_str: str):
        message = json.loads(message_str)
        msg_id = message.get("id")
        method = message.get("method")

        if method == "textDocument/didChange":
            uri = message["params"]["textDocument"]["uri"]
            changes = message["params"]["contentChanges"]
            file_path = uri.replace("file://", "")
            with open(file_path, "r+") as f:
                content = f.read()
                for change in changes:
                    if "range" in change:
                        start = change["range"]["start"]
                        end = change["range"]["end"]
                        lines = content.splitlines()
                        line = lines[start["line"]]
                        new_line = line[:start["character"]] + change["text"] + line[end["character"]:]
                        lines[start["line"]] = new_line
                        content = "\n".join(lines)
                    else:
                        content = change["text"]
                    f.seek(0)
                    f.write(content)
                    f.truncate()
            await self.subprocess.send(message_str)

        elif method == "textDocument/completion":
            await self.subprocess.send(message_str)
            response = await self.subprocess.receive(msg_id, timeout=10.0)
            if response:
                await self.websocket.send_text(response)

        elif method == "shutdown":
            await self.subprocess.send(message_str)
            response = await self.subprocess.receive(msg_id, timeout=5.0)
            if response:
                await self.websocket.send_text(response)
            await self.cleanup()

        else:
            await self.subprocess.send(message_str)
            if msg_id:
                response = await self.subprocess.receive(msg_id, timeout=10.0)
                if response:
                    await self.websocket.send_text(response)

    async def _handle_notification(self, message):
        await self.websocket.send_text(json.dumps(message))

    async def cleanup(self):
        if self.subprocess:
            await self.subprocess.stop()
            shutil.rmtree(self.workspace_path, ignore_errors=True)
            logger.info(f"Cleaned up workspace for {self.interview_id}")