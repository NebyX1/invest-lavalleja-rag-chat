"""El índice embebido y la activación requieren un único proceso escritor."""
import os


class RuntimeLock:
    def __init__(self, path):
        self.file = path.open("a+b")
        try:
            if self.file.seek(0, 2) == 0:
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("El volumen ya está en uso. Ejecutá una sola réplica y un solo worker de Gianna.") from None

    def close(self):
        self.file.close()
