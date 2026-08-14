import logging
import os
import sys

_PLAIN_FORMAT = "%(message)s"
_DETAILED_FORMAT = "%(asctime)s %(levelname)-7s %(name)s - %(message)s"

_configured = False


def setup_logging(stream=None):
    global _configured
    if _configured:
        return logging.getLogger()
    _configured = True

    level = _level_from_env()

    if level is None:
        logging.basicConfig(level=logging.INFO, format=_PLAIN_FORMAT, force=True, stream=stream)
        return logging.getLogger()

    root = logging.getLogger()
    for handler in root.handlers:
        root.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(logging.Formatter(_DETAILED_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)
    root.debug("debug logging enabled at level %s", logging.getLevelName(level))
    return root


def _level_from_env():
    debug_flag = os.getenv("DEBUG", "").strip().lower()
    if debug_flag in ("1", "true", "yes", "on"):
        return logging.DEBUG

    level_name = os.getenv("LOG_LEVEL", "").strip().upper()
    if not level_name:
        return None
    level = getattr(logging, level_name, None)
    if level is None:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger(__name__).warning("Unrecognised LOG_LEVEL %r, ignoring", level_name)
        return None
    return level


def debug_enabled() -> bool:
    return _level_from_env() is not None