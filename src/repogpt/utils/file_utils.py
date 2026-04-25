import hashlib
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

CHUNK_SIZE = 8192


def calculate_file_hash(file_path: Path, algorithm: str = "sha256") -> str | None:
    """Calculate a file hash, returning None when the file cannot be read."""
    try:
        hasher = hashlib.new(algorithm)
        with file_path.open("rb") as f:
            while chunk := f.read(CHUNK_SIZE):
                hasher.update(chunk)
        return hasher.hexdigest()
    except FileNotFoundError:
        logger.error("file not found while hashing", path=str(file_path))
    except PermissionError:
        logger.error("permission denied while hashing", path=str(file_path))
    except OSError as e:
        logger.error("os error while hashing", path=str(file_path), error=str(e))
    except ValueError:
        logger.error("invalid hash algorithm", algorithm=algorithm)
    except Exception as e:
        logger.exception("unexpected error while hashing", path=str(file_path), error=str(e))

    return None


def is_likely_binary(file_path: Path, check_bytes: int = 1024) -> bool:
    """Return True when a file looks binary based on an initial byte sample."""
    try:
        with file_path.open("rb") as f:
            chunk = f.read(check_bytes)
            if b"\x00" in chunk:
                logger.debug("detected null byte", path=str(file_path))
                return True
    except FileNotFoundError:
        logger.warning("file not found while checking binary", path=str(file_path))
        return False
    except PermissionError:
        logger.warning("permission denied while checking binary", path=str(file_path))
        return False
    except OSError as e:
        logger.warning("os error while checking binary", path=str(file_path), error=str(e))
        return False
    except Exception as e:
        logger.warning("unexpected error while checking binary", path=str(file_path), error=str(e))
        return False

    return False
