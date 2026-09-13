"""
Circuit Breaker & Exponential Backoff Engine for Antigravity Account Controller
Protects against infinite failure thrashing loops during account rotation.
States:
- CLOSED: Normal operation, rotation attempts permitted.
- OPEN: Circuit broken after consecutive failures; rotation requests throttled.
- HALF_OPEN: Trial period allowing a single test attempt after cooldown expires.
"""

import time
import random
import logging
from typing import Tuple

logger = logging.getLogger("CircuitBreaker")

class RotationCircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        base_cooldown_sec: float = 60.0,
        max_cooldown_sec: float = 900.0,  # 15 minutes max
        backoff_multiplier: float = 2.0,
        jitter_factor: float = 0.2
    ):
        self.failure_threshold = failure_threshold
        self.base_cooldown_sec = base_cooldown_sec
        self.max_cooldown_sec = max_cooldown_sec
        self.backoff_multiplier = backoff_multiplier
        self.jitter_factor = jitter_factor
        
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.consecutive_failures = 0
        self.last_failure_time = 0.0
        self.current_cooldown = base_cooldown_sec
        self.next_attempt_allowed_at = 0.0

    def can_attempt(self) -> Tuple[bool, str, float]:
        """
        Determines whether a rotation attempt is currently permitted by the circuit.
        Returns: (can_attempt, reason_message, wait_seconds_remaining)
        """
        now = time.time()
        if self.state == "CLOSED":
            return True, "Circuito CERRADO (operativo normal)", 0.0
            
        if self.state == "OPEN":
            if now >= self.next_attempt_allowed_at:
                self.state = "HALF_OPEN"
                logger.info("[CIRCUIT BREAKER] Cooldown expirado. Transición a HALF_OPEN: permitiendo 1 intento de prueba.")
                return True, "Circuito en prueba (HALF_OPEN)", 0.0
            else:
                wait_remaining = self.next_attempt_allowed_at - now
                return False, f"Circuito ABIERTO. Cooldown activo ({int(wait_remaining)}s restantes)", wait_remaining

        if self.state == "HALF_OPEN":
            return True, "Circuito en prueba (HALF_OPEN)", 0.0

        return False, "Estado desconocido del circuito", 60.0

    def record_success(self):
        """Records a successful rotation, resetting failures and restoring CLOSED state."""
        if self.consecutive_failures > 0 or self.state != "CLOSED":
            logger.info(f"[CIRCUIT BREAKER] Operación exitosa. Circuito RESTABLECIDO a CLOSED tras {self.consecutive_failures} fallos.")
        self.state = "CLOSED"
        self.consecutive_failures = 0
        self.current_cooldown = self.base_cooldown_sec
        self.next_attempt_allowed_at = 0.0

    def record_failure(self, error_reason: str = ""):
        """
        Records a rotation failure, increments consecutive failure counter,
        and applies exponential backoff with random jitter.
        """
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        
        exponent = max(0, self.consecutive_failures - 1)
        raw_cooldown = min(self.max_cooldown_sec, self.base_cooldown_sec * (self.backoff_multiplier ** exponent))
        jitter = random.uniform(0, raw_cooldown * self.jitter_factor)
        self.current_cooldown = raw_cooldown + jitter
        self.next_attempt_allowed_at = self.last_failure_time + self.current_cooldown
        
        if self.consecutive_failures >= self.failure_threshold:
            self.state = "OPEN"
            logger.error(
                f"[CIRCUIT BREAKER ACTIVADO] {self.consecutive_failures} fallos consecutivos detectados ({error_reason}). "
                f"Circuito ABIERTO. Rotaciones pausadas durante {int(self.current_cooldown)}s (~{int(self.current_cooldown // 60)} min)."
            )
        else:
            logger.warning(
                f"[CIRCUIT BREAKER] Fallo registrado ({self.consecutive_failures}/{self.failure_threshold}). "
                f"Próximo reintento diferido por {int(self.current_cooldown)}s."
            )
