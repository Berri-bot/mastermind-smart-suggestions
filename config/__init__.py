from pathlib import Path
import subprocess
from logger import get_logger

logger = get_logger("config")

class Config:
    def __init__(self):
        # Base application directory
        self.APP_DIR = Path("/app")
        
        # JDK configuration
        self.JDK_HOME = self.APP_DIR / "lsp" / "java"
        self.JAVA_BIN = self.JDK_HOME / "bin" / "java"
        
        # JDTLS configuration
        self.JDT_HOME = self.APP_DIR / "lsp" / "java" / "jdt-language-server-1.36.0"
        self.JDT_CONFIG = self.JDT_HOME / "config_linux"
        self.JDT_LAUNCHER = self.JDT_HOME / "plugins" / "org.eclipse.equinox.launcher_1.6.800.v20240513-1750.jar"
        
        # Workspace directory
        self.WORKSPACE_DIR = self.APP_DIR / "workspace"
        self.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        
        # Log file
        self.LOG_FILE = self.APP_DIR / "app.log"
        
        # Log configuration details
        logger.info(
            f"Configuration initialized:\n"
            f"  JDK_HOME: {self.JDK_HOME}\n"
            f"  JAVA_BIN: {self.JAVA_BIN}\n"
            f"  JDT_HOME: {self.JDT_HOME}\n"
            f"  JDT_CONFIG: {self.JDT_CONFIG}\n"
            f"  JDT_LAUNCHER: {self.JDT_LAUNCHER}\n"
            f"  WORKSPACE_DIR: {self.WORKSPACE_DIR}"
        )
        
        # Validate configuration on initialization
        self.validate_java()

    def validate_java(self):
        """Validate that Java is correctly installed and executable"""
        try:
            result = subprocess.run(
                [str(self.JAVA_BIN), "-version"],
                capture_output=True,
                text=True,
                check=True
            )
            java_version = result.stderr.strip()  # -version outputs to stderr
            logger.info(f"Java version: {java_version}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Java validation failed with exit code {e.returncode}: {e.stderr}", exc_info=True)
            raise RuntimeError(f"Java validation failed: {e.stderr}")
        except FileNotFoundError:
            logger.error(f"Java binary not found at {self.JAVA_BIN}", exc_info=True)
            raise RuntimeError(f"Java binary not found at {self.JAVA_BIN}")
        except Exception as e:
            logger.error(f"Unexpected error during Java validation: {e}", exc_info=True)
            raise

# Singleton instance of Config
config = Config()