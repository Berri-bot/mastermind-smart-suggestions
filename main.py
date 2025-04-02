from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from services.document_manager import DocumentManager
from services.lsp_manager import LSPManager
from config import config
from logger import get_logger, setup_logging
import json
import os
from typing import Dict, Any

# Setup logging
setup_logging(str(config.LOG_FILE))
logger = get_logger("main")

app = FastAPI(title="Code Completion Service")
manager = DocumentManager()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    """Initialize application services"""
    logger.info("Starting application...")
    try:
        # Validate configuration
        config.validate_java()
        
        # Initialize LSP servers
        LSPManager.initialize_servers()
        
        logger.info("Application startup completed successfully")
    except Exception as e:
        logger.error("Application startup failed", exc_info=True)
        raise

@app.on_event("shutdown")
async def shutdown():
    """Cleanup application resources"""
    logger.info("Shutting down application...")
    try:
        LSPManager.shutdown()
        manager.shutdown()
        logger.info("Application shutdown completed")
    except Exception as e:
        logger.error("Error during application shutdown", exc_info=True)

@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint"""
    return {"status": "healthy"}

async def process_message(websocket: WebSocket, message: Dict[str, Any], interview_id: str) -> None:
    """Process incoming WebSocket messages"""
    logger.info(f"[interview={interview_id}] Processing message: {json.dumps(message)}")
    
    try:
        # Validate JSON-RPC message
        if message.get("jsonrpc") != "2.0":
            raise ValueError("Invalid JSON-RPC version")
        
        if "method" not in message:
            raise ValueError("Missing 'method' in message")
        
        method = message["method"]
        params = message.get("params", {})
        message_id = message.get("id")
        
        response = {"jsonrpc": "2.0", "id": message_id}
        
        # Process different methods
        if method == "textDocument/didOpen":
            doc = params["textDocument"]
            manager.did_open(
                interview_id,
                doc["uri"],
                doc["languageId"],
                doc["text"]
            )
            response["result"] = {"status": "document_opened"}
        
        elif method == "textDocument/didChange":
            doc = params["textDocument"]
            changes = params.get("contentChanges", [])
            
            if changes:
                manager.did_change(
                    interview_id,
                    doc["uri"],
                    changes[0]["text"]
                )
                response["result"] = {"status": "document_updated"}
            else:
                response["result"] = {"status": "no_changes"}
        
        elif method == "textDocument/completion":
            doc = params["textDocument"]
            position = params["position"]
            
            completions = manager.get_completions(
                interview_id,
                doc["uri"],
                position["line"],
                position["character"]
            )
            response["result"] = completions
        
        elif method == "textDocument/run":
            doc = params["textDocument"]
            result = manager.run_code(interview_id, doc["uri"])
            response["result"] = result
        
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        await websocket.send_text(json.dumps(response))
        logger.debug(f"[interview={interview_id}] Sent response: {json.dumps(response)}")
    
    except Exception as e:
        error_response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32602,
                "message": str(e)
            }
        }
        await websocket.send_text(json.dumps(error_response))
        logger.error(f"[interview={interview_id}] Error processing message: {str(e)}", exc_info=True)

@app.websocket("/ws/{interview_id}")
async def websocket_endpoint(websocket: WebSocket, interview_id: str):
    """WebSocket endpoint for code completion service"""
    await websocket.accept()
    logger.info(f"[interview={interview_id}] WebSocket connection opened")
    
    try:
        while True:
            data = await websocket.receive_text()
            logger.debug(f"[interview={interview_id}] Received message: {data[:200]}...")
            
            try:
                message = json.loads(data)
                await process_message(websocket, message, interview_id)
            except json.JSONDecodeError as e:
                error_msg = f"Invalid JSON: {str(e)}"
                await websocket.send_text(json.dumps({
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": error_msg}
                }))
                logger.error(f"[interview={interview_id}] JSON decode error: {error_msg}")
    
    except WebSocketDisconnect:
        logger.info(f"[interview={interview_id}] Client disconnected")
    except Exception as e:
        logger.error(f"[interview={interview_id}] WebSocket error: {str(e)}", exc_info=True)
    finally:
        manager.cleanup_interview(interview_id)
        logger.info(f"[interview={interview_id}] Resources cleaned up")