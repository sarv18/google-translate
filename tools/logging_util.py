import logging
import os
from logging.handlers import TimedRotatingFileHandler
from tools.file_manager import create_directory_structure
from config import BASE_DATA_PATH, SESSION_KEY


def setup_logger(logger_name, path=None, allow_stream_log=False):
    """
    Setup a logger with timed rotating file handler.

    Args:
        logger_name: Name of the logger
        path: Ignored - uses BASE_DATA_PATH from config
        allow_stream_log: If True, also log to console
    """
    log_path = f"{BASE_DATA_PATH}/logs"

    # Create directory structure if it doesn't exist
    if not os.path.exists(log_path):
        create_directory_structure(BASE_DATA_PATH + "/logs")

    # Create per-logger subdirectory (operation/, classification/, etc.)
    subdir = f"{log_path}/{logger_name}"
    os.makedirs(subdir, exist_ok=True)

    logger_name_with_session = f"senti_{logger_name}@{SESSION_KEY}"
    logger = logging.getLogger(logger_name_with_session)

    # Only add handler if not already present
    if not logger.handlers:
        handler = TimedRotatingFileHandler(
            f"{log_path}/{logger_name}/{logger_name}.log",
            when='midnight',
            backupCount=5,
            interval=1
        )
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(f'{SESSION_KEY} @&#&@ %(message)s;%(asctime)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        if allow_stream_log:
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            logger.addHandler(stream_handler)

    return logger