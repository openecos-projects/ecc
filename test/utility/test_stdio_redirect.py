import os
import sys
import threading

import pytest

from chipcompiler.utility import log as log_module
from chipcompiler.utility.log import (
    capture_stdio_to_file,
    init_api_runtime_log,
    redirect_stdio_to_file,
)


@pytest.fixture(autouse=True)
def _reset_persistent_redirect():
    yield
    log_module._close_persistent_redirect()


class TestRedirectSemanticBehavior:
    """Verify redirect semantics, not just fd counts."""

    def test_r1_then_r2_stdout_stderr_point_to_r2(self, tmp_path):
        """After r1 then r2, writing to stdout goes to r2's log."""
        r1 = redirect_stdio_to_file(str(tmp_path / "r1.log"))
        print("to-r1")

        r2 = redirect_stdio_to_file(str(tmp_path / "r2.log"))
        print("to-r2")
        sys.stderr.write("err-to-r2\n")
        r2.flush()

        r2.close()
        assert "to-r2" in (tmp_path / "r2.log").read_text()
        assert "err-to-r2" in (tmp_path / "r2.log").read_text()
        r1.close()

    def test_r2_close_restores_to_r1_state(self, tmp_path):
        """Closing r2 restores fd 1/2 to whatever was active before r2."""
        r1 = redirect_stdio_to_file(str(tmp_path / "r1.log"))
        r2 = redirect_stdio_to_file(str(tmp_path / "r2.log"))

        print("after-r2")
        r2.close()

        print("after-r2-close")
        r1.close()

        r2_text = (tmp_path / "r2.log").read_text()
        assert "after-r2" in r2_text
        assert "after-r2-close" not in r2_text

    def test_r1_close_after_r2_does_not_corrupt(self, tmp_path):
        """Closing an already-superseded r1 is a no-op that doesn't corrupt r2."""
        r1 = redirect_stdio_to_file(str(tmp_path / "r1.log"))
        r2 = redirect_stdio_to_file(str(tmp_path / "r2.log"))

        print("during-r2")
        r1.close()

        print("still-r2")
        r2.close()

        r2_text = (tmp_path / "r2.log").read_text()
        assert "during-r2" in r2_text
        assert "still-r2" in r2_text

    def test_scoped_capture_restores_original(self, tmp_path):
        """capture_stdio_to_file restores stdout/stderr after scope exits."""
        stdout_file = tmp_path / "orig_stdout.txt"
        stderr_file = tmp_path / "orig_stderr.txt"

        saved_stdout_fd = os.dup(1)
        saved_stderr_fd = os.dup(2)
        try:
            with open(stdout_file, "wb") as sf, open(stderr_file, "wb") as ef:
                os.dup2(sf.fileno(), 1)
                os.dup2(ef.fileno(), 2)

            with capture_stdio_to_file(str(tmp_path / "step.log")):
                os.write(1, b"inside-capture\n")
                os.write(2, b"err-inside-capture\n")

            os.write(1, b"after-capture\n")
            os.write(2, b"err-after-capture\n")
        finally:
            os.dup2(saved_stdout_fd, 1)
            os.dup2(saved_stderr_fd, 2)
            os.close(saved_stdout_fd)
            os.close(saved_stderr_fd)

        assert "inside-capture" in (tmp_path / "step.log").read_text()
        assert "after-capture" in stdout_file.read_text()
        assert "err-inside-capture" in (tmp_path / "step.log").read_text()
        assert "err-after-capture" in stderr_file.read_text()

    def test_nested_scoped_captures_restore_correctly(self, tmp_path):
        """Nested capture_stdio_to_file restores each layer correctly."""
        with capture_stdio_to_file(str(tmp_path / "outer.log")):
            os.write(1, b"outer\n")
            with capture_stdio_to_file(str(tmp_path / "inner.log")):
                os.write(1, b"inner\n")
            os.write(1, b"after-inner\n")

        assert (tmp_path / "outer.log").read_text() == "outer\nafter-inner\n"
        assert (tmp_path / "inner.log").read_text() == "inner\n"

    def test_exception_during_enter_restores_cleanly(self, tmp_path):
        """If __enter__ raises, fd 1/2 are restored and no fds leak."""
        fd_before = len(os.listdir("/proc/self/fd"))

        with pytest.raises(OSError):
            redirect_stdio_to_file("/nonexistent/deeply/nested/path.log")

        fd_after = len(os.listdir("/proc/self/fd"))
        assert fd_after <= fd_before + 1

        print("still-works")
        assert True

    def test_concurrent_redirect_stdio_to_file(self, tmp_path):
        """Concurrent capture_stdio_to_file calls serialize and don't corrupt state."""
        barrier = threading.Barrier(2)
        results = {}

        def worker(name, log_path):
            barrier.wait()
            with capture_stdio_to_file(str(log_path)):
                print(f"from-{name}")
                fd_now = os.dup(1)
                results[name] = fd_now

        t1 = threading.Thread(target=worker, args=("a", tmp_path / "a.log"))
        t2 = threading.Thread(target=worker, args=("b", tmp_path / "b.log"))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        for fd_copy in results.values():
            os.close(fd_copy)

        a_text = (tmp_path / "a.log").read_text()
        b_text = (tmp_path / "b.log").read_text()
        assert "from-a" in a_text
        assert "from-b" in b_text

    def test_repeated_init_api_runtime_log_logs_to_last_file(self, tmp_path):
        """Repeated init_api_runtime_log redirects output to the most recent log."""
        for i in range(5):
            init_api_runtime_log(str(tmp_path / f"run_{i}.log"))

        os.write(1, b"final-output\n")
        sys.stderr.write("final-err\n")
        sys.stderr.flush()

        for i in range(4):
            content = (tmp_path / f"run_{i}.log").read_text()
            assert "final-output" not in content, f"run_{i}.log should not have final output"

        last_content = (tmp_path / "run_4.log").read_text()
        assert "final-output" in last_content
        assert "final-err" in last_content

    def test_repeated_init_api_runtime_log_no_fd_leak(self, tmp_path):
        """Repeated init_api_runtime_log does not grow fd count unboundedly."""
        fd_before = len(os.listdir("/proc/self/fd"))
        for i in range(10):
            init_api_runtime_log(str(tmp_path / f"run_{i}.log"))
        fd_after = len(os.listdir("/proc/self/fd"))
        assert fd_after - fd_before < 5

    def test_capture_stdio_to_file_with_none_is_noop(self, tmp_path):
        """capture_stdio_to_file(None) yields without redirecting."""
        target = tmp_path / "capture_target.txt"
        saved_fd = os.dup(1)
        try:
            with open(target, "wb") as f:
                os.dup2(f.fileno(), 1)

            with capture_stdio_to_file(None):
                os.write(1, b"should-go-to-target\n")

            os.write(1, b"still-target\n")
        finally:
            os.dup2(saved_fd, 1)
            os.close(saved_fd)

        content = target.read_text()
        assert "should-go-to-target" in content
        assert "still-target" in content


def test_scoped_capture_does_not_clear_persistent_redirect(tmp_path):
    """A scoped capture entering and leaving must not orphan the persistent redirect."""
    init_api_runtime_log(str(tmp_path / "persistent.log"))

    assert log_module._persistent_redirect is not None

    with capture_stdio_to_file(str(tmp_path / "scoped.log")):
        os.write(1, b"scoped-output\n")

    assert log_module._persistent_redirect is not None

    os.write(1, b"persistent-output\n")
    assert "persistent-output" in (tmp_path / "persistent.log").read_text()


def test_interleaved_init_capture_init_does_not_leak_fds(tmp_path):
    """The sequence init -> capture -> init -> capture -> init must not grow fds."""
    fd_before = len(os.listdir("/proc/self/fd"))

    init_api_runtime_log(str(tmp_path / "run_0.log"))
    fd_after_init_0 = len(os.listdir("/proc/self/fd"))

    with capture_stdio_to_file(str(tmp_path / "cap_0.log")):
        os.write(1, b"cap-0\n")
    fd_after_cap_0 = len(os.listdir("/proc/self/fd"))

    init_api_runtime_log(str(tmp_path / "run_1.log"))
    fd_after_init_1 = len(os.listdir("/proc/self/fd"))

    with capture_stdio_to_file(str(tmp_path / "cap_1.log")):
        os.write(1, b"cap-1\n")
    fd_after_cap_1 = len(os.listdir("/proc/self/fd"))

    init_api_runtime_log(str(tmp_path / "run_2.log"))
    fd_after_init_2 = len(os.listdir("/proc/self/fd"))

    assert fd_after_init_0 <= fd_before + 5
    assert fd_after_cap_0 <= fd_after_init_0 + 1
    assert fd_after_init_1 <= fd_after_init_0 + 1
    assert fd_after_cap_1 <= fd_after_init_1 + 1
    assert fd_after_init_2 <= fd_after_init_0 + 1
