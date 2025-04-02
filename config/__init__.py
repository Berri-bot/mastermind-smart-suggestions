import os
import subprocess
from pathlib import Path
from logger import get_logger, setup_logging

setup_logging()
logger = get_logger("config")

class Config:
    def __init__(self):
        self.BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
        self.LOG_FILE = self.BASE_DIR / "logs" / "server.log"
        self.JDK_HOME = Path(os.getenv("JAVA_HOME", "/app/lsp/java/jdk-21"))
        self.JDT_HOME = Path(os.getenv("JDT_HOME", "/app/lsp/java/jdt-language-server-1.36.0"))
        self.WORKSPACE_DIR = Path("/app/workspace")
        self.PYTHON_LSP_CMD = ["pylsp"]
        self.JDT_CONFIG = self.JDT_HOME / "config_linux"
        
        self.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        self.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Config initialized: JDK_HOME={self.JDK_HOME}, JDT_HOME={self.JDT_HOME}")

    def validate(self):
        logger.info("Validating configuration...")
        java_exec = self.JDK_HOME / "bin" / "java"
        if not java_exec.exists():
            logger.error(f"Java executable not found at {java_exec}")
            raise FileNotFoundError(f"Java executable not found at {java_exec}")
        if not os.access(java_exec, os.X_OK):
            logger.error(f"Java executable at {java_exec} is not executable")
            raise PermissionError(f"Java executable at {java_exec} is not executable")
        try:
            result = subprocess.run([str(java_exec), "-version"], check=True, capture_output=True, text=True)
            logger.info(f"Java version: {result.stderr.strip()}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Java version check failed: {e.stderr}")
            raise RuntimeError(f"Java version check failed: {e.stderr}")
        
        launcher_jars = list((self.JDT_HOME / "plugins").glob("org.eclipse.equinox.launcher_*.jar"))
        if not launcher_jars:
            logger.error(f"No JDT launcher found in {self.JDT_HOME}/plugins")
            raise FileNotFoundError(f"No JDT launcher found in {self.JDT_HOME}/plugins")
        logger.info(f"Using JDT launcher: {launcher_jars[0]}")

config = Config()