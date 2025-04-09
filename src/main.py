from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from connection import ConnectionHandler
import asyncio
import logging
import signal
import os
import glob

from logger import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

jdtls_base_path = "/app/jdtls"
base_workspace_dir = os.getenv("WORKSPACE_DIR", "/workspaces")

def get_jdtls_paths(base_path: str):
    jar_pattern = os.path.join(base_path, "plugins", "org.eclipse.equinox.launcher_*.jar")
    jar_files = glob.glob(jar_pattern)
    if not jar_files:
        raise FileNotFoundError(f"No JAR file found matching {jar_pattern}")
    launcher_jar = jar_files[0]
    config_path = os.path.join(base_path, "config_linux")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config directory not found at {config_path}")
    return launcher_jar, config_path

launcher_jar, config_path = get_jdtls_paths(jdtls_base_path)

@app.websocket("/ws/{interviewId}")
async def websocket_endpoint(websocket: WebSocket, interviewId: str, language: str = Query(...)):
    await websocket.accept()
    logger.info(f"WebSocket connected for interviewId={interviewId}, language={language}")

    handler = ConnectionHandler(
        websocket=websocket,
        interview_id=interviewId,
        language=language,
        launcher_jar=launcher_jar,
        config_path=config_path,
        base_workspace_dir=base_workspace_dir
    )

    try:
        await handler.initialize()
        logger.info(f"Initialization complete for {interviewId}")
        while True:
            message = await websocket.receive_text()
            logger.debug(f"Received message for {interviewId}: {message[:200]}...")
            await handler.handle_message(message)
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for {interviewId}")
    except Exception as e:
        logger.error(f"WebSocket error for {interviewId}: {str(e)}", exc_info=True)
    finally:
        logger.info(f"Starting cleanup for {interviewId}")
        await handler.cleanup()
        logger.info(f"Cleanup complete for {interviewId}")

def handle_signal(signum, frame):
    logger.info(f"Received signal {signum}, shutting down")
    asyncio.get_event_loop().stop()

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)