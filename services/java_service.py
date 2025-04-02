from pathlib import Path
from typing import List, Dict
from services.lsp_manager import LSPManager
from logger import get_logger
import json

logger = get_logger("java_service")

class JavaService:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.lsp_manager = LSPManager(workspace)
        logger.info(f"JavaService initialized for workspace: {self.workspace}")

    def get_completions(self, uri: str, text: str, line: int, column: int) -> List[Dict]:
        if not self.lsp_manager._initialized:
            logger.error("Java LSP not initialized")
            return []
        try:
            response = self.lsp_manager.send_request({
                "method": "textDocument/completion",
                "params": {"textDocument": {"uri": uri}, "position": {"line": line, "character": column}}
            })
            logger.debug(f"LSP completion response: {json.dumps(response, indent=2)}")
            if not response or "error" in response:
                logger.error(f"Completion failed: {response.get('error', 'No response')}")
                return []
            items = response.get("result", {}).get("items", response.get("result", []))
            completions = [{"label": item["label"], "insertText": item.get("insertText", item["label"])} for item in items]
            logger.info(f"Returning {len(completions)} completions for {uri}")
            return completions
        except Exception as e:
            logger.error(f"Error getting completions: {e}", exc_info=True)
            return []

    def shutdown(self) -> None:
        self.lsp_manager.shutdown()
        logger.info(f"JavaService shut down for workspace: {self.workspace}")