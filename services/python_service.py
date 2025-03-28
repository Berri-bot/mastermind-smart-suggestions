import os
import subprocess
import logging
from pathlib import Path
from typing import List, Dict
from .lsp_manager import LSPManager

logger = logging.getLogger(__name__)

class PythonService:
    def __init__(self, workspace: Path, interview_id: str):
        self.workspace = workspace
        self.interview_id = interview_id
        self.initialized = False
        self._initialize_lsp()

    def _initialize_lsp(self):
        try:
            response = LSPManager.send_python_request({
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": f"file://{self.workspace}"
                }
            })
            
            if response and not response.get("error"):
                self.initialized = True
                LSPManager.send_python_notification({
                    "jsonrpc": "2.0",
                    "method": "initialized",
                    "params": {}
                })
                logger.info(f"[interview={self.interview_id}] Python LSP initialized")
        except Exception as e:
            logger.error(f"[interview={self.interview_id}] Error initializing Python LSP: {str(e)}", exc_info=True)

    def get_completions(self, uri: str, text: str, line: int, column: int) -> List[Dict]:
        if not self.initialized:
            return []
            
        try:
            # Notify LSP of document open
            LSPManager.send_python_notification({
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "python",
                        "version": 1,
                        "text": text
                    }
                }
            })
            
            # Request completions
            response = LSPManager.send_python_request({
                "jsonrpc": "2.0",
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": column}
                }
            })
            
            if not response or "result" not in response:
                return []
                
            items = response["result"]
            if isinstance(items, dict):
                items = items.get("items", [])
                
            return [{
                "label": item.get("label", ""),
                "kind": item.get("kind", 1),
                "insertText": item.get("insertText", item.get("label", ""))
            } for item in items]
            
        except Exception as e:
            logger.error(f"[interview={self.interview_id}] Error getting completions: {str(e)}", exc_info=True)
            return []

    def run_code(self, uri: str, text: str) -> Dict[str, str]:
        try:
            file_path = Path(uri.replace("file://", ""))
            file_path.write_text(text)
            
            result = subprocess.run(
                ["python", str(file_path)],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            return {
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else ""
            }
        except subprocess.TimeoutExpired:
            return {"output": "", "error": "Execution timed out"}
        except Exception as e:
            return {"output": "", "error": str(e)}

    def shutdown(self):
        logger.info(f"[interview={self.interview_id}] Shutting down Python service")