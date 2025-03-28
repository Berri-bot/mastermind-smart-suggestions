import os
import re
import subprocess
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from config import config
from .lsp_manager import LSPManager
import json
import time

logger = logging.getLogger(__name__)

class JavaService:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.src_dir = workspace / "src" / "main" / "java"
        self.initialized = False
        self._setup_project_structure()
        self._initialize_lsp()

    def _setup_project_structure(self):
        """Create standard Maven project structure"""
        self.src_dir.mkdir(parents=True, exist_ok=True)
        
        # Create minimal pom.xml if not exists
        pom_path = self.workspace / "pom.xml"
        if not pom_path.exists():
            pom_content = """<?xml version="1.0" encoding="UTF-8"?>
            <project xmlns="http://maven.apache.org/POM/4.0.0"
                     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                     xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
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

    def _initialize_lsp(self):
        """Initialize the Java LSP connection"""
        try:
            init_params = {
                "processId": os.getpid(),
                "rootUri": f"file://{self.workspace}",
                "capabilities": {
                    "textDocument": {
                        "completion": {
                            "completionItem": {"snippetSupport": True}
                        }
                    }
                },
                "initializationOptions": {
                    "bundles": [],
                    "workspaceFolders": [f"file://{self.workspace}"],
                    "settings": {
                        "java": {
                            "home": str(config.JDK_HOME),
                            "configuration": {
                                "runtimes": [{
                                    "name": "JavaSE-21",
                                    "path": str(config.JDK_HOME),
                                    "default": True
                                }]
                            }
                        }
                    }
                }
            }
            
            response = LSPManager.send_java_request({
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": init_params,
                "id": 1
            })
            
            if response and not response.get("error"):
                self.initialized = True
                LSPManager.send_java_notification({
                    "jsonrpc": "2.0",
                    "method": "initialized",
                    "params": {}
                })
                logger.info(f"Java LSP initialized for workspace: {self.workspace}")
        except Exception as e:
            logger.error(f"Error initializing Java LSP: {str(e)}", exc_info=True)
            raise

    def get_completions(self, uri: str, text: str, line: int, column: int) -> List[Dict]:
        """Get code completions from Java LSP server"""
        if not self.initialized:
            return []
            
        try:
            # Ensure file is in src/main/java
            file_path = self._ensure_proper_location(uri, text)
            
            # Notify LSP of document open
            self._send_did_open(file_path, text)
            
            # Request completions
            return self._request_completions(file_path, line, column)
        except Exception as e:
            logger.error(f"Error getting completions: {str(e)}", exc_info=True)
            return []

    def _ensure_proper_location(self, uri: str, text: str) -> str:
        """Ensure file is in the correct source directory"""
        if uri.startswith("file://"):
            file_path = Path(uri[7:])
        else:
            file_path = Path(uri)
            
        if not file_path.is_relative_to(self.src_dir):
            relative_path = file_path.relative_to(self.workspace) if file_path.is_relative_to(self.workspace) else file_path.name
            new_path = self.src_dir / relative_path
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_text(text)
            return f"file://{new_path}"
        return uri

    def _send_did_open(self, uri: str, text: str):
        """Send didOpen notification to LSP server"""
        LSPManager.send_java_notification({
            "jsonrpc": "2.0",
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

    def _request_completions(self, uri: str, line: int, column: int) -> List[Dict]:
        """Request completions from LSP server"""
        response = LSPManager.send_java_request({
            "jsonrpc": "2.0",
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": column},
                "context": {"triggerKind": 1}
            },
            "id": 2
        })
        
        if not response or "error" in response:
            return []
            
        result = response.get("result", {})
        items = result if isinstance(result, list) else result.get("items", [])
        
        return [{
            "label": item.get("label", ""),
            "kind": item.get("kind", 1),
            "detail": item.get("detail", ""),
            "insertText": item.get("insertText", item.get("label", ""))
        } for item in items]

    def run_code(self, uri: str, text: str) -> Dict[str, str]:
        """Compile and run Java code"""
        try:
            file_path = Path(uri.replace("file://", ""))
            class_name, package = self._parse_class_info(text)
            
            # Create package structure
            class_dir = self.src_dir
            if package:
                class_dir = class_dir.joinpath(*package.split('.'))
                class_dir.mkdir(parents=True, exist_ok=True)
            
            # Write source file
            src_path = class_dir / f"{class_name}.java"
            src_path.write_text(text)
            
            # Compile
            compile_result = subprocess.run(
                [str(config.JDK_HOME / "bin" / "javac"), str(src_path)],
                cwd=str(self.workspace),
                capture_output=True,
                text=True
            )
            
            if compile_result.returncode != 0:
                return {"output": "", "error": compile_result.stderr}
            
            # Run with classpath
            run_cmd = [
                str(config.JDK_HOME / "bin" / "java"),
                "-cp",
                str(self.src_dir),  # Add classpath to src/main/java
                f"{package}.{class_name}" if package else class_name
            ]
            
            run_result = subprocess.run(
                run_cmd,
                cwd=str(self.workspace),
                capture_output=True,
                text=True
            )
            
            return {
                "output": run_result.stdout,
                "error": run_result.stderr if run_result.returncode != 0 else ""
            }
        except Exception as e:
            return {"output": "", "error": str(e)}

    def _parse_class_info(self, text: str) -> Tuple[str, str]:
        package_match = re.search(r'package\s+([a-zA-Z0-9.]+)\s*;', text)
        class_match = re.search(r'(?:public\s+)?class\s+(\w+)', text)
        return (
            class_match.group(1) if class_match else "Main",
            package_match.group(1) if package_match else ""
        )

    def shutdown(self):
        logger.info(f"Shutting down Java service for workspace: {self.workspace}")