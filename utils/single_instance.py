"""
Bitta nusxa bloklash (single instance lock).

Telegram'da bir bot tokeni bilan **faqat bitta** `getUpdates` (polling)
so'rovi ishlashi mumkin. Ikkinchisi ishga tushsa:
    telegram.error.Conflict: terminated by other getUpdates request

Bu blok fayl darajasidagi qulflash (flock/locking) orqali hal qilinadi:
qulfa ega bo'lgan jarayon o'chsa, qulf fayl yopilganda avtomatik bo'shaydi
(boshqa jarayon "vafot etgan" qulfdan qolmaydi).

Windows: msvcrt.locking, Unix/Linux/macOS: fcntl.flock.
"""
from __future__ import annotations

import os
from pathlib import Path


class SingleInstanceLock:
    """Fayl quflab, bitta nusxani kafolatlaydi."""

    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(path)
        self._handle = None
        self.acquired = False

    def acquire(self) -> bool:
        """Qulfni oladi. Boshqa jarayon ushlab turgan bo'lsa — False."""
        if self.acquired:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        self.acquired = True
        return True

    def release(self) -> None:
        """Qulfni bo'shatadi (jarayon tugasa ham avtomatik bo'shaydi)."""
        if not self.acquired or self._handle is None:
            return
        try:
            self._handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            try:
                self._handle.close()
            except OSError:
                pass
            self._handle = None
            self.acquired = False

    def __enter__(self) -> "SingleInstanceLock":
        self.acquire()
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()
