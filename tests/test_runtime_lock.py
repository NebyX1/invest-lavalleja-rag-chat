import pytest

from admin_runtime import RuntimeLock


def test_only_one_runtime_can_own_persistent_data(tmp_path):
    path = tmp_path / "runtime.lock"
    owner = RuntimeLock(path)
    try:
        with pytest.raises(RuntimeError, match="una sola réplica"):
            RuntimeLock(path)
    finally:
        owner.close()
    replacement = RuntimeLock(path)
    replacement.close()
    assert path.stat().st_size == 1
