import subprocess
import re
from pathlib import Path
from typing import List, Dict
from config import config
from services.lsp_manager import LSPManager
from logger import get_logger

logger = get_logger("java_service")

class JavaService:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.src_dir = workspace / "src" / "main" / "java"
        self.initialized = False
        
        self._setup_project_structure()
        self._initialize_lsp()
        logger.info(f"JavaService initialized for workspace: {workspace}")

    def _setup_project_structure(self) -> None:
        """Setup basic Java project structure"""
        self.src_dir.mkdir(parents=True, exist_ok=True)
        
        # Create minimal pom.xml if not exists
        pom_path = self.workspace / "pom.xml"
        if not pom_path.exists():
            pom_content = """<?xml version="1.0" encoding="UTF-8"?>
                                <project xmlns="http://maven.apache.org/POM/4.0.0">
                                    <modelVersion>4.0.0</modelVersion>
                                    <groupId>com.example</groupId>
                                    <artifactId>java-project</artifactId>
                                    <version>1.0-SNAPSHOT</version>
                                    <properties>
                                        <maven.compiler.source>21</maven.compiler.source>
                                        <maven.compiler.target>21</maven.compiler.target>
                                    </properties>
                                </project>"""
            pom_path.write_text(pom_content)
            logger.info(f"Created pom.xml at {pom_path}")

    def _initialize_lsp(self) -> None:
        """Initialize the Java LSP connection"""
        logger.info(f"Initializing Java LSP for workspace: {self.workspace}")
        
        try:
            response = LSPManager.send_java_request({
                "method": "initialize",
                "params": {
                    "processId": None,
                    "rootUri": f"file://{self.workspace}",
                    "capabilities": {
                        "textDocument": {
                            "completion": {
                                "completionItem": {
                                    "snippetSupport": True,
                                    "deprecatedSupport": True,
                                    "preselectSupport": True
                                }
                            }
                        },
                        "workspace": {
                            "configuration": True
                        }
                    },
                    "workspaceFolders": [
                        {"uri": f"file://{self.workspace}", "name": "java_project"}
                    ]
                }
            })
            
            if response and "error" not in response:
                self.initialized = True
                LSPManager.send_java_notification({
                    "method": "initialized",
                    "params": {}
                })
                logger.info("Java LSP initialized successfully")
            else:
                error = response.get("error", {"message": "Unknown error"}) if response else {"message": "No response"}
                logger.error(f"Java LSP initialization failed: {error}")
                raise RuntimeError(f"Java LSP initialization failed: {error['message']}")
        
        except Exception as e:
            logger.error("Failed to initialize Java LSP", exc_info=True)
            raise

    def get_completions(self, uri: str, text: str, line: int, column: int) -> List[Dict]:
        """Get code completions for the given position"""
        if not self.initialized:
            logger.error("Java LSP not initialized")
            return []
        
        file_path = self._ensure_proper_location(uri, text)
        self._send_did_open(file_path, text)
        
        try:
            response = LSPManager.send_java_request({
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": file_path},
                    "position": {"line": line, "character": column}
                }
            })
            
            if not response or "error" in response:
                error = response.get("error", {"message": "No response"}) if response else {"message": "No response"}
                logger.error(f"Completion request failed: {error}")
                return []
            
            result = response.get("result", [])
            items = result.get("items", result) if isinstance(result, dict) else result
            
            return [
                {
                    "label": item["label"],
                    "insertText": item.get("insertText", item["label"]),
                    "kind": item.get("kind", 0),
                    "detail": item.get("detail", "")
                }
                for item in items
            ]
        
        except Exception as e:
            logger.error("Error getting completions", exc_info=True)
            return []

    def _ensure_proper_location(self, uri: str, text: str) -> str:
        file_path = Path(uri.replace("file://", ""))
        if not file_path.is_relative_to(self.src_dir):
            new_path = self.src_dir / file_path.name
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_text(text)
            return f"file://{new_path}"
        return uri

    def _send_did_open(self, uri: str, text: str):
        LSPManager.send_java_notification({
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "java",
                    "version": 1,
                    "text": text
                }
            }
        })

    def run_code(self, uri: str, text: str) -> Dict[str, str]:
        logger.info(f"Running code for {uri}")
        try:
            file_path = Path(uri.replace("file://", ""))
            class_name, _ = self._parse_class_info(text)
            src_path = self.src_dir / f"{class_name}.java"
            src_path.write_text(text)
            
            compile_result = subprocess.run(
                [str(config.JDK_HOME / "bin" / "javac"), str(src_path)],
                cwd=str(self.workspace),
                capture_output=True,
                text=True
            )
            if compile_result.returncode != 0:
                logger.error(f"Compilation failed: {compile_result.stderr}")
                return {"output": "", "error": compile_result.stderr}
            
            run_result = subprocess.run(
                [str(config.JDK_HOME / "bin" / "java"), class_name],
                cwd=str(self.workspace),
                capture_output=True,
                text=True
            )
            logger.info(f"Code executed: output={run_result.stdout}, error={run_result.stderr}")
            return {"output": run_result.stdout, "error": run_result.stderr if run_result.returncode != 0 else ""}
        except Exception as e:
            logger.error(f"Error running code: {str(e)}", exc_info=True)
            return {"output": "", "error": str(e)}

    def _parse_class_info(self, text: str) -> tuple:
        class_match = re.search(r'(?:public\s+)?class\s+(\w+)', text)
        return (class_match.group(1) if class_match else "Main", "")

    def shutdown(self):
        logger.info(f"Shutting down Java service for workspace: {self.workspace}")