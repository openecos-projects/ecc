import os
import sys

from chipcompiler.runtime.events import redirect_stdout_to_stderr


def test_redirect_stdout_to_stderr_restores_fd_1_and_fd_2(tmp_path):
    stdout_target = tmp_path / "stdout.txt"
    stderr_target = tmp_path / "stderr.txt"
    redirected_target = tmp_path / "redirected.txt"

    saved_stdout_fd = os.dup(1)
    saved_stderr_fd = os.dup(2)
    with open(stdout_target, "wb") as stdout_file, open(stderr_target, "wb") as stderr_file:
        os.dup2(stdout_file.fileno(), 1)
        os.dup2(stderr_file.fileno(), 2)
        try:
            with redirect_stdout_to_stderr(), open(redirected_target, "wb") as redirected_file:
                os.dup2(redirected_file.fileno(), 2)
                os.write(1, b"captured stdout\n")
                os.write(2, b"captured stderr\n")

            os.write(1, b"restored stdout\n")
            os.write(2, b"restored stderr\n")
        finally:
            os.dup2(saved_stdout_fd, 1)
            os.dup2(saved_stderr_fd, 2)
            os.close(saved_stdout_fd)
            os.close(saved_stderr_fd)
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

    assert stdout_target.read_text() == "restored stdout\n"
    assert stderr_target.read_text() == "captured stdout\nrestored stderr\n"
    assert redirected_target.read_text() == "captured stderr\n"
