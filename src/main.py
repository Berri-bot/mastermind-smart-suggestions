import os
import glob
import subprocess
import logging
from typing import Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from connection import ConnectionHandler
from logger import setup_logging
import importlib

app = FastAPI()
active_connections: Dict[str, ConnectionHandler] = {}

setup_logging()
logger = logging.getLogger(__name__)

# Container paths (consistent with Dockerfile)
jdtls_base_path = "/app/jdtls"
base_workspace_dir = "/workspaces"

logger.debug(f"Using jdtls_base_path={jdtls_base_path}, base_workspace_dir={base_workspace_dir}")

def get_jdtls_paths():
    logger.debug(f"Checking JDT LS base path: {jdtls_base_path}")
    launcher_pattern = os.path.join(jdtls_base_path, "plugins", "org.eclipse.equinox.launcher_*.jar")
    logger.debug(f"Looking for JAR files with pattern: {launcher_pattern}")
    launcher_jars = glob.glob(launcher_pattern)
    if not launcher_jars:
        raise FileNotFoundError(f"No launcher JAR found in {launcher_pattern}")
    launcher_jar = launcher_jars[0]
    logger.debug(f"Found launcher JAR: {launcher_jar}")
    config_path = os.path.join(jdtls_base_path, "config_linux")
    logger.debug(f"Checking config path: {config_path}")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config directory not found: {config_path}")
    return launcher_jar, config_path

launcher_jar, config_path = get_jdtls_paths()

try:
    java_version = subprocess.check_output(["java", "-version"], stderr=subprocess.STDOUT).decode().strip()
    logger.debug(f"Java version: {java_version}")
except subprocess.CalledProcessError as e:
    logger.error(f"Failed to get Java version: {e.output.decode()}")
    raise

@app.get("/")
async def health_check():
    logger.debug(f"Health check requested, active connections: {len(active_connections)}")
    return {"status": "healthy", "active_connections": len(active_connections)}

@app.websocket("/ws/{interview_id}")
async def websocket_endpoint(websocket: WebSocket, interview_id: str, language: str = "java"):
    await websocket.accept()
    logger.info(f"WebSocket connected for interviewId={interview_id}, language={language}")
    handler = ConnectionHandler(
        websocket=websocket,
        interview_id=interview_id,
        language=language,
        launcher_jar=launcher_jar,
        config_path=config_path,
        base_workspace_dir=base_workspace_dir
    )
    active_connections[interview_id] = handler
    logger.debug(f"Added handler to active_connections for {interview_id}")
    try:
        await handler.initialize()
        while True:
            message = await websocket.receive_text()
            await handler.handle_message(message)
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for {interview_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {interview_id}: {str(e)}\n{importlib.import_module('traceback').format_exc()}")
        await websocket.send_text(f'{{"error": "{str(e)}"}}')
    finally:
        logger.info(f"Starting cleanup for {interview_id}")
        await handler.cleanup()
        if interview_id in active_connections:
            del active_connections[interview_id]
            logger.debug(f"Removed {interview_id} from active_connections")
        logger.info(f"Cleanup complete for {interview_id}")