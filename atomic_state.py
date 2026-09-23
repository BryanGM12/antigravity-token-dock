"""
Atomic, Cross-Process Thread-Safe State Store with Windows Retry & Backup Recovery
"""
import os
import json
import time
import shutil
import logging
from typing import Dict, Any, Callable, Optional

logger = logging.getLogger("AtomicState")

class SafeJsonStore:
    def __init__(self, filepath: str, default_factory: Optional[Callable[[], Dict[str, Any]]] = None):
        self.filepath = filepath
        self.default_factory = default_factory or dict

    def read(self) -> Dict[str, Any]:
        return self.load_json(self.filepath, self.default_factory)

    def write(self, data: Dict[str, Any]):
        self.save_json(self.filepath, data)

    @staticmethod
    def load_json(filepath: str, default_factory: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
        bak_file = filepath + ".bak"
        
        # 1. Try loading primary file with short retries
        if os.path.exists(filepath):
            for attempt in range(5):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        return data
                except (PermissionError, OSError):
                    time.sleep(0.02 * (attempt + 1))
                except json.JSONDecodeError:
                    if attempt < 2:
                        time.sleep(0.03 * (attempt + 1))
                        continue
                    logger.warning(f"[CORRUPCIÓN DETECTADA] {filepath} corrupto o truncado. Intentando respaldo .bak...")
                    break
                    
        # 2. Respaldo .bak si el principal está corrupto
        if os.path.exists(bak_file):
            try:
                with open(bak_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    logger.info(f"[RECUPERADO] Estado restaurado exitosamente desde {bak_file}")
                    SafeJsonStore.save_json(filepath, data)
                    return data
            except Exception as e:
                logger.error(f"Fallo al leer respaldo .bak: {e}")

        # 3. Fallback a fábrica por defecto
        return default_factory()

    @staticmethod
    def save_json(filepath: str, data: Dict[str, Any]):
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        # Unique temporary filename per process and timestamp
        temp_file = f"{filepath}.{os.getpid()}_{time.time_ns()}.tmp"
        bak_file = filepath + ".bak"

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        # Backup existing target
        if os.path.exists(filepath):
            try:
                shutil.copyfile(filepath, bak_file)
            except Exception:
                pass

        # Atomic replacement with retries for Windows WinError 32
        success = False
        for attempt in range(10):
            try:
                os.replace(temp_file, filepath)
                success = True
                break
            except (PermissionError, OSError):
                time.sleep(0.03 * (attempt + 1))

        if not success:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass
            raise TimeoutError(f"No se pudo completar el guardado atómico en {filepath} tras 10 reintentos.")
