from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from services.document_manager import DocumentManager
from services.lsp_manager import LSPManager
from config import config
from logger import get_logger, setup_logging
import json

setup_logging()
logger = get_logger("main")

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
    config.validate()
    LSPManager.initialize_servers()

@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down application...")
    LSPManager.shutdown()
    manager.shutdown()

async def process_message(websocket: WebSocket, message: dict, interview_id: str):
    logger.info(f"[interview={interview_id}] Processing message: {json.dumps(message)}")
    try:
        if message.get("jsonrpc") != "2.0":
            raise ValueError("Invalid JSON-RPC version")
        if "method" not in message:
            raise ValueError("Missing 'method'")
        
        method = message["method"]
        params = message.get("params", {})
        message_id = message.get("id")

        response = {"jsonrpc": "2.0", "id": message_id}

        if method == "textDocument/didOpen":
            manager.did_open(interview_id, params["textDocument"]["uri"], 
                           params["textDocument"]["languageId"], 
                           params["textDocument"]["text"])
            response["result"] = {"status": "opened"}

        elif method == "textDocument/didChange":
            changes = params.get("contentChanges", [])
            if changes:
                manager.did_change(interview_id, params["textDocument"]["uri"], changes[0]["text"])
                response["result"] = {"status": "updated"}
            else:
                response["result"] = {"status": "no_changes"}

        elif method == "textDocument/completion":
            completions = manager.get_completions(interview_id, params["textDocument"]["uri"], 
                                                params["position"]["line"], 
                                                params["position"]["character"])
            response["result"] = completions

        elif method == "textDocument/run":
            result = manager.run_code(interview_id, params["textDocument"]["uri"])
            response["result"] = result

        else:
            raise ValueError(f"Unknown method: {method}")

        await websocket.send_text(json.dumps(response))
        logger.info(f"[interview={interview_id}] Sent response: {json.dumps(response)}")

    except Exception as e:
        error_response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {"code": -32602, "message": str(e)}
        }
        await websocket.send_text(json.dumps(error_response))
        logger.error(f"[interview={interview_id}] Error processing message: {str(e)}", exc_info=True)

@app.websocket("/ws/{interview_id}")
async def websocket_endpoint(websocket: WebSocket, interview_id: str):
    await websocket.accept()
    logger.info(f"[interview={interview_id}] WebSocket connection opened")
    try:
        while True:
            data = await websocket.receive_text()
            logger.debug(f"[interview={interview_id}] Received: {data}")
            message = json.loads(data)
            await process_message(websocket, message, interview_id)
    except WebSocketDisconnect:
        logger.info(f"[interview={interview_id}] Client disconnected")
    except Exception as e:
        logger.error(f"[interview={interview_id}] WebSocket error: {str(e)}", exc_info=True)
    finally:
        manager.cleanup_interview(interview_id)