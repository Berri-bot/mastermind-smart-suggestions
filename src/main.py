from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from connection import ConnectionHandler
import asyncio
import logging
import signal
import os
import glob
import traceback
import subprocess

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
active_connections = {}

def get_jdtls_paths(base_path: str):
    try:
        logger.debug(f"Checking JDT LS base path: {base_path}")
        if not os.path.exists(base_path):
            logger.error(f"JDT LS base path does not exist: {base_path}")
            raise FileNotFoundError(f"JDT LS base path does not exist: {base_path}")
        
        jar_pattern = os.path.join(base_path, "plugins", "org.eclipse.equinox.launcher_*.jar")
        logger.debug(f"Looking for JAR files with pattern: {jar_pattern}")
        jar_files = glob.glob(jar_pattern)
        if not jar_files:
            logger.error(f"No JAR file found matching {jar_pattern}. Listing directory contents:")
            if os.path.exists(os.path.join(base_path, "plugins")):
                logger.error(f"Contents of {base_path}/plugins: {os.listdir(os.path.join(base_path, 'plugins'))}")
            else:
                logger.error(f"Plugins directory not found at {base_path}/plugins")
            raise FileNotFoundError(f"No JAR file found matching {jar_pattern}")
        launcher_jar = jar_files[0]
        logger.debug(f"Found launcher JAR: {launcher_jar}")

        config_path = os.path.join(base_path, "config_linux")
        logger.debug(f"Checking config path: {config_path}")
        if not os.path.exists(config_path):
            logger.error(f"Config directory not found at {config_path}")
            raise FileNotFoundError(f"Config directory not found at {config_path}")
        
        return launcher_jar, config_path
    except Exception as e:
        logger.error(f"Error in get_jdtls_paths: {str(e)}\n{traceback.format_exc()}")
        raise

logger.debug(f"Using jdtls_base_path={jdtls_base_path}, base_workspace_dir={base_workspace_dir}")
if not os.path.exists(base_workspace_dir):
    logger.warning(f"Base workspace directory does not exist, creating: {base_workspace_dir}")
    os.makedirs(base_workspace_dir, exist_ok=True)
try:
    java_version = subprocess.check_output(["java", "-version"], stderr=subprocess.STDOUT).decode()
    logger.debug(f"Java version: {java_version.strip()}")
except subprocess.CalledProcessError as e:
    logger.error(f"Java not found or failed to run: {str(e)}\n{traceback.format_exc()}")
    raise RuntimeError("Java is not installed or not executable")
except FileNotFoundError:
    logger.error("Java command not found in PATH\n{traceback.format_exc()}")
    raise RuntimeError("Java is not installed")

launcher_jar, config_path = get_jdtls_paths(jdtls_base_path)

@app.get("/")
async def health_check():
    logger.debug(f"Health check requested, active connections: {len(active_connections)}")
    return {"status": "ok", "connections": len(active_connections)}

@app.websocket("/ws/{interviewId}")
async def websocket_endpoint(websocket: WebSocket, interviewId: str, language: str = Query(...)):
    try:
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
        
        active_connections[interviewId] = handler
        logger.debug(f"Added handler to active_connections for {interviewId}")

        await handler.initialize()
        logger.info(f"Initialization complete for {interviewId}")
        while True:
            message = await websocket.receive_text()
            logger.debug(f"Received message for {interviewId}: {message[:200]}...")
            await handler.handle_message(message)
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for {interviewId}")
    except Exception as e:
        logger.error(f"WebSocket error for {interviewId}: {str(e)}\n{traceback.format_exc()}")
    finally:
        try:
            logger.info(f"Starting cleanup for {interviewId}")
            await handler.cleanup()
            if interviewId in active_connections:
                del active_connections[interviewId]
                logger.debug(f"Removed {interviewId} from active_connections")
            logger.info(f"Cleanup complete for {interviewId}")
        except Exception as e:
            logger.error(f"Error during cleanup for {interviewId}: {str(e)}\n{traceback.format_exc()}")

async def shutdown():
    logger.info("Shutting down gracefully...")
    for interview_id, handler in list(active_connections.items()):
        try:
            await handler.cleanup()
            logger.debug(f"Cleaned up connection {interview_id}")
        except Exception as e:
            logger.error(f"Error cleaning up {interview_id}: {str(e)}\n{traceback.format_exc()}")
    logger.info("All connections cleaned up")

def handle_signal(signum, frame):
    logger.info(f"Received signal {signum}, initiating graceful shutdown")
    asyncio.create_task(shutdown())

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)