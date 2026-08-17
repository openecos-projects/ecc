# خطة نهائية: State Machine Guards — ECC (v3)

## تسوية التناقضات (PHASE 0)

### التناقض 1: agent/engine.py vs flow.py

**النتيجة:** كلاهما يستخدم نفس `EngineFlow.set_state()`. state machine واحدة.

- `agent/engine.py:38` — `set_state(Ongoing)` ✓
- `agent/engine.py:112` (`_finish_step`) — `set_state(Success/Incomplete/Invalid)` ✓
- الفرق الوحيد: `agent/engine.py` يمكنه `set_state(Invalid)` من `Ongoing` ( عبر `_step_state()`)

### التناقض 2: Incomplete → Ongoing

**النتيجة:** `Incomplete` terminal في lifecycle. `Incomplete → Ongoing` يحدث **فقط** عبر batch reset.

```
Lifecycle (set_state):         Batch Reset (bypass set_state):
Incomplete → {nothing}         Incomplete → [batch] → Unstart → [set_state] → Ongoing
```

- `_invalidate_suffix()` يعيّن `step["state"] = Unstart` **بشكل مباشر** — لا يستدعي `set_state()`
- ثم `run_step()` يستدعي `set_state(Ongoing)` من `Unstart`

### التناقض 3: Invalid terminal vs clear_states()

**النتيجة:** `Invalid` terminal في جدول الانتقالات. `clear_states()` batch reset يتجاوز الجدول.

- `clear_states()` يعيّن `step["state"] = Unstart` **بشكل مباشر** — لا يستدعي `set_state()`
- `Invalid` terminal لأن `set_state()` لا يسمح بـ `Invalid → أي شيء`
- لكن `clear_states()` يمكنه تعيين `Invalid → Unstart` لأنه **يتجاوز** الجدول

---

## الجدول الموحد

### Layer 1: State Machine — `set_state()` lifecycle transitions

```python
_VALID_TRANSITIONS = {
    Unstart:    {Ongoing, Incomplete},
    Pending:    {Ongoing, Incomplete},
    Ongoing:    {Success, Incomplete, Invalid},
    Success:    {},       # terminal
    Incomplete: {},       # terminal
    Invalid:    {},       # terminal
}
```

### Layer 2: Batch Operations — تتجاوز `set_state()`

| العملية | الآلية | تتجاوز Guards؟ |
|---------|--------|----------------|
| `clear_states()` | `step["state"] = Unstart` مباشر | **نعم** |
| `_invalidate_suffix()` | `step["state"] = Unstart` مباشر | **نعم** |
| `_prepare_steps_for_rerun()` | `record.update({"state": "Unstart"})` | **نعم** |

### ملخص التسوية

| السؤال | الإجابة |
|--------|---------|
| `Incomplete → Ongoing` مباشر؟ | **ممنوع** |
| `Incomplete → Unstart` في جدول set_state؟ | **لا** — يحدث عبر batch reset |
| `Incomplete → Ongoing` في reality؟ | **يحدث** عبر `Incomplete → [batch] → Unstart → [set_state] → Ongoing` |
| `Invalid → Unstart` في جدول set_state؟ | **لا** — terminal |
| `clear_states()` يُعيّن `Invalid → Unstart`؟ | **نعم** — batch reset يتجاوز الجدول |
| `agent/engine.py` يستخدم نفس الـ machine؟ | **نعم** — يرث `EngineFlow` |

---

## PHASE 1: Audit شامل لكل callers

### Production Code — set_state() callers صحيحة

| Caller | المستحثّ | الحالة الأصلية | ملاحظات |
|--------|-----------|----------------|---------|
| `flow.py:479` | `Ongoing` | `Unstart` / `Incomplete` | `Unstart→Ongoing` ✓, `Incomplete→Ongoing` عبر batch ✓ |
| `flow.py:545` | `Success` / `Incomplete` | `Ongoing` | `Ongoing→Success` ✓, `Ongoing→Incomplete` ✓ |
| `agent/engine.py:38` | `Ongoing` | `Unstart` / `Incomplete` | نسخة من flow.py:479 ✓ |
| `agent/engine.py:112` | `Success` / `Incomplete` / `Invalid` | `Ongoing` | `Ongoing→*` ✓ |

### Production Code — direct state assignments (يجب تمريرها عبر set_state)

| الموقع | التعيين | يجب تعديله؟ |
|--------|---------|-------------|
| `flow.py:314` | `step["state"] = Incomplete` | **نعم** — `Unstart→Incomplete` مسموح |

### Production Code — batch resets (يجب **عدم** تمريرها عبر Guards)

| الموقع | العملية |
|--------|---------|
| `flow.py:183` `clear_states()` | `step["state"] = Unstart` |
| `rerun.py:108` `_invalidate_suffix()` | `step["state"] = Unstart` |
| `workspace_api.py:974` `_prepare_steps_for_rerun()` | `record.update({"state": "Unstart"})` |
| `workspace_api.py:1006` `_reset_step_subflow()` | `step.update({"state": "Unstart"})` |

### Subflow update_step() — غير متعلق

| الموقع |
|--------|
| `yosys/subflow.py:105` |
| `ecc/subflow.py:196` |
| `ecc_sizer/subflow.py:96` |
| `ecc/metrics.py:3467` |

### Test callers (يجب تعديلها)

| Caller | المشكلة |
|--------|---------|
| `test/utility/test_json.py:193,223,257` | `Unstart → Success` — يتجاوز lifecycle |
| `test/test_engine_rerun.py:54,158` | mock يتجاوز lifecycle |
| `test/formal/test_state_machine.py:253` | `Unstart → كل الحالات` |
| `test/formal/test_state_machine.py:344,351` | mock run_step |

---

## PHASE 2: تصميم Guards

### الملف: `chipcompiler/engine/flow.py`

```python
_VALID_TRANSITIONS: dict[str, set[str]] = {
    StateEnum.Unstart.value: {StateEnum.Ongoing.value, StateEnum.Imcomplete.value},
    StateEnum.Pending.value: {StateEnum.Ongoing.value, StateEnum.Imcomplete.value},
    StateEnum.Ongoing.value: {
        StateEnum.Success.value,
        StateEnum.Imcomplete.value,
        StateEnum.Invalid.value,
    },
    StateEnum.Success.value: set(),
    StateEnum.Imcomplete.value: set(),
    StateEnum.Invalid.value: set(),
}


def _validate_transition(old_state: str | None, new_state: str, step_name: str, tool: str) -> None:
    """Raise ValueError on illegal lifecycle transitions.

    Batch resets (clear_states, _invalidate_suffix) bypass this by assigning
    step["state"] directly rather than calling set_state().
    """
    if old_state is None or old_state == new_state:
        return
    allowed = _VALID_TRANSITIONS.get(old_state, set())
    if new_state not in allowed:
        raise ValueError(
            f"Illegal state transition for {step_name}/{tool}: "
            f"{old_state} → {new_state}. "
            f"Allowed transitions from {old_state}: {sorted(allowed) or 'none'}"
        )
```

### تعديل set_state()

```python
def set_state(self, name, tool, state, runtime=None, peak_memory=None):
    state_value = state.value if isinstance(state, StateEnum) else state
    for step in self.workspace.flow.data.get("steps", []):
        if step.get("name") == name and step.get("tool") == tool:
            old_state = step.get("state")
            _validate_transition(old_state, state_value, name, tool)
            step["state"] = state_value
            if runtime is not None:
                step["runtime"] = runtime
            if peak_memory is not None:
                step["peak memory (mb)"] = peak_memory
            if not self.save():
                logger.error(
                    "Failed to persist flow state for %s/%s (state=%s); "
                    "state change exists only in memory",
                    name, tool, state_value,
                )
            return True
    return False
```

### تعديل create_step_workspaces() (flow.py:314)

```python
# الحالي:
step["state"] = StateEnum.Imcomplete.value

# المقترح:
self.set_state(name=step["name"], tool=step["tool"], state=StateEnum.Imcomplete)
```

### ما الذي لا نعدّله

- `clear_states()` — batch reset
- `_invalidate_suffix()` — batch reset
- `_prepare_steps_for_rerun()` — batch reset
- Subflow `update_step()` — subflow-level

---

## PHASE 3: Resume/Rerun Verification

### --resume

```
run_resume()
  → run_from(first_non_success_step)
    → _invalidate_suffix(index)     # batch: all → Unstart
    → _run_selected()
      → flow.run_step(step, rerun=True)
        → set_state(Ongoing)        # lifecycle: Unstart → Ongoing ✓
        → set_state(Success)        # lifecycle: Ongoing → Success ✓
```

### --from

نفس `--resume`. ✓

### --only

```
run_only()
  → _invalidate_suffix(index)       # batch
  → _run_selected()
    → flow.run_step(step, rerun=True)
      → set_state(Ongoing)          # Unstart → Ongoing ✓
      → set_state(Success/Incomplete) # Ongoing → ✓
```

### --force

يُستخدم فقط مع `--only`. يتجاوز فحص Success في `selected_step_names()`. لا يؤثر على guards. ✓

### workspace_api _prepare_steps_for_rerun()

```python
record.update({"state": "Unstart", ...})  # batch reset ✓
```

---

## PHASE 4: Formal Tests Updates

### XFAIL #1: test_no_invalid_transition_allowed (test_state_machine.py:91)

- **بعد التنفيذ:** يتحول إلى PASSED
- `_code_transition_constraint` يمثل الجدول الجديد

### XFAIL #2: test_terminal_unreachable_without_ongoing (test_state_machine.py:124)

- **بعد التنفيذ:** يتحول إلى PASSED
- `_code_transition_constraint` يرفض `Unstart → Success`

### XFAIL #3: test_chain_breaks_on_failure (test_file_chaining.py:101)

- **يبقى XFAIL** — الكود يتوقف عند الفشل (لا downstream steps)
- تحديث الـ model ليعكس `break` behavior

### XFAIL #4: test_no_stale_output_propagation (test_file_chaining.py:222)

- **يبقى XFAIL** — downstream steps لا تُنشأ عند الفشل
- تحديث الـ model

### XFAIL #5: test_key_spelling_matches_template (test_param_propagation.py:62)

- لا علاقة له بـ state machine — يبقى كما هو

---

## PHASE 5: Regression Tests

```python
# === Lifecycle transitions ===

def test_valid_unstart_to_ongoing():
    flow.set_state("step", "tool", StateEnum.Ongoing)  # ✓

def test_valid_ongoing_to_success():
    flow.set_state("step", "tool", StateEnum.Ongoing)
    flow.set_state("step", "tool", StateEnum.Success)  # ✓

def test_valid_ongoing_to_incomplete():
    flow.set_state("step", "tool", StateEnum.Ongoing)
    flow.set_state("step", "tool", StateEnum.Imcomplete)  # ✓

def test_valid_ongoing_to_invalid():
    flow.set_state("step", "tool", StateEnum.Ongoing)
    flow.set_state("step", "tool", StateEnum.Invalid)  # ✓

def test_valid_unstart_to_incomplete():
    flow.set_state("step", "tool", StateEnum.Imcomplete)  # ✓

# === Rejection ===

def test_reject_unstart_to_success():
    with pytest.raises(ValueError, match="Illegal state transition"):
        flow.set_state("step", "tool", StateEnum.Success)

def test_reject_unstart_to_invalid():
    with pytest.raises(ValueError, match="Illegal state transition"):
        flow.set_state("step", "tool", StateEnum.Invalid)

def test_reject_success_to_ongoing():
    flow.set_state("step", "tool", StateEnum.Success)
    with pytest.raises(ValueError, match="Illegal state transition"):
        flow.set_state("step", "tool", StateEnum.Ongoing)

def test_reject_incomplete_to_success():
    flow.set_state("step", "tool", StateEnum.Imcomplete)
    with pytest.raises(ValueError, match="Illegal state transition"):
        flow.set_state("step", "tool", StateEnum.Success)

def test_reject_invalid_to_any():
    step = flow.get_step("step", "tool")
    step["state"] = StateEnum.Invalid.value
    for target in [StateEnum.Unstart, StateEnum.Ongoing, StateEnum.Success, StateEnum.Incomplete]:
        with pytest.raises(ValueError, match="Illegal state transition"):
            flow.set_state("step", "tool", target)

def test_reject_ongoing_to_unstart():
    flow.set_state("step", "tool", StateEnum.Ongoing)
    with pytest.raises(ValueError, match="Illegal state transition"):
        flow.set_state("step", "tool", StateEnum.Unstart)

# === Idempotent ===

def test_idempotent_update_allowed():
    flow.set_state("step", "tool", StateEnum.Ongoing)
    flow.set_state("step", "tool", StateEnum.Ongoing)  # no error

# === Batch resets bypass guards ===

def test_clear_states_bypasses_guards():
    flow.set_state("step", "tool", StateEnum.Success)
    flow.clear_states()
    assert flow.get_step("step", "tool")["state"] == StateEnum.Unstart.value

def test_clear_states_resets_invalid():
    # Set Invalid directly — set_state() would reject it
    step = flow.get_step("step", "tool")
    step["state"] = StateEnum.Invalid.value
    flow.save()
    flow.clear_states()
    assert flow.get_step("step", "tool")["state"] == StateEnum.Unstart.value

# === Persistence ===

def test_rejected_transition_does_not_persist(tmp_path):
    original = json.loads(flow_path.read_text())
    with pytest.raises(ValueError):
        flow.set_state("step", "tool", StateEnum.Success)
    assert json.loads(flow_path.read_text()) == original

# === Resume/rerun ===

def test_resume_after_incomplete(tmp_path):
    # Setup: Synthesis=Success, place=Incomplete, CTS=Unstart
    # resume re-runs place and CTS
    ...

def test_rerun_from_step_invalidates_downstream(tmp_path):
    # --from X invalidates X and following to Unstart
    ...

def test_only_force_reruns_successful_step(tmp_path):
    # --only X --force re-runs a successful step
    ...
```

---

## PHASE 6: التقرير النهائي

| البند | التفاصيل |
|-------|----------|
| **الملف الرئيسي** | `chipcompiler/engine/flow.py` |
| **الملفات المعدّلة** | `test/formal/test_state_machine.py`, `test/formal/test_file_chaining.py`, `test/test_engine_flow.py`, `test/test_engine_rerun.py`, `test/utility/test_json.py` |
| **التغيير الرئيسي** | `set_state()` يرفض انتقالات غير صالحة مع `ValueError` |
| **التمييز** | `set_state()` = lifecycle transitions, `clear_states()`/`_invalidate_suffix()` = batch resets |
| **الانتقالات المرفوضة** | `Unstart→Success`, `Unstart→Invalid`, `Ongoing→Unstart`, `Success→*`, `Incomplete→*`, `Invalid→*` |
| **Invalid** | Terminal في lifecycle — batch reset يمكنه تعيينه لـ Unstart |
| **Incomplete** | Terminal في lifecycle — batch reset يمكنه تعيينه لـ Unstart |
| **Tests المُضافة** | ~15 regression test |
| **Tests المعدّلة** | ~4 formal + ~5 test callers |
| **XFAIL المتبقية** | 3 (chain_breaks, stale_output, key_spelling) |
| **المخاطر** | منخفضة |
