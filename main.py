from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from services.document_manager import DocumentManager
from services.lsp_manager import LSPManager
from config import config
import logging
import json
import uvicorn
from typing import Dict, Any, List

class InterviewFormatter(logging.Formatter):
    def format(self, record):
        if not hasattr(record, 'interview_id'):
            record.interview_id = 'system'
        return super().format(record)

# Configure logging
handler = logging.StreamHandler()
handler.setFormatter(InterviewFormatter("%(asctime)s [%(levelname)s] [interview=%(interview_id)s] %(message)s"))
file_handler = logging.FileHandler(config.LOG_FILE)
file_handler.setFormatter(InterviewFormatter("%(asctime)s [%(levelname)s] [interview=%(interview_id)s] %(message)s"))

logging.getLogger('').handlers = [handler, file_handler]
logging.getLogger('').setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)

app = FastAPI()
manager = DocumentManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    logger.info("Starting application...")
    try:
        config.validate()
        LSPManager.initialize_servers()
        logger.info("Application startup complete")
    except Exception as e:
        logger.error(f"Startup failed: {str(e)}", exc_info=True)
        raise

@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down application...")
    try:
        manager.shutdown()
        LSPManager.shutdown()
    except Exception as e:
        logger.error(f"Shutdown errore: {str(e)}", exc_info=True)

async def process_message(websocket: WebSocket, message: Dict[str, Any], interview_id: str) -> None:
    try:
        if not isinstance(message, dict):
            raise ValueError("Message must be a JSON object")
        if message.get("jsonrpc") != "2.0":
            raise ValueError("Invalid JSON-RPC version. Must be '2.0'")
        if "method" not in message:
            raise ValueError("Missing required field: 'method'")

        method = message["method"]
        params = message.get("params", {})
        message_id = message.get("id")

        if method == "textDocument/didOpen":
            if "textDocument" not in params:
                raise ValueError("Missing 'textDocument' in params")
            text_doc = params["textDocument"]
            required = ["uri", "languageId", "text"]
            if not all(field in text_doc for field in required):
                raise ValueError(f"Missing required fields in textDocument: {required}")
            manager.did_open(interview_id, text_doc["uri"], text_doc["languageId"], text_doc["text"])
            response = {"jsonrpc": "2.0", "id": message_id, "result": {"status": "opened"}}

        elif method == "textDocument/didChange":
            changes = params.get("contentChanges", [])
            if changes:
                text = changes[0]["text"]
                manager.did_change(interview_id, params["textDocument"]["uri"], text)
                response = {"jsonrpc": "2.0", "id": message_id, "result": {"status": "updated"}}
            else:
                response = {"jsonrpc": "2.0", "id": message_id, "result": {"status": "no_changes"}}

        elif method == "textDocument/completion":
            if "textDocument" not in params or "position" not in params:
                raise ValueError("Missing required fields in params")
            uri = params["textDocument"].get("uri")
            position = params["position"]
            if not uri or not all(k in position for k in ["line", "character"]):
                raise ValueError("Missing or invalid parameters")
            completions = manager.get_completions(interview_id, uri, position["line"], position["character"])
            response = {"jsonrpc": "2.0", "id": message_id, "result": completions}

        elif method == "textDocument/run":
            if "textDocument" not in params or not params["textDocument"].get("uri"):
                raise ValueError("Missing textDocument.uri in params")
            uri = params["textDocument"]["uri"]
            result = manager.run_code(interview_id, uri)
            response = {"jsonrpc": "2.0", "id": message_id, "result": result}

        else:
            raise ValueError(f"Unknown method: {method}")

        await websocket.send_text(json.dumps(response))

    except Exception as e:
        logger.error(f"[interview={interview_id}] Error processing message: {str(e)}", exc_info=True)
        error_response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {"code": -32602, "message": str(e)}
        }
        await websocket.send_text(json.dumps(error_response))

@app.websocket("/ws/{interview_id}")
async def websocket_endpoint(websocket: WebSocket, interview_id: str):
    await websocket.accept()
    logger.info(f"[interview={interview_id}] WebSocket connection opened")
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            if isinstance(payload, list):
                for message in payload:
                    await process_message(websocket, message, interview_id)
            else:
                await process_message(websocket, payload, interview_id)
    except WebSocketDisconnect:
        logger.info(f"[interview={interview_id}] Client disconnected")
    except Exception as e:
        logger.error(f"[interview={interview_id}] WebSocket error: {str(e)}", exc_info=True)
    finally:
        manager.cleanup_interview(interview_id)  # Removed await
        logger.info(f"[interview={interview_id}] Cleaned up resources")