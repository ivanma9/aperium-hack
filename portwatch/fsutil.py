"""Atomic file writes."""
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_path(path):
    """Yield a unique temporary path next to `path`; move it over `path` when the block succeeds, remove
    it when it fails. The name comes from mkstemp, so two writers of the same target never share a tmp."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    os.close(fd)
    umask = os.umask(0)
    os.umask(umask)
    os.chmod(tmp, 0o666 & ~umask)                 # mkstemp makes 0600; keep the usual file mode
    try:
        yield Path(tmp)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
