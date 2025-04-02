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
        """Get or create workspace path for the interview"""
        path = config.WORKSPACE_DIR / interview_id / language
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_service(self, interview_id: str, language: str) -> Optional[JavaService]:
        """Get language service for the interview"""
        service_key = f"{interview_id}_{language}"
        
        if service_key not in self.services:
            workspace = self.get_workspace_path(interview_id, language)
            
            if language == "java":
                self.services[service_key] = JavaService(workspace)
            else:
                logger.error(f"[interview={interview_id}] Unsupported language: {language}")
                return None
        
        return self.services.get(service_key)

    def did_open(self, interview_id: str, uri: str, language_id: str, text: str) -> None:
        """Handle document open event"""
        file_path = self._write_file(interview_id, uri, language_id, text)
        
        self.documents[uri] = {
            "interview_id": interview_id,
            "languageId": language_id,
            "text": text,
            "file_path": file_path,
            "version": 1
        }
        
        logger.info(f"[interview={interview_id}] Opened document: {uri}")

    def did_change(self, interview_id: str, uri: str, text: str) -> None:
        """Handle document change event"""
        if uri not in self.documents:
            logger.warning(f"[interview={interview_id}] Changed document not found: {uri}")
            return
        
        doc = self.documents[uri]
        doc["text"] = text
        doc["version"] += 1
        
        self._write_file(interview_id, uri, doc["languageId"], text)
        logger.info(f"[interview={interview_id}] Updated document: {uri} (v{doc['version']})")

    def get_completions(self, interview_id: str, uri: str, line: int, column: int) -> List[Dict]:
        """Get code completions for the given position"""
        if uri not in self.documents:
            logger.error(f"[interview={interview_id}] Document not found: {uri}")
            return []
        
        doc = self.documents[uri]
        service = self.get_service(interview_id, doc["languageId"])
        
        if not service:
            logger.error(f"[interview={interview_id}] No service for language: {doc['languageId']}")
            return []
        
        completions = service.get_completions(uri, doc["text"], line, column)
        logger.info(f"[interview={interview_id}] Returning {len(completions)} completions for {uri}")
        return completions

    def run_code(self, interview_id: str, uri: str) -> Dict[str, str]:
        """Run code from the given document"""
        if uri not in self.documents:
            logger.error(f"[interview={interview_id}] Document not found: {uri}")
            return {"output": "", "error": "Document not found"}
        
        doc = self.documents[uri]
        service = self.get_service(interview_id, doc["languageId"])
        
        if not service:
            logger.error(f"[interview={interview_id}] No service for language: {doc['languageId']}")
            return {"output": "", "error": f"No service for language: {doc['languageId']}"}
        
        return service.run_code(uri, doc["text"])

    def _write_file(self, interview_id: str, uri: str, language_id: str, text: str) -> Path:
        """Write document content to workspace file"""
        file_name = Path(uri).name
        workspace = self.get_workspace_path(interview_id, language_id)
        file_path = workspace / file_name
        
        file_path.write_text(text, encoding="utf-8")
        logger.debug(f"[interview={interview_id}] Wrote file: {file_path}")
        return file_path

    def cleanup_interview(self, interview_id: str) -> None:
        """Clean up resources for the interview"""
        # Clean up services
        for key in list(self.services.keys()):
            if key.startswith(f"{interview_id}_"):
                self.services[key].shutdown()
                del self.services[key]
        
        # Clean up documents
        for uri in list(self.documents.keys()):
            if self.documents[uri]["interview_id"] == interview_id:
                del self.documents[uri]
        
        logger.info(f"[interview={interview_id}] Cleaned up resources")

    def shutdown(self) -> None:
        """Shutdown all document manager resources"""
        # Shutdown all services
        for service in self.services.values():
            service.shutdown()
        
        self.services.clear()
        self.documents.clear()
        logger.info("DocumentManager shutdown complete")