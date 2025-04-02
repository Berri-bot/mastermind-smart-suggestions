import os
import subprocess
from pathlib import Path
from typing import List
from logger import get_logger, setup_logging

setup_logging()
logger = get_logger("config")

class Config:
    def __init__(self):
        self.BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
        self.LOG_FILE = self.BASE_DIR / "logs" / "server.log"
        self.JDK_HOME = Path(os.getenv("JAVA_HOME", "/app/lsp/java/jdk-21"))
        self.JDT_HOME = Path(os.getenv("JDT_HOME", "/app/lsp/java/jdt-language-server-1.36.0"))
        self.WORKSPACE_DIR = Path(os.getenv("WORKSPACE", "/app/workspace"))
        self.PYTHON_LSP_CMD = ["pylsp"]
        
        # JDTLS specific paths
        self.JDT_CONFIG = self.JDT_HOME / "config_linux"
        self.JDT_PLUGINS = self.JDT_HOME / "plugins"
        self.JDT_LAUNCHER = self._find_launcher_jar()
        
        # Validate paths
        self._validate_paths()
        
        logger.info(f"Configuration initialized:\n"
                   f"  JDK_HOME: {self.JDK_HOME}\n"
                   f"  JDT_HOME: {self.JDT_HOME}\n"
                   f"  WORKSPACE: {self.WORKSPACE_DIR}\n"
                   f"  JDT Launcher: {self.JDT_LAUNCHER}")

    def _find_launcher_jar(self) -> Path:
        launcher_jars = list(self.JDT_PLUGINS.glob("org.eclipse.equinox.launcher_*.jar"))
        if not launcher_jars:
            raise FileNotFoundError(f"No JDT launcher JAR found in {self.JDT_PLUGINS}")
        return launcher_jars[0]

    def _validate_paths(self):
        """Validate all required paths exist and are accessible"""
        required_paths = [
            (self.JDK_HOME / "bin" / "java", "Java executable"),
            (self.JDT_HOME, "JDT Language Server"),
            (self.JDT_CONFIG, "JDT config directory"),
            (self.JDT_LAUNCHER, "JDT launcher JAR")
        ]
        
        for path, description in required_paths:
            if not path.exists():
                raise FileNotFoundError(f"{description} not found at {path}")
            if not os.access(path, os.R_OK):
                raise PermissionError(f"No read access to {path}")

    def validate_java(self) -> str:
        """Validate Java installation and return version"""
        java_exec = self.JDK_HOME / "bin" / "java"
        try:
            result = subprocess.run(
                [str(java_exec), "-version"],
                check=True,
                capture_output=True,
                text=True
            )
            version = result.stderr.split('\n')[0].strip()
            logger.info(f"Java version: {version}")
            return version
        except subprocess.CalledProcessError as e:
            logger.error(f"Java version check failed: {e.stderr}")
            raise RuntimeError(f"Java version check failed: {e.stderr}")

config = Config()