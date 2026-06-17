# Wizard Stepper Navigation + IRA Tag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Make completed stepper circles clickable to jump back to any finished step, including from the done screen. (2) Change the tag assigned to Industry Reference Architecture apps from `"Target Reference"` to `"Whitespace - IRA"`.

**Architecture:** Both changes are surgical. Task 1 touches only `archimedes_wizard.html` (JS + CSS). Task 2 touches `pipeline/industry_reference.py` (one string) and `archimedes_wizard.html` (one label string).

**Tech Stack:** Vanilla JS, HTML/CSS, Python (openpyxl)

---

### Task 1: Stepper click-to-navigate

**Files:**
- Modify: `archimedes_wizard.html` — CSS block (~line 66), `renderProgress()` (~line 1367), `showDone()` (~line 2551)

No unit tests for pure UI JS — manual verification steps provided.

- [ ] **Step 1: Add CSS for clickable done steps**

Find the `.progress-step.done .step-label` block (~line 115) and add a cursor rule immediately after it:

```css
.progress-step.done  .step-label { color: var(--blue-10); font-weight: 600; }
.progress-step.active .step-label { color: var(--blue-7);  font-weight: 700; }
.progress-step.done  { cursor: pointer; }
```

- [ ] **Step 2: Add `jumpToStep` function after `renderProgress()`**

After the closing `}` of `renderProgress()` (~line 1378), insert:

```javascript
function jumpToStep(i) {
  // Only allow jumping to steps that have been visited (done) or are current
  if (i >= currentStep && i !== currentStep) return;
  currentStep = i;
  renderProgress();
  renderStep(currentStep);
  showNav();
}
```

- [ ] **Step 3: Wire `onclick` to done steps in `renderProgress()`**

Change the `renderProgress()` body so done steps get an onclick:

```javascript
function renderProgress() {
  const labels = t('steps');
  const el = document.getElementById('progress-steps');
  el.innerHTML = STEPS.map((s, i) => {
    const isDone   = i < currentStep;
    const isActive = i === currentStep;
    const cls      = isDone ? 'done' : isActive ? 'active' : '';
    const click    = isDone ? `onclick="jumpToStep(${i})"` : '';
    return `
    <div class="progress-step ${cls}" ${click}>
      <div class="step-circle">${isDone ? '✓' : i + 1}</div>
      <div class="step-label">${labels[i]}</div>
    </div>`;
  }).join('');
  document.getElementById('header-step-label').textContent =
    t('step_of', currentStep + 1, STEPS.length) + ' — ' + labels[currentStep];
}
```

- [ ] **Step 4: Make `showDone()` keep nav accessible for stepper clicks**

In `showDone()` (~line 2552), the back/skip/next buttons are all hidden. That's fine — the stepper itself is the navigation. But `currentStep = STEPS.length` means no step is "done" from the stepper's perspective (all `i < STEPS.length` are done). Verify: after `showDone()` calls `renderProgress()`, `currentStep === STEPS.length` so every step index `i` satisfies `i < currentStep` → all get `done` class and `onclick`. No change needed here.

Also update `header-step-label` in `renderProgress()` to guard against out-of-range `currentStep` (done screen sets it to `STEPS.length`):

```javascript
  if (currentStep < STEPS.length) {
    document.getElementById('header-step-label').textContent =
      t('step_of', currentStep + 1, STEPS.length) + ' — ' + labels[currentStep];
  }
  // When currentStep === STEPS.length (done screen), showDone() sets its own label — leave it alone
```

- [ ] **Step 5: Manual verification**

1. Start wizard: `python3 archimedes_wizard.py`
2. Complete at least 3 steps (Client → Catalogs → Baseline)
3. Verify circles 1 and 2 have pointer cursor on hover
4. Click circle 1 (Client) → should jump back to that step
5. Complete the full pipeline until the done screen
6. On done screen, click any previous step circle → should navigate to that step, showing its content and nav buttons

- [ ] **Step 6: Commit**

```bash
git add archimedes_wizard.html
git commit -m "feat(wizard): clickable stepper for completed steps"
```

---

### Task 2: Change IRA tag to "Whitespace - IRA"

**Files:**
- Modify: `pipeline/industry_reference.py` line ~397
- Modify: `archimedes_wizard.html` line ~2007 (label in `renderWhitespace()`)

- [ ] **Step 1: Update tag in `industry_reference.py`**

At line ~397 in `pipeline/industry_reference.py`:

```python
# Before:
tag = "Target Reference"

# After:
tag = "Whitespace - IRA"
```

- [ ] **Step 2: Update label in wizard HTML**

At line ~2007 in `archimedes_wizard.html`, inside `renderWhitespace()`:

```javascript
// Before:
Tag que se asignará: <code style="background:var(--surface);padding:2px 6px;border-radius:4px">Target Reference</code>

// After:
Tag que se asignará: <code style="background:var(--surface);padding:2px 6px;border-radius:4px">Whitespace - IRA</code>
```

- [ ] **Step 3: Manual verification**

1. In wizard Step 7 (Reference), select an industry and click Fetch
2. Select one or more whitespace items and click Apply
3. Download the generated Target Excel
4. Open it — Application sheet, `tags` column should show `Whitespace - IRA`

- [ ] **Step 4: Commit**

```bash
git add pipeline/industry_reference.py archimedes_wizard.html
git commit -m "feat(ira): rename tag to 'Whitespace - IRA'"
```

---

### Task 3: Apply same changes to `archimedes_wizard_pro.html`

**Files:**
- Modify: `archimedes_wizard_pro.html` — same CSS, JS, and label changes as Tasks 1 and 2

- [ ] **Step 1: Check if pro has `renderProgress`, `showDone`, `renderWhitespace`**

```bash
grep -n "renderProgress\|showDone\|renderWhitespace\|Target Reference" archimedes_wizard_pro.html
```

- [ ] **Step 2: Apply identical changes** from Tasks 1 and 2 to the matching locations in `archimedes_wizard_pro.html`

- [ ] **Step 3: Commit + push**

```bash
git add archimedes_wizard_pro.html
git commit -m "feat(wizard-pro): stepper nav + Whitespace-IRA tag parity"
git push
```
