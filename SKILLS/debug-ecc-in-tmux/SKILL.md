---
name: debug-ecc-in-tmux
description: Reproduce and inspect this repository's ECC Python, C++, pybind, iDB/iRT, and CUDA failures under GDB or cuda-gdb inside a persistent tmux session. Use for native crashes, wrong database values, missed native breakpoints, pin/net/geometry inspection, attaching to a running ECC process, or preserving a stopped debugger for later commands.
---

# Debug ECC in tmux

Keep one reproducible ECC invocation stopped at the narrowest useful native boundary. Preserve the tmux session so another person or turn can inspect it without rerunning an expensive flow.

## Establish the Reproduction

1. Read `AGENTS.md`, `docs/development.md`, `.vscode/launch.json` when present, native package `pyproject.toml` files, and `.venv/bin/ecc run --help`.
2. Record the repository commit, recursive submodule commits, Workspace, persisted Step, exact failure, and whether replacing that Step's output is acceptable.
3. Inspect `ps` and existing tmux sessions for another writer. ECC has no Workspace process lock; never start a second writer.
4. Prefer the public Workspace entry:

```bash
.venv/bin/python -m chipcompiler.cli.main run \
  --workspace /path/to/workspace --only place --force --json
```

Replace `place` with the exact Step from `home/flow.json`. Reproduce once without a debugger when practical and capture the error, signal, thread behavior, and log path.

## Prepare Native Code

Follow `../run-and-test-ecc/SKILL.md` for checkout, submodule, Nix, uv, and import-provenance checks. Build the affected package before launching a debugger:

```bash
cmake --build chipcompiler/thirdparty/ecc-tools/build --target ecc_py -j 8
cmake --build chipcompiler/thirdparty/ecc-dreamplace/build -j 8
```

If the build tree is stale, missing, or ABI-incompatible, recreate the editable package with `uv sync --reinstall-package <package>` and the repository's `--no-build-isolation-package` options.

Require a Debug/unstripped extension for source-line breakpoints. For CUDA device stepping, rebuild with device debug flags such as `CUDA_NVCC_FLAGS_DEBUG=-G`; host GDB cannot step a device kernel.

Prevent scikit-build from rebuilding after the debugger starts by passing the exact build directories:

```bash
repo=$(git rev-parse --show-toplevel)
export SKBUILD_EDITABLE_SKIP="$repo/chipcompiler/thirdparty/ecc-dreamplace/build:$repo/chipcompiler/thirdparty/ecc-tools/build"
```

Do not use `SKBUILD_EDITABLE_SKIP=1`; it is interpreted as a list of paths.

## Start a Persistent Session

Choose a unique session name. Never reuse or kill an existing session without authorization.

```bash
repo=$(git rev-parse --show-toplevel)
workspace="/absolute/path/to/workspace"
session=ecc-place-native-debug
skip_paths="$repo/chipcompiler/thirdparty/ecc-dreamplace/build:$repo/chipcompiler/thirdparty/ecc-tools/build"

if tmux has-session -t "$session" 2>/dev/null; then
  echo "tmux session already exists: $session" >&2
  exit 1
fi

printf -v quoted_skip_paths '%q' "$skip_paths"
printf -v quoted_python '%q' "$repo/.venv/bin/python"
printf -v quoted_workspace '%q' "$workspace"
debug_command="exec env SKBUILD_EDITABLE_SKIP=$quoted_skip_paths PYTHONFAULTHANDLER=1 PYTHONUNBUFFERED=1 /usr/bin/gdb --args $quoted_python -m chipcompiler.cli.main run --workspace $quoted_workspace --only place --force --json"
tmux new-session -d -s "$session" -c "$repo" "$debug_command"
```

`printf %q` keeps repository and Workspace paths as single shell words when tmux starts the command. Attach with `tmux attach -t "$session"`, or send one debugger command at a time and verify it with `tmux capture-pane`. Do not enqueue an unchecked command batch.

## Configure GDB

Use this baseline for ECC-Tools, iDB, iRT, and host-side DreamPlace code:

```gdb
set pagination off
set confirm off
set print pretty on
set print elements 0
set breakpoint pending on
set follow-fork-mode parent
set detach-on-fork on
add-auto-load-safe-path /absolute/path/to/ecc
break /absolute/path/to/source.cpp:LINE
run
```

Pending breakpoints are normal because native extensions load after Python starts. Prefer `follow-fork-mode parent` until evidence shows the target executes in a child.

For signal failures, stop before teardown:

```gdb
handle SIGSEGV stop print pass
handle SIGFPE stop print pass
handle SIGABRT stop print pass
catch throw
```

Break immediately before a fatal logger or abort when the handler destroys useful locals.

## Inspect a Hit

Start with execution context rather than guessed accessors:

```gdb
info breakpoints
info sharedlibrary
info threads
thread apply all bt 3
thread THREAD_NUMBER
frame 0
bt 40
info args
info locals
ptype TYPE_OR_EXPRESSION
```

iRT and placement use worker threads; select the thread stopped at the target frame. For pin, net, placement, or geometry failures, capture:

- Native thread and full backtrace.
- Net and pin names/indices.
- IO versus instance-pin ownership, instance name, and placement status.
- Access point and shape rectangles/layers.
- Die/core/grid bounds and the exact failed comparison.
- Pointer identities when aliasing or ownership is suspected.

Use verified singleton/global state only after `ptype`, `info args`, and `info locals` establish the current types. Change one value or hypothesis at a time; prefer inspection over debugger mutation.

## Debug CUDA

Use the installed `cuda-gdb`, serialize launches, and verify the local toolkit path instead of hard-coding a version:

```bash
env CUDA_LAUNCH_BLOCKING=1 \
  SKBUILD_EDITABLE_SKIP="$SKBUILD_EDITABLE_SKIP" \
  /path/to/cuda-gdb --args .venv/bin/python /path/to/reproducer.py
```

```gdb
set breakpoint pending on
break /absolute/path/to/kernel.cu:LINE
run
info cuda kernels
info cuda threads
bt
```

Use host GDB for wrappers and cuda-gdb only when the suspected defect is in device code.

## Attach to an Existing Process

Confirm the exact Python process that loaded the target extension, not a Yosys/Sizer child or monitor:

```bash
ps -eo pid,ppid,stat,etime,cmd | rg 'chipcompiler.cli.main|\.venv/bin/python'
repo=$(git rev-parse --show-toplevel)
session=ecc-native-attach
pid=PID

[[ "$pid" =~ ^[0-9]+$ ]] || { echo "invalid PID: $pid" >&2; exit 2; }
if tmux has-session -t "$session" 2>/dev/null; then
  echo "tmux session already exists: $session" >&2
  exit 1
fi

tmux new-session -d -s "$session" -c "$repo" "exec /usr/bin/gdb -p $pid"
tmux attach -t "$session"
```

Respect host ptrace restrictions and do not attach to an unrelated user process.

## Preserve and Hand Off

Leave GDB stopped unless explicitly asked to continue or terminate. Report:

- tmux target `session:window.pane`.
- Repository, Workspace, Step, and inferior command.
- Breakpoint file/line or function.
- Thread, frame, stop reason, and key inspected values.
- Next falsifiable question.
- Workspace outputs/configs changed by reproduction.

Inspect without disturbing the inferior:

```bash
tmux list-panes -a -F '#{session_name}:#{window_index}.#{pane_index} pid=#{pane_pid} cmd=#{pane_current_command}'
tmux capture-pane -p -t session:0.0 -S -200
```

Do not treat a short capture as complete history. Never continue, detach, or kill the session merely for cleanup.

## Diagnose Missed Breakpoints

- Pending forever: inspect `info sharedlibrary`, module `__file__`, source path, and loaded extension provenance.
- GDB follows CMake/Ninja: prebuild, pass exact `SKBUILD_EDITABLE_SKIP` paths, and keep parent-following.
- No line symbols: rebuild Debug and confirm the `.so` is not stripped.
- Host breakpoint works but kernel does not: rebuild with `-G` and use cuda-gdb.
- Failure occurs before the Step: inspect persisted absolute paths and configs; do not silently repair the artifact.
- Logger breakpoint loses locals: move to the error call site.
- Session appears idle: inspect process state, current frame, logs, and pane before calling it hung.
