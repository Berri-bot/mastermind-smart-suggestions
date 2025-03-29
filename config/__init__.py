import os
import logging
import subprocess
import sys
from pathlib import Path

class Config:
    def __init__(self):
        self.BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
        self.LOG_FILE = self.BASE_DIR / "logs" / "server.log"
        
        self.JDK_HOME = Path(os.getenv("JAVA_HOME", "/app/lsp/java/jdk-21.0.2"))
        self.JDT_HOME = Path(os.getenv("JDT_HOME", "/app/lsp/java/jdt-language-server-1.36.0"))
        self.WORKSPACE_DIR = Path("/app/workspace")
        self.PYTHON_LSP_CMD = ["pylsp"]
        
        # JDT Configuration
        self.JDT_CONFIG = self.JDT_HOME / "config_linux"
        if not self.JDT_CONFIG.exists():
            self.JDT_CONFIG = self.JDT_HOME / "config_mac" if sys.platform == "darwin" else self.JDT_HOME / "config_win"
        
        # Create required directories
        self.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        self.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        
    def validate(self):
        logger = logging.getLogger(__name__)
        
        # Verify Java setup
        java_exec = self.JDK_HOME / "bin" / "java"
        if not java_exec.exists():
            raise FileNotFoundError(f"Java executable not found at {java_exec}")
        logger.info(f"Using Java from: {self.JDK_HOME}")
        
        # Verify JDTLS
        launcher_jars = list((self.JDT_HOME / "plugins").glob("org.eclipse.equinox.launcher_*.jar"))
        if not launcher_jars:
            raise FileNotFoundError(f"No JDT launcher found in {self.JDT_HOME}/plugins")
        logger.info(f"Using JDT launcher: {launcher_jars[0]}")
        
        # Verify Python
        try:
            subprocess.run(["python", "--version"], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Python not available: {e.stderr.decode()}")

config = Config()