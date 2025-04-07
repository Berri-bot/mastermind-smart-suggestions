import logging
import json
import sys
from datetime import datetime

class GCPFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "sourceLocation": {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName
            },
            "logger": record.name
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(GCPFormatter())
    logger.handlers = [handler]