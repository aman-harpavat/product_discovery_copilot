from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import settings


def configure_logging() -> None:
    root_logger = logging.getLogger()
    if getattr(configure_logging, "_configured", False):
        return

    log_path = Path(settings.log_file_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(settings.log_level.upper())
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(settings.log_level.upper())
    stream_handler.setFormatter(formatter)

    root_logger.setLevel(settings.log_level.upper())
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

    configure_logging._configured = True
