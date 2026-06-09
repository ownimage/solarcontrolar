import json
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

class JsonStore:
    def __init__(self, filepath: str):
        self._filepath = filepath
        logger.debug(f"Opening file {filepath}")

    def read(self) -> dict:
        try:
            with open(self._filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.info(f"File {self._filepath} not found.")
            return {}
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {self._filepath}") from e

    def write(self, data: dict) -> None:
        with open(self._filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)