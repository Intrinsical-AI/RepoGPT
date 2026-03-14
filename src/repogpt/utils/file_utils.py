# repogpt/utils/file_utils.py

import hashlib
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

CHUNK_SIZE = 8192  # Leer archivos en bloques de 8KB para hashing


def calculate_file_hash(file_path: Path, algorithm: str = "sha256") -> str | None:
    """
    Calcula el hash de un archivo usando el algoritmo especificado.

    Args:
        file_path: Ruta al archivo.
        algorithm: Algoritmo de hash a usar (ej. 'sha256', 'md5').

    Returns:
        El hash en formato hexadecimal como string, o None si ocurre un error.
    """
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
    """
    Intenta determinar si un archivo es probablemente binario.

    Actualmente usa una heurística simple: la presencia de un byte NULL
    dentro de los primeros 'check_bytes'.

    Args:
        file_path: Ruta al archivo.
        check_bytes: Número de bytes iniciales a revisar.

    Returns:
        True si el archivo parece binario, False en caso contrario o si hay error.
    """
    try:
        with file_path.open("rb") as f:
            chunk = f.read(check_bytes)
            if b"\x00" in chunk:
                logger.debug("detected null byte", path=str(file_path))
                return True
            # Podríamos añadir más heurísticas aquí si fuera necesario
            # Por ejemplo, buscar un alto porcentaje de caracteres no imprimibles.
    except FileNotFoundError:
        logger.warning("file not found while checking binary", path=str(file_path))
        return False  # No se puede determinar, asumir no binario por seguridad
    except PermissionError:
        logger.warning("permission denied while checking binary", path=str(file_path))
        return False  # Asumir no binario
    except OSError as e:
        logger.warning("os error while checking binary", path=str(file_path), error=str(e))
        return False  # Asumir no binario
    except Exception as e:
        logger.warning("unexpected error while checking binary", path=str(file_path), error=str(e))
        return False  # Asumir no binario

    logger.debug("file does not look binary", path=str(file_path))
    return False


# Podrías añadir aquí otras utilidades relacionadas con archivos si las necesitas.
