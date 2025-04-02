from pathlib import Path
from typing import Dict, List, Optional
from config import config
from services.java_service import JavaService
from logger import get_logger

logger = get_logger("document_manager")

class DocumentManager:
    def __init__(self):
        self.documents: Dict[str, Dict] = {}
        self.services: Dict[str, JavaService] = {}
        logger.info("DocumentManager initialized")

    def get_workspace_path(self, interview_id: str, language: str) -> Path:
        path = config.WORKSPACE_DIR / interview_id / language
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_service(self, interview_id: str, language: str) -> Optional[JavaService]:
        service_key = f"{interview_id}_{language}"
        if service_key not in self.services:
            workspace = self.get_workspace_path(interview_id, language)
            if language == "java":
                self.services[service_key] = JavaService(workspace)
            else:
                logger.error(f"Unsupported language: {language}")
                return None
        return self.services.get(service_key)

    def did_open(self, interview_id: str, uri: str, language_id: str, text: str) -> None:
        file_path = self._write_file(interview_id, uri, language_id, text)
        self.documents[uri] = {
            "interview_id": interview_id,
            "languageId": language_id,
            "text": text,
            "file_path": file_path,
            "version": 1
        }
        service = self.get_service(interview_id, language_id)
        if service:
            service.lsp_manager.send_notification({
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {"uri": uri, "languageId": language_id, "version": 1, "text": text}
                }
            })
        logger.info(f"Opened document: {uri}")

    def did_change(self, interview_id: str, uri: str, text: str) -> None:
        if uri not in self.documents:
            logger.error(f"Document not found: {uri}")
            return
        self.documents[uri]["text"] = text
        self.documents[uri]["version"] += 1
        file_path = self._write_file(interview_id, uri, self.documents[uri]["languageId"], text)
        service = self.get_service(interview_id, self.documents[uri]["languageId"])
        if service:
            service.lsp_manager.send_notification({
                "method": "textDocument/didChange",
                "params": {
                    "textDocument": {"uri": uri, "version": self.documents[uri]["version"]},
                    "contentChanges": [{"text": text}]
                }
            })
        logger.info(f"Updated document: {uri}")

    def get_completions(self, interview_id: str, uri: str, line: int, column: int) -> List[Dict]:
        if uri not in self.documents:
            logger.error(f"Document not found: {uri}")
            return []
        doc = self.documents[uri]
        service = self.get_service(interview_id, doc["languageId"])
        if not service:
            return []
        return service.get_completions(uri, doc["text"], line, column)

    def run_code(self, interview_id: str, uri: str) -> Dict:
        # Placeholder for code execution (not implemented in your original)
        logger.info(f"Run code requested for {uri} (not implemented)")
        return {"status": "not_implemented"}

    def _write_file(self, interview_id: str, uri: str, language_id: str, text: str) -> Path:
        file_name = Path(uri).name
        workspace = self.get_workspace_path(interview_id, language_id)
        file_path = workspace / file_name
        file_path.write_text(text, encoding="utf-8")
        return file_path

    def cleanup_interview(self, interview_id: str) -> None:
        for key in list(self.services.keys()):
            if key.startswith(f"{interview_id}_"):
                self.services[key].shutdown()
                del self.services[key]
        for uri in list(self.documents.keys()):
            if self.documents[uri]["interview_id"] == interview_id:
                del self.documents[uri]
        logger.info(f"Cleaned up resources for interview: {interview_id}")

    def shutdown(self) -> None:
        for service in self.services.values():
            service.shutdown()
        self.services.clear()
        self.documents.clear()
        logger.info("DocumentManager shutdown complete")