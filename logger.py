import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

def setup_logging(log_file: str):
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s')
    handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
    handler.setFormatter(log_formatter)
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger().addHandler(handler)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)