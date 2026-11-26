"""Limit repeated failed logins (password guessing).

Two counters, both over a sliding window:

- per account (email): after `max_failures` wrong passwords the account cannot be
  logged into for `lockout` time, from anywhere. This stops guessing one password.
- per client IP address: a higher limit (`ip_factor` x `max_failures`), so a single
  client cannot try one common password against many accounts either.

A successful login clears the account's counter. The counters live in memory: right for
this single-process deployment (SQLite, one uvicorn worker); several workers or servers
would share them through a store such as Redis instead. Unknown emails are counted like
real ones, so the lockout does not reveal which accounts exist.
"""

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from threading import Lock
from time import monotonic


@dataclass
class LoginThrottle:
    max_failures: int = 5
    window: timedelta = timedelta(minutes=15)
    lockout: timedelta = timedelta(minutes=15)
    ip_factor: int = 4
    clock: Callable[[], float] = monotonic
    _failures: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _locked_until: dict[str, float] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    @staticmethod
    def _keys(email: str, ip_address: str | None) -> list[tuple[str, int]]:
        """(counter key, its limit factor): the account, and the client if known."""
        keys = [(f"email:{email.lower()}", 1)]
        if ip_address:
            keys.append((f"ip:{ip_address}", 0))  # 0 = use ip_factor
        return keys

    def _limit(self, factor: int) -> int:
        return self.max_failures * (factor or self.ip_factor)

    def retry_after(self, email: str, ip_address: str | None) -> int:
        """Seconds until a login may be tried again (0 = allowed now)."""
        now = self.clock()
        with self._lock:
            waits = [
                self._locked_until[key] - now
                for key, _ in self._keys(email, ip_address)
                if self._locked_until.get(key, 0) > now
            ]
        return int(max(waits) + 0.999) if waits else 0

    def failed(self, email: str, ip_address: str | None) -> None:
        """Count a failed attempt; lock the account (or client) when over its limit."""
        now = self.clock()
        horizon = now - self.window.total_seconds()
        with self._lock:
            for key, factor in self._keys(email, ip_address):
                attempts = self._failures[key]
                attempts.append(now)
                while attempts and attempts[0] <= horizon:
                    attempts.popleft()
                if len(attempts) >= self._limit(factor):
                    self._locked_until[key] = now + self.lockout.total_seconds()
                    attempts.clear()

    def succeeded(self, email: str) -> None:
        """A correct password: forget the account's failed attempts."""
        key = f"email:{email.lower()}"
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()
