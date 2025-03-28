import os
import shutil
import logging
from pathlib import Path
from typing import Dict, List, Optional
from config import config
from .java_service import JavaService
from .python_service import PythonService

logger = logging.getLogger(__name__)

class DocumentManager:
    def __init__(self):
        self.documents: Dict[str, dict] = {}
        self.services: Dict[str, object] = {}
        logger.info("DocumentManager initialized")

    def get_workspace_path(self, interview_id: str, language: str) -> Path:
        path = config.WORKSPACE_DIR / interview_id / language
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_service(self, interview_id: str, language: str) -> Optional[object]:
        service_key = f"{interview_id}_{language}"
        if service_key not in self.services:
            workspace = self.get_workspace_path(interview_id, language)
            try:
                if language == "java":
                    self.services[service_key] = JavaService(workspace)
                elif language == "python":
                    self.services[service_key] = PythonService(workspace, interview_id)
                else:
                    logger.error(f"[interview={interview_id}] Unsupported language: {language}")
                    return None
            except Exception as e:
                logger.error(f"[interview={interview_id}] Failed to create {language} service: {str(e)}", exc_info=True)
                return None
        return self.services.get(service_key)

    def did_open(self, interview_id: str, uri: str, language_id: str, text: str) -> None:
        try:
            file_path = self._write_file(interview_id, uri, language_id, text)
            self.documents[uri] = {
                "interview_id": interview_id,
                "languageId": language_id,
                "text": text,
                "file_path": file_path
            }
            logger.info(f"[interview={interview_id}] Opened document: {uri}")
            logger.debug(f"[interview={interview_id}] Document content:\n{text}")
        except Exception as e:
            logger.error(f"[interview={interview_id}] Error opening document: {str(e)}", exc_info=True)
            raise

    def did_change(self, interview_id: str, uri: str, text: str) -> None:
        if uri in self.documents:
            self.documents[uri]["text"] = text
            try:
                self._write_file(interview_id, uri, self.documents[uri]["languageId"], text)
                logger.debug(f"[interview={interview_id}] Updated document: {uri} with content:\n{text}")
            except Exception as e:
                logger.error(f"[interview={interview_id}] Error updating document: {str(e)}", exc_info=True)
                raise

    def get_completions(self, interview_id: str, uri: str, line: int, column: int) -> List[dict]:
        if uri not in self.documents:
            logger.error(f"[interview={interview_id}] Document not found: {uri}")
            return []
        doc = self.documents[uri]
        logger.info(f"[interview={interview_id}] Fetching completions for {uri} at line {line}, column {column}")
        logger.debug(f"[interview={interview_id}] Current document content:\n{doc['text']}")
        service = self.get_service(interview_id, doc["languageId"])
        if not service:
            logger.error(f"[interview={interview_id}] No service for language: {doc['languageId']}")
            return []
        try:
            completions = service.get_completions(uri, doc["text"], line, column)
            logger.info(f"[interview={interview_id}] Returning {len(completions)} completions for {uri}")
            return completions
        except Exception as e:
            logger.error(f"[interview={interview_id}] Error getting completions: {str(e)}", exc_info=True)
            return []

    def run_code(self, interview_id: str, uri: str) -> dict:
        if uri not in self.documents:
            logger.error(f"[interview={interview_id}] Document not found: {uri}")
            return {"output": "", "error": "Document not found"}
        doc = self.documents[uri]
        service = self.get_service(interview_id, doc["languageId"])
        if not service:
            logger.error(f"[interview={interview_id}] No service for language: {doc['languageId']}")
            return {"output": "", "error": f"No service for language: {doc['languageId']}"}
        try:
            return service.run_code(uri, doc["text"])
        except Exception as e:
            logger.error(f"[interview={interview_id}] Error running code: {str(e)}", exc_info=True)
            return {"output": "", "error": str(e)}

    def _write_file(self, interview_id: str, uri: str, language_id: str, text: str) -> Path:
        try:
            file_name = Path(uri).name
            workspace = self.get_workspace_path(interview_id, language_id)
            file_path = workspace / file_name
            file_path.write_text(text, encoding="utf-8")
            logger.debug(f"[interview={interview_id}] Wrote file: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"[interview={interview_id}] Error writing file: {str(e)}", exc_info=True)
            raise

    def cleanup_interview(self, interview_id: str) -> None:
        try:
            for key in list(self.services.keys()):
                if key.startswith(f"{interview_id}_"):
                    try:
                        self.services[key].shutdown()
                    except Exception as e:
                        logger.error(f"[interview={interview_id}] Error shutting down service: {str(e)}", exc_info=True)
                    del self.services[key]
            for uri in list(self.documents.keys()):
                if self.documents[uri]["interview_id"] == interview_id:
                    del self.documents[uri]
            interview_dir = config.WORKSPACE_DIR / interview_id
            if interview_dir.exists():
                shutil.rmtree(interview_dir, ignore_errors=True)
            logger.info(f"[interview={interview_id}] Cleaned up resources")
        except Exception as e:
            logger.error(f"[interview={interview_id}] Error during cleanup: {str(e)}", exc_info=True)

    def shutdown(self):
        try:
            for service in self.services.values():
                service.shutdown()
            self.services.clear()
            self.documents.clear()
            logger.info("DocumentManager shutdown complete")
        except Exception as e:
            logger.error(f"Error during DocumentManager shutdown: {str(e)}", exc_info=True)