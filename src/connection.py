import json
import logging
import os
import shutil
from typing import Optional
from fastapi import WebSocket
from utils.subprocess_utils import SubprocessManager
from logger import setup_logging
import traceback

setup_logging()
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
        self.workspace_path = os.path.join(self.base_workspace_dir, self.interview_id)
        self.subprocess: Optional[SubprocessManager] = None
        self.initialized = False
        self.next_id = 1
        self.open_documents = set()
        logger.debug(f"Initialized ConnectionHandler for interview_id={interview_id} with workspace_path={self.workspace_path}")

    async def initialize(self):
        try:
            logger.debug(f"Checking workspace path: {self.workspace_path}")
            os.makedirs(self.workspace_path, exist_ok=True)
            logger.debug(f"Created workspace directory: {self.workspace_path}")
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
            logger.debug(f"Starting JDT LS with command: {' '.join(cmd)}")

            self.subprocess = SubprocessManager(cmd)
            self.subprocess.set_notification_callback(self._handle_notification)
            await self.subprocess.start()
            logger.info(f"JDT LS process started for {self.interview_id} with workspace {self.workspace_path}")

            init_msg = {
                "jsonrpc": "2.0",
                "id": self.next_id,
                "method": "initialize",
                "params": {
                    "processId": None,
                    "rootUri": f"file://{self.workspace_path}",
                    "capabilities": {
                        "textDocument": {
                            "synchronization": {
                                "openClose": True,
                                "change": 2,
                                "save": {"includeText": True}
                            },
                            "completion": {"completionItem": {"snippetSupport": True}},
                            "publishDiagnostics": {"relatedInformation": True}
                        },
                        "workspace": {
                            "didChangeConfiguration": {"dynamicRegistration": True},
                            "workspaceFolders": True
                        }
                    },
                    "workspaceFolders": [
                        {"uri": f"file://{self.workspace_path}", "name": self.interview_id}
                    ]
                }
            }
            self.next_id += 1
            logger.debug(f"Sending initialize message: {json.dumps(init_msg)[:200]}...")
            await self.subprocess.send(json.dumps(init_msg))
            response = await self.subprocess.receive(init_msg["id"], timeout=300.0)  # Match SubprocessManager timeout
            if response:
                self.initialized = True
                logger.info(f"JDT LS initialized successfully for {self.interview_id}")
                await self.websocket.send_text(response)
                await self.subprocess.send(json.dumps({"jsonrpc": "2.0", "method": "initialized", "params": {}}))

                did_open_msg = {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didOpen",
                    "params": {
                        "textDocument": {
                            "uri": f"file://{self.workspace_path}/src/Main.java",
                            "languageId": "java",
                            "version": 1,
                            "text": open(f"{self.workspace_path}/src/Main.java", "r").read()
                        }
                    }
                }
                logger.debug(f"Sending didOpen message: {json.dumps(did_open_msg)[:200]}...")
                await self.subprocess.send(json.dumps(did_open_msg))
            else:
                logger.error(f"Failed to initialize JDT LS for {self.interview_id}: No response received after 300s")
                raise RuntimeError("JDT LS initialization failed: No response")
        except Exception as e:
            logger.error(f"Error in initialize for {self.interview_id}: {str(e)}\n{traceback.format_exc()}")
            raise

    def _create_project_files(self):
        try:
            src_path = os.path.join(self.workspace_path, "src")
            logger.debug(f"Creating source directory: {src_path}")
            os.makedirs(src_path, exist_ok=True)
            java_file = os.path.join(src_path, "Main.java")
            if not os.path.exists(java_file):
                with open(java_file, "w") as f:
                    f.write("""public class Main {
    public static void main(String[] args) {
        System.out.println("Hello, World!");
    }
}
""")
                logger.debug(f"Created {java_file}")

            project_file = os.path.join(self.workspace_path, ".project")
            unique_project_name = f"{self.interview_id}_{os.urandom(4).hex()}"
            with open(project_file, "w") as f:
                f.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<projectDescription>
    <name>{unique_project_name}</name>
    <comment></comment>
    <projects></projects>
    <buildSpec>
        <buildCommand>
            <name>org.eclipse.jdt.core.javabuilder</name>
            <arguments></arguments>
        </buildCommand>
    </buildSpec>
    <natures>
        <nature>org.eclipse.jdt.core.javanature</nature>
    </natures>
</projectDescription>
""")
                logger.debug(f"Created {project_file}")

            classpath_file = os.path.join(self.workspace_path, ".classpath")
            with open(classpath_file, "w") as f:
                f.write("""<?xml version="1.0" encoding="UTF-8"?>
<classpath>
    <classpathentry kind="src" path="src"/>
    <classpathentry kind="con" path="org.eclipse.jdt.launching.JRE_CONTAINER"/>
    <classpathentry kind="output" path="bin"/>
</classpath>
""")
                logger.debug(f"Created {classpath_file}")
        except Exception as e:
            logger.error(f"Error creating project files for {self.interview_id}: {str(e)}\n{traceback.format_exc()}")
            raise

    async def _handle_notification(self, message):
        try:
            logger.debug(f"Notification from {self.interview_id}: {json.dumps(message)[:200]}...")
            if message.get("method") == "textDocument/publishDiagnostics":
                logger.info(f"Diagnostics for {message['params']['uri']}: {message['params']['diagnostics']}")
            elif message.get("method") == "window/logMessage":
                logger.info(f"JDT LS log: {message['params']['message']}")
            await self.websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"Error handling notification for {self.interview_id}: {str(e)}\n{traceback.format_exc()}")

    async def handle_message(self, message_str: str):
        try:
            message = json.loads(message_str)
            logger.debug(f"Processing message for {self.interview_id}: {message_str[:200]}...")
            if message.get("jsonrpc") != "2.0":
                logger.warning(f"Invalid JSON-RPC version for {self.interview_id}")
                await self.send_error(None, -32600, "Invalid Request")
                return

            if not self.initialized and message.get("method") != "initialize":
                logger.warning(f"Server not initialized for {self.interview_id}")
                await self.send_error(message.get("id"), -32002, "Server not initialized")
                return

            method = message.get("method")
            msg_id = message.get("id")

            if method == "textDocument/didOpen":
                uri = message["params"]["textDocument"]["uri"]
                self.open_documents.add(uri)
                logger.info(f"Document opened: {uri}")

            elif method == "textDocument/didChange":
                uri = message["params"]["textDocument"]["uri"]
                version = message["params"]["textDocument"].get("version")
                changes = message["params"]["contentChanges"]
                logger.info(f"Applying changes to {uri} (version {version}): {json.dumps(changes)[:200]}...")
                if changes and "text" in changes[0]:
                    file_path = uri.replace("file://", "")
                    with open(file_path, "w") as f:
                        f.write(changes[0]["text"])
                    logger.debug(f"Updated file content at {file_path}")

            elif method == "textDocument/didClose":
                uri = message["params"]["textDocument"]["uri"]
                self.open_documents.discard(uri)
                logger.info(f"Document closed: {uri}")
                if not self.open_documents:
                    await self.cleanup()

            elif method == "textDocument/completion":
                logger.info(f"Completion request received at position: {message['params']['position']} for {message['params']['textDocument']['uri']}")

            elif method == "exit":
                logger.info(f"Exit requested for {self.interview_id}")
                await self.cleanup()
                return

            logger.debug(f"Forwarding message to JDT LS: {message_str[:200]}...")
            await self.subprocess.send(message_str)
            if msg_id is not None:
                logger.debug(f"Awaiting response for ID {msg_id}")
                response = await self.subprocess.receive(msg_id, timeout=15.0)
                if response:
                    logger.debug(f"Sending response for ID {msg_id} to client: {response[:200]}...")
                    await self.websocket.send_text(response)
                else:
                    logger.warning(f"No response received for ID {msg_id} within 15s timeout")
                    await self.send_error(msg_id, -32603, "No response from JDT LS")

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for {self.interview_id}: {str(e)} - Message: {message_str[:200]}\n{traceback.format_exc()}")
            await self.send_error(None, -32700, f"Parse error: {str(e)}")
        except Exception as e:
            logger.error(f"Message handling error for {self.interview_id}: {str(e)} - Message: {message_str[:200]}\n{traceback.format_exc()}")
            await self.send_error(msg_id, -32603, f"Internal error: {str(e)}")

    async def send_error(self, msg_id, code: int, message: str):
        try:
            error = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": code, "message": message}
            }
            logger.error(f"Sending error for {self.interview_id}: {message}\n{traceback.format_exc()}")
            await self.websocket.send_text(json.dumps(error))
        except Exception as e:
            logger.error(f"Error sending error message for {self.interview_id}: {str(e)}\n{traceback.format_exc()}")

    async def cleanup(self):
        try:
            if self.subprocess and self.initialized:
                logger.info(f"Initiating shutdown for {self.interview_id}")
                shutdown_msg = {"jsonrpc": "2.0", "id": self.next_id, "method": "shutdown"}
                self.next_id += 1
                await self.subprocess.send(json.dumps(shutdown_msg))
                response = await self.subprocess.receive(shutdown_msg["id"], timeout=5.0)
                if response:
                    logger.debug(f"Shutdown response: {response}")
                await self.subprocess.send(json.dumps({"jsonrpc": "2.0", "method": "exit"}))
                await self.subprocess.stop()
                self.subprocess = None
                self.initialized = False

            if os.path.exists(self.workspace_path):
                shutil.rmtree(self.workspace_path, ignore_errors=True)
                logger.info(f"Workspace directory removed: {self.workspace_path}")
        except Exception as e:
            logger.error(f"Error in cleanup for {self.interview_id}: {str(e)}\n{traceback.format_exc()}")