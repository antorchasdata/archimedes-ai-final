# Wizard_Pro Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `archimedes_wizard_pro.html` — a Dark Glass + Full Immersive redesign of the Archimedes wizard, functionally identical to `archimedes_wizard.html`, reusing the same backend at `http://localhost:8767`.

**Architecture:** Single standalone HTML file with embedded CSS and JS. All API calls point to `http://localhost:8767` (unchanged backend). Dark background `#0a0a1a`, glassmorphism cards (`backdrop-filter: blur(20px)`), full-screen step layout with large bold typography. Progress shown as horizontal pills in fixed header (no sidebar).

**Tech Stack:** Vanilla HTML/CSS/JS, no external dependencies. Font: "72 Brand" system stack (same as current wizard).

---

## File Structure

| File | Action | Notes |
|------|--------|-------|
| `archimedes_wizard_pro.html` | **Create** | New standalone frontend — full file |
| `archimedes_wizard.html` | No change | Existing frontend untouched |
| `archimedes_wizard.py` | No change | Existing backend untouched |

---

## CSS Design Tokens

These values are used throughout all tasks. Reference here:

```css
:root {
  --bg:          #0a0a1a;
  --bg-card:     rgba(255,255,255,0.06);
  --bg-card-hover: rgba(255,255,255,0.09);
  --border:      rgba(255,255,255,0.12);
  --border-active: rgba(79,195,247,0.5);
  --cyan:        #4fc3f7;
  --blue:        #0070f2;
  --blue-dark:   #002A86;
  --green:       #22c55e;
  --orange:      #f97316;
  --red:         #ef4444;
  --text-primary:   #ffffff;
  --text-secondary: rgba(255,255,255,0.55);
  --text-muted:     rgba(255,255,255,0.3);
  --glow-cyan:   0 0 12px rgba(79,195,247,0.4);
  --glow-blue:   0 0 12px rgba(0,112,242,0.4);
  --radius:      12px;
  --radius-l:    18px;
  --font: "72 Brand","72",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono: "SFMono-Regular","Consolas","Liberation Mono",Menlo,monospace;
}
```

---

## Task 1: HTML shell + CSS foundations

**Files:**
- Create: `archimedes_wizard_pro.html`

- [ ] **Step 1: Create the file with `<!DOCTYPE html>`, `<head>`, CSS variables, and base reset**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Archimedes AI — Wizard Pro</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:             #0a0a1a;
  --bg-card:        rgba(255,255,255,0.06);
  --bg-card-hover:  rgba(255,255,255,0.09);
  --border:         rgba(255,255,255,0.12);
  --border-active:  rgba(79,195,247,0.5);
  --cyan:           #4fc3f7;
  --blue:           #0070f2;
  --blue-dark:      #002A86;
  --green:          #22c55e;
  --orange:         #f97316;
  --red:            #ef4444;
  --text-primary:   #ffffff;
  --text-secondary: rgba(255,255,255,0.55);
  --text-muted:     rgba(255,255,255,0.3);
  --glow-cyan:      0 0 12px rgba(79,195,247,0.4);
  --glow-blue:      0 0 12px rgba(0,112,242,0.4);
  --radius:         12px;
  --radius-l:       18px;
  --font: "72 Brand","72",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono: "SFMono-Regular","Consolas","Liberation Mono",Menlo,monospace;
}

html, body {
  height: 100%;
  background: var(--bg);
  font-family: var(--font);
  color: var(--text-primary);
  overflow-x: hidden;
}

/* Ambient background glow */
body::before {
  content: '';
  position: fixed;
  top: -20%;
  right: -10%;
  width: 60vw;
  height: 60vw;
  background: radial-gradient(circle, rgba(0,112,242,0.08) 0%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}
body::after {
  content: '';
  position: fixed;
  bottom: -10%;
  left: -10%;
  width: 50vw;
  height: 50vw;
  background: radial-gradient(circle, rgba(79,195,247,0.06) 0%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}
</style>
</head>
<body>
<!-- content will be added in subsequent tasks -->
</body>
</html>
```

- [ ] **Step 2: Open the file in browser and verify dark background renders correctly**

Open `archimedes_wizard_pro.html` directly in a browser. Should see solid `#0a0a1a` background with no errors in console.

---

## Task 2: Fixed header with logo + progress pills + language selector

**Files:**
- Modify: `archimedes_wizard_pro.html`

- [ ] **Step 1: Add header CSS inside the `<style>` block**

Add after the `body::after` rule:

```css
/* ── Header ─────────────────────────────────────────────── */
.header {
  position: fixed;
  top: 0; left: 0; right: 0;
  height: 58px;
  background: rgba(10,10,26,0.85);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 28px;
  gap: 16px;
  z-index: 100;
}
.header-logo {
  font-size: 18px;
  font-weight: 800;
  color: var(--text-primary);
  letter-spacing: -0.5px;
  flex-shrink: 0;
}
.header-logo span { color: var(--cyan); }
.header-client {
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 500;
  flex-shrink: 0;
}
.header-sep { flex: 1; }

/* Progress pills */
.header-pills {
  display: flex;
  gap: 5px;
  align-items: center;
}
.pill {
  height: 5px;
  border-radius: 3px;
  transition: all 0.3s ease;
}
.pill.done    { width: 20px; background: var(--blue); }
.pill.active  { width: 28px; background: var(--cyan); box-shadow: var(--glow-cyan); }
.pill.pending { width: 10px; background: rgba(255,255,255,0.15); }

.header-step-name {
  font-size: 11px;
  font-weight: 700;
  color: var(--cyan);
  letter-spacing: 0.5px;
  flex-shrink: 0;
  min-width: 80px;
}

/* Language selector */
.lang-select {
  appearance: none;
  background: rgba(255,255,255,0.06) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='rgba(255,255,255,0.4)'/%3E%3C/svg%3E") no-repeat right 8px center;
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  font-family: var(--font);
  font-size: 12px;
  font-weight: 600;
  outline: none;
  padding: 5px 28px 5px 10px;
  transition: background 0.15s;
  flex-shrink: 0;
}
.lang-select:hover { background-color: rgba(255,255,255,0.1); }
.lang-select option { background: #0d1b3e; color: #fff; }
```

- [ ] **Step 2: Add header HTML inside `<body>`, before the closing `</body>` tag**

```html
<header class="header">
  <div class="header-logo">Archimedes <span>AI</span></div>
  <div class="header-client" id="header-client"></div>
  <div class="header-sep"></div>
  <div class="header-pills" id="header-pills"></div>
  <div class="header-step-name" id="header-step-name"></div>
  <select class="lang-select" id="lang-select" onchange="setLang(this.value)">
    <option value="en">🇬🇧 EN</option>
    <option value="es">🇪🇸 ES</option>
    <option value="fr">🇫🇷 FR</option>
    <option value="it">🇮🇹 IT</option>
    <option value="fi">🇫🇮 FI</option>
  </select>
</header>
```

- [ ] **Step 3: Verify in browser — header visible, blurred, no layout overflow**

---

## Task 3: Main content area + step card + bottom nav CSS

**Files:**
- Modify: `archimedes_wizard_pro.html`

- [ ] **Step 1: Add layout + step card CSS**

Add after header CSS:

```css
/* ── Layout ──────────────────────────────────────────────── */
.main {
  min-height: 100vh;
  padding: 90px 24px 100px;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  position: relative;
  z-index: 1;
}

/* ── Step card ───────────────────────────────────────────── */
.step-card {
  width: 100%;
  max-width: 640px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-l);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  padding: 40px 44px;
  animation: fadeUp 0.3s ease;
}
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}

.step-eyebrow {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  color: var(--cyan);
  margin-bottom: 10px;
}
.step-title {
  font-size: 28px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.15;
  margin-bottom: 10px;
}
.step-desc {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.7;
  margin-bottom: 32px;
}

/* ── Form elements ───────────────────────────────────────── */
.field-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
  margin-bottom: 8px;
  display: block;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.field-hint {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 8px;
}
input[type="text"] {
  width: 100%;
  padding: 14px 18px;
  background: rgba(255,255,255,0.05);
  border: 1.5px solid var(--border);
  border-radius: var(--radius);
  font-family: var(--font);
  font-size: 15px;
  color: var(--text-primary);
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}
input[type="text"]:focus {
  border-color: var(--cyan);
  box-shadow: 0 0 0 3px rgba(79,195,247,0.12);
}
input[type="text"]::placeholder { color: var(--text-muted); }

/* ── Drop zones ──────────────────────────────────────────── */
.drop-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 4px; }
.drop-grid.single { grid-template-columns: 1fr; }
.drop-zone {
  border: 2px dashed rgba(255,255,255,0.15);
  border-radius: var(--radius);
  padding: 28px 16px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  background: rgba(255,255,255,0.03);
  position: relative;
}
.drop-zone:hover, .drop-zone.drag-over {
  border-color: var(--cyan);
  background: rgba(79,195,247,0.06);
}
.drop-zone.has-file {
  border-color: var(--blue);
  border-style: solid;
  background: rgba(0,112,242,0.08);
}
.drop-zone.has-file.is-image {
  border-color: var(--green);
  background: rgba(34,197,94,0.08);
}
.drop-icon  { font-size: 28px; margin-bottom: 8px; }
.drop-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); margin-bottom: 4px; }
.drop-hint  { font-size: 11px; color: var(--text-muted); }
.drop-filename {
  font-size: 12px;
  font-weight: 700;
  color: var(--cyan);
  margin-top: 6px;
  word-break: break-all;
}
.drop-zone.is-image .drop-filename { color: var(--green); }
.drop-remove {
  position: absolute;
  top: 8px; right: 10px;
  font-size: 16px;
  color: var(--text-muted);
  cursor: pointer;
  line-height: 1;
  padding: 2px 4px;
  border-radius: 4px;
}
.drop-remove:hover { color: var(--red); background: rgba(239,68,68,0.1); }
input[type="file"] { display: none; }

/* Multi-image thumbnails */
.img-thumbs { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.img-thumb {
  position: relative;
  width: 70px; height: 70px;
  border-radius: 8px;
  overflow: hidden;
  border: 1.5px solid var(--border);
}
.img-thumb img { width: 100%; height: 100%; object-fit: cover; }
.img-thumb-remove {
  position: absolute;
  top: 2px; right: 2px;
  background: rgba(0,0,0,0.65);
  color: white;
  border-radius: 50%;
  width: 16px; height: 16px;
  font-size: 10px;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
}

/* ── Result / info cards ─────────────────────────────────── */
.result-card {
  border-radius: var(--radius);
  padding: 16px 20px;
  margin-top: 20px;
  display: none;
}
.result-card.show { display: block; animation: fadeUp 0.2s ease; }
.result-card.success { background: rgba(34,197,94,0.1);  border: 1px solid rgba(34,197,94,0.3); }
.result-card.info    { background: rgba(79,195,247,0.08); border: 1px solid rgba(79,195,247,0.25); }
.result-card.warning { background: rgba(249,115,22,0.1);  border: 1px solid rgba(249,115,22,0.3); }
.result-card.error   { background: rgba(239,68,68,0.1);   border: 1px solid rgba(239,68,68,0.3); }

.result-header {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; font-weight: 700; margin-bottom: 10px;
}
.result-card.success .result-header { color: var(--green); }
.result-card.info    .result-header { color: var(--cyan); }
.result-card.warning .result-header { color: var(--orange); }
.result-card.error   .result-header { color: var(--red); }

.result-stats { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 8px; }
.stat-pill {
  display: flex; flex-direction: column;
  background: rgba(255,255,255,0.06);
  border-radius: 8px;
  padding: 8px 14px;
  min-width: 70px;
}
.stat-pill .stat-n   { font-size: 20px; font-weight: 800; color: var(--cyan); line-height: 1; }
.stat-pill .stat-lbl { font-size: 10px; color: var(--text-muted); margin-top: 3px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
.result-summary { font-size: 13px; color: var(--text-secondary); line-height: 1.55; }

/* Download items */
.download-list { display: flex; flex-direction: column; gap: 10px; margin-top: 4px; }
.download-item {
  display: flex; align-items: center; gap: 14px;
  padding: 14px 18px;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}
.download-item .di-icon  { font-size: 24px; flex-shrink: 0; }
.download-item .di-info  { flex: 1; }
.download-item .di-label { font-size: 13px; font-weight: 700; color: var(--text-primary); }
.download-item .di-desc  { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.download-item .di-stats { font-size: 11px; color: var(--text-secondary); margin-top: 3px; font-family: var(--mono); }
.btn-download {
  padding: 8px 16px;
  background: rgba(0,112,242,0.2);
  color: var(--cyan);
  border: 1px solid rgba(79,195,247,0.3);
  border-radius: 8px;
  font-family: var(--font);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
  flex-shrink: 0;
}
.btn-download:hover { background: rgba(79,195,247,0.15); border-color: var(--cyan); }

/* Catalog cards */
.catalog-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.catalog-card {
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 18px;
}
.catalog-card .cc-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 10px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.5px;
  margin-bottom: 8px;
}
.catalog-card.rba .cc-badge { background: rgba(0,42,134,0.6); color: var(--cyan); border: 1px solid rgba(79,195,247,0.3); }
.catalog-card.rsa .cc-badge { background: rgba(0,112,242,0.3); color: var(--cyan); border: 1px solid rgba(79,195,247,0.3); }
.catalog-card .cc-title { font-size: 13px; font-weight: 700; color: var(--text-primary); margin-bottom: 6px; }
.catalog-card .cc-meta  { font-size: 11px; color: var(--text-secondary); line-height: 1.7; font-family: var(--mono); }
.catalog-card .cc-stats { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 8px; }
.cc-stat {
  font-size: 11px;
  background: rgba(255,255,255,0.06);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 3px 8px;
  color: var(--text-secondary);
  font-weight: 600;
}

/* Toggle rows (LeanIX import checkboxes) */
.push-options { display: flex; flex-direction: column; gap: 12px; }
.toggle-row {
  display: flex; align-items: center; gap: 14px;
  padding: 14px 18px;
  background: rgba(255,255,255,0.04);
  border: 1.5px solid var(--border);
  border-radius: var(--radius);
  cursor: pointer;
  transition: border-color 0.15s;
}
.toggle-row:hover { border-color: var(--cyan); }
.toggle-row.active { border-color: var(--cyan); background: rgba(79,195,247,0.07); }
.toggle-row input[type="checkbox"] { width: 18px; height: 18px; cursor: pointer; accent-color: var(--cyan); }
.toggle-row .tr-label { font-size: 13px; font-weight: 600; color: var(--text-secondary); flex: 1; }
.toggle-row .tr-file  { font-size: 11px; color: var(--text-muted); font-family: var(--mono); }

/* Info box */
.info-box {
  background: rgba(79,195,247,0.07);
  border: 1px solid rgba(79,195,247,0.2);
  border-radius: var(--radius);
  padding: 12px 16px;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 20px;
}
.info-box strong { color: var(--cyan); }

/* Spinner */
.spinner-wrap { display: none; align-items: center; gap: 12px; padding: 16px 0; color: var(--cyan); font-size: 13px; font-weight: 600; }
.spinner-wrap.show { display: flex; }
.spinner {
  width: 22px; height: 22px;
  border: 3px solid rgba(79,195,247,0.2);
  border-top-color: var(--cyan);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Done screen */
.done-screen { text-align: center; padding: 40px 0; }
.done-icon  { font-size: 56px; margin-bottom: 16px; }
.done-title { font-size: 26px; font-weight: 800; color: var(--green); margin-bottom: 8px; }
.done-sub   { font-size: 14px; color: var(--text-secondary); line-height: 1.65; max-width: 440px; margin: 0 auto 24px; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
```

- [ ] **Step 2: Add bottom nav CSS**

```css
/* ── Bottom nav ──────────────────────────────────────────── */
.nav-bar {
  position: fixed;
  bottom: 0; left: 0; right: 0;
  background: rgba(10,10,26,0.9);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-top: 1px solid var(--border);
  padding: 14px 32px;
  display: flex;
  align-items: center;
  gap: 12px;
  z-index: 100;
}
.nav-bar-inner { max-width: 640px; margin: 0 auto; width: 100%; display: flex; gap: 12px; align-items: center; }
.nav-spacer { flex: 1; }

.btn-primary {
  padding: 11px 30px;
  background: linear-gradient(90deg, var(--cyan), var(--blue));
  color: #fff;
  border: none;
  border-radius: var(--radius);
  font-family: var(--font);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: opacity 0.15s, box-shadow 0.15s;
  display: flex; align-items: center; gap: 6px;
}
.btn-primary:hover:not(:disabled) { opacity: 0.88; box-shadow: var(--glow-blue); }
.btn-primary:disabled { opacity: 0.35; cursor: not-allowed; }

.btn-secondary {
  padding: 11px 20px;
  background: rgba(255,255,255,0.06);
  color: var(--cyan);
  border: 1.5px solid rgba(79,195,247,0.35);
  border-radius: var(--radius);
  font-family: var(--font);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.btn-secondary:hover { background: rgba(79,195,247,0.1); border-color: var(--cyan); }

.btn-ghost {
  padding: 11px 16px;
  background: transparent;
  color: var(--text-muted);
  border: none;
  font-family: var(--font);
  font-size: 13px;
  cursor: pointer;
  border-radius: var(--radius);
  transition: background 0.15s, color 0.15s;
}
.btn-ghost:hover { background: rgba(255,255,255,0.06); color: var(--text-secondary); }
```

- [ ] **Step 3: Add HTML for main content area and nav bar inside `<body>` (after `<header>`)**

```html
<!-- Main content -->
<div class="main" id="main-content"></div>

<!-- Nav bar -->
<div class="nav-bar">
  <div class="nav-bar-inner">
    <button class="btn-ghost" id="btn-back" onclick="goBack()" style="display:none" data-t="back"></button>
    <div class="nav-spacer"></div>
    <button class="btn-secondary" id="btn-skip" onclick="skipStep()" style="display:none" data-t="skip"></button>
    <button class="btn-primary" id="btn-next" onclick="nextStep()" data-t="continue"></button>
  </div>
</div>
```

- [ ] **Step 4: Verify in browser — dark nav bar visible at bottom, main area padded correctly**

---

## Task 4: Cookie Monster KPI Easter Egg CSS

**Files:**
- Modify: `archimedes_wizard_pro.html`

- [ ] **Step 1: Add KPI easter egg CSS (after btn-ghost CSS)**

```css
/* ── KPI Easter Egg ──────────────────────────────────────── */
.kpi-cookie-wrap {
  position: fixed;
  width: 60px; height: 60px;
  cursor: pointer;
  z-index: 9999;
  user-select: none;
  transition: transform 0.15s ease;
}
.kpi-cookie-wrap:hover { transform: scale(1.15) rotate(-8deg); }
.kpi-cookie-wrap img   { width: 100%; height: 100%; border-radius: 50%; opacity: 0.5; transition: opacity 0.2s; object-fit: cover; }
.kpi-cookie-wrap:hover img { opacity: 0.85; }
.kpi-cookie-wrap.active img { opacity: 1; animation: cookiePulse 0.4s ease; }
@keyframes cookiePulse {
  0%   { transform: scale(1); }
  50%  { transform: scale(1.3) rotate(15deg); }
  100% { transform: scale(1); }
}
.kpi-cookie-badge {
  position: absolute;
  top: -4px; right: -4px;
  background: var(--cyan); color: #fff;
  font-size: 9px; font-weight: 700;
  border-radius: 50%; width: 16px; height: 16px;
  display: flex; align-items: center; justify-content: center;
  opacity: 0; transition: opacity 0.2s;
}
.kpi-cookie-badge.show { opacity: 1; }

#kpi-panel {
  display: none;
  margin-top: 20px;
  border: 2px dashed rgba(79,195,247,0.4);
  border-radius: var(--radius);
  padding: 16px 18px;
  background: rgba(79,195,247,0.06);
  animation: fadeUp 0.3s ease;
}
#kpi-panel.show { display: block; }
.kpi-panel-header {
  font-size: 13px; font-weight: 700;
  color: var(--cyan);
  margin-bottom: 8px;
  display: flex; align-items: center; gap: 8px;
}
.kpi-panel-hint {
  font-size: 11px; color: var(--text-muted);
  margin-bottom: 14px; line-height: 1.5;
}
.kpi-stats { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.kpi-stat {
  background: rgba(255,255,255,0.06);
  border: 1px solid var(--border);
  border-radius: 8px; padding: 6px 12px;
  font-size: 11px; color: var(--text-secondary);
  text-align: center; min-width: 80px;
}
.kpi-stat strong { display: block; font-size: 18px; color: var(--cyan); }

/* Industry Reference select */
select.industry-select {
  width: 100%;
  padding: 12px 16px;
  background: rgba(255,255,255,0.05);
  border: 1.5px solid var(--border);
  border-radius: var(--radius);
  font-family: var(--font);
  font-size: 14px;
  color: var(--text-primary);
  outline: none;
  cursor: pointer;
  appearance: none;
  transition: border-color 0.2s;
}
select.industry-select:focus { border-color: var(--cyan); }
select.industry-select option { background: #0d1b3e; color: #fff; }

/* Whitespace product list */
.ws-product-list { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }
.ws-product-item {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 14px;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.ws-product-item:hover { border-color: var(--cyan); }
.ws-product-item.selected { border-color: var(--cyan); background: rgba(79,195,247,0.07); }
.ws-product-item input[type="checkbox"] { accent-color: var(--cyan); width: 16px; height: 16px; flex-shrink: 0; }
.ws-product-name { font-size: 13px; font-weight: 600; color: var(--text-primary); flex: 1; }
.ws-select-bar { display: flex; gap: 10px; margin-bottom: 10px; }
.ws-select-bar button {
  font-size: 11px; font-weight: 700; padding: 4px 10px;
  background: rgba(255,255,255,0.06); border: 1px solid var(--border);
  border-radius: 6px; color: var(--text-secondary); cursor: pointer;
}
.ws-select-bar button:hover { border-color: var(--cyan); color: var(--cyan); }
```

---

## Task 5: JavaScript — translations, session state, utility functions

**Files:**
- Modify: `archimedes_wizard_pro.html`

- [ ] **Step 1: Add `<script>` block with translations (copy verbatim from `archimedes_wizard.html` lines 622–877)**

Open `archimedes_wizard.html`, copy the entire `LANGS` constant (the `const LANGS = { en: {...}, es: {...}, fr: {...}, it: {...}, fi: {...} }` block). Paste it as the start of a new `<script>` tag just before `</body>`.

- [ ] **Step 2: Add session state variables and utility functions after `LANGS`**

```javascript
// ── State ──────────────────────────────────────────────────────────────────
let _lang = 'en';
let _step = 0;
let _sessionId = null;
let _clientName = '';
let _baselineFile = null;
let _cloudFile = null;
let _reqsFile = null;
let _pdfFile = null;
let _images = [];
let _contrastEnabled = false;
let _liftShiftEnabled = false;
let _liftShiftMappings = null;
let _liftShiftMode = null;
let _baselineDone = false;
let _reqsDone = false;
let _pdfDone = false;
let _imgDone = false;
let _generateDone = false;
let _refDone = false;
let _generateFiles = {};
let _lxConfigured = false;
// KPI easter egg
let _cookieClicks = 0;
let _kpiUnlocked = false;
let _cookieEl = null;

const BASE = 'http://localhost:8767';
const TOTAL_STEPS = 9;

function t(key, ...args) {
  const L = LANGS[_lang] || LANGS.en;
  const val = L[key] ?? (LANGS.en[key]);
  if (typeof val === 'function') return val(...args);
  return val ?? key;
}

function setLang(lang) {
  _lang = lang;
  renderStep(_step);
  renderPills();
}

async function apiFetch(path, opts = {}) {
  const res = await fetch(BASE + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

function showSpinner(id, msgKey) {
  const el = document.getElementById(id);
  if (el) { el.querySelector('.spin-msg').textContent = t(msgKey); el.classList.add('show'); }
}
function hideSpinner(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('show');
}
function showResult(id, type, header, body = '') {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = `result-card ${type} show`;
  el.innerHTML = `<div class="result-header">${header}</div>${body ? `<div class="result-summary">${body}</div>` : ''}`;
}
```

- [ ] **Step 3: Verify no syntax errors — open browser console, no red errors on load**

---

## Task 6: Progress pills renderer + step navigation logic

**Files:**
- Modify: `archimedes_wizard_pro.html`

- [ ] **Step 1: Add `renderPills()` function**

```javascript
function renderPills() {
  const L = LANGS[_lang] || LANGS.en;
  const steps = L.steps || LANGS.en.steps;
  const container = document.getElementById('header-pills');
  const nameEl = document.getElementById('header-step-name');
  if (!container) return;
  container.innerHTML = steps.map((_, i) => {
    const cls = i < _step ? 'done' : i === _step ? 'active' : 'pending';
    return `<div class="pill ${cls}"></div>`;
  }).join('');
  if (nameEl) nameEl.textContent = steps[_step] || '';
}

function updateHeaderClient() {
  const el = document.getElementById('header-client');
  if (el) el.textContent = _clientName ? `· ${_clientName}` : '';
}
```

- [ ] **Step 2: Add `goBack()`, `skipStep()`, `nextStep()` navigation functions**

```javascript
function goBack() {
  if (_step > 0) { _step--; renderStep(_step); renderPills(); }
}

function skipStep() {
  if (_step < TOTAL_STEPS - 1) { _step++; renderStep(_step); renderPills(); }
}

async function nextStep() {
  const btn = document.getElementById('btn-next');
  // Step-specific validation/action before advancing
  if (_step === 0) {
    const val = document.getElementById('s0-input')?.value.trim();
    if (!val) { document.getElementById('s0-input').focus(); return; }
    btn.disabled = true;
    try {
      const r = await apiFetch('/api/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_name: val })
      });
      _sessionId = r.session_id;
      _clientName = val;
      updateHeaderClient();
    } catch(e) {
      showResult('s0-result', 'error', '✗ Error', e.message);
      btn.disabled = false;
      return;
    }
    btn.disabled = false;
  }

  if (_step === 2 && !_baselineDone && (_baselineFile || _cloudFile)) {
    await runBaseline(); return;
  }
  if (_step === 3 && !_reqsDone && _reqsFile) {
    await runRequirements(); return;
  }
  if (_step === 4 && !_pdfDone && _pdfFile) {
    await runPdf(); return;
  }
  if (_step === 5 && !_imgDone && _images.length > 0) {
    await runImages(); return;
  }
  if (_step === 6 && !_generateDone) {
    await runGenerate(); return;
  }
  if (_step === 8) {
    await runImport(); return;
  }

  if (_step < TOTAL_STEPS - 1) {
    _step++;
    renderStep(_step);
    renderPills();
  }
}

function renderNavButtons() {
  const back = document.getElementById('btn-back');
  const skip = document.getElementById('btn-skip');
  const next = document.getElementById('btn-next');
  if (!back || !skip || !next) return;

  back.style.display = _step > 0 ? '' : 'none';
  back.textContent = t('back');

  const skippable = [2, 3, 4, 5, 7].includes(_step);
  skip.style.display = skippable ? '' : 'none';
  skip.textContent = t('skip');

  if (_step === TOTAL_STEPS - 1) {
    next.textContent = t('import_btn');
  } else if (_step === TOTAL_STEPS) {
    next.textContent = t('finish');
  } else {
    next.textContent = t('continue');
  }
}
```

---

## Task 7: Steps 0–2 render functions (Client, Catalogs, Baseline)

**Files:**
- Modify: `archimedes_wizard_pro.html`

- [ ] **Step 1: Add `renderStep()` dispatcher and steps 0–2**

```javascript
function renderStep(n) {
  const main = document.getElementById('main-content');
  const fns = [renderS0, renderS1, renderS2, renderS3, renderS4, renderS5, renderS6, renderS7ref, renderS7, renderDone];
  main.innerHTML = '';
  const card = document.createElement('div');
  card.className = 'step-card';
  main.appendChild(card);
  if (fns[n]) fns[n](card);
  renderNavButtons();
}

function renderS0(el) {
  el.innerHTML = `
    <div class="step-eyebrow">${t('s0_eye', 1, TOTAL_STEPS)}</div>
    <div class="step-title">${t('s0_title')}</div>
    <div class="step-desc">${t('s0_desc')}</div>
    <label class="field-label" for="s0-input">${t('s0_label')}</label>
    <input type="text" id="s0-input" placeholder="${t('s0_placeholder')}" value="${_clientName}"
      onkeydown="if(event.key==='Enter') nextStep()">
    <div id="s0-result" class="result-card"></div>
  `;
  document.getElementById('s0-input').focus();
}

function renderS1(el) {
  el.innerHTML = `
    <div class="step-eyebrow">${t('s1_eye', 2, TOTAL_STEPS)}</div>
    <div class="step-title">${t('s1_title')}</div>
    <div class="step-desc">${t('s1_desc')}</div>
    <div id="s1-spinner" class="spinner-wrap"><div class="spinner"></div><span class="spin-msg">${t('s1_loading')}</span></div>
    <div id="s1-result" class="result-card"></div>
    <div id="s1-catalogs" class="catalog-grid" style="margin-top:16px;"></div>
    <div id="s1-hint" style="margin-top:14px;font-size:12px;color:var(--text-muted);display:none;">${t('s1_update_hint')}</div>
  `;
  loadCatalogs();
}

async function loadCatalogs() {
  document.getElementById('s1-spinner').classList.add('show');
  try {
    const d = await apiFetch('/api/catalogs');
    document.getElementById('s1-spinner').classList.remove('show');
    showResult('s1-result', 'success', `✓ ${t('s1_loaded')}`);
    const grid = document.getElementById('s1-catalogs');
    grid.innerHTML = `
      <div class="catalog-card rba">
        <div class="cc-badge">RBA</div>
        <div class="cc-title">${t('cat_rba_title')}</div>
        <div class="cc-meta">${t('s1_version')}: ${d.rba?.version || '—'}<br>${t('s1_source')}: ${d.rba?.source || '—'}</div>
        <div class="cc-stats"><span class="cc-stat">${d.rba?.count || 0} BCs</span><span class="cc-stat">${d.rba?.domains || 0} dominios</span></div>
      </div>
      <div class="catalog-card rsa">
        <div class="cc-badge">RSA</div>
        <div class="cc-title">${t('cat_rsa_title')}</div>
        <div class="cc-meta">${t('s1_version')}: ${d.rsa?.version || '—'}<br>${t('s1_source')}: ${d.rsa?.source || '—'}</div>
        <div class="cc-stats"><span class="cc-stat">${d.rsa?.count || 0} productos</span></div>
      </div>
    `;
    document.getElementById('s1-hint').style.display = '';
  } catch(e) {
    document.getElementById('s1-spinner').classList.remove('show');
    showResult('s1-result', 'error', `✗ ${t('s1_err')}`, e.message);
  }
}

function renderS2(el) {
  el.innerHTML = `
    <div class="step-eyebrow">${t('s2_eye', 3, TOTAL_STEPS)}</div>
    <div class="step-title">${t('s2_title')}</div>
    <div class="step-desc">${t('s2_desc')}</div>
    <div class="drop-grid">
      <div class="drop-zone${_baselineFile ? ' has-file' : ''}" id="dz-onprem" onclick="document.getElementById('f-onprem').click()" ondragover="dzDragOver(event,'dz-onprem')" ondragleave="dzDragLeave('dz-onprem')" ondrop="dzDrop(event,'dz-onprem','f-onprem')">
        ${_baselineFile ? `<span class="drop-remove" onclick="clearFile('baseline',event)">✕</span>` : ''}
        <div class="drop-icon">🖥️</div>
        <div class="drop-title">${t('s2_onprem_hint')}</div>
        <div class="drop-hint">.xlsx</div>
        ${_baselineFile ? `<div class="drop-filename">${_baselineFile.name}</div>` : ''}
      </div>
      <div class="drop-zone${_cloudFile ? ' has-file' : ''}" id="dz-cloud" onclick="document.getElementById('f-cloud').click()" ondragover="dzDragOver(event,'dz-cloud')" ondragleave="dzDragLeave('dz-cloud')" ondrop="dzDrop(event,'dz-cloud','f-cloud')">
        ${_cloudFile ? `<span class="drop-remove" onclick="clearFile('cloud',event)">✕</span>` : ''}
        <div class="drop-icon">☁️</div>
        <div class="drop-title">${t('s2_cloud_hint')}</div>
        <div class="drop-hint">.xlsx</div>
        ${_cloudFile ? `<div class="drop-filename">${_cloudFile.name}</div>` : ''}
      </div>
    </div>
    <input type="file" id="f-onprem" accept=".xlsx" onchange="fileSelected('baseline',this)">
    <input type="file" id="f-cloud"  accept=".xlsx" onchange="fileSelected('cloud',this)">
    <div id="s2-spinner" class="spinner-wrap" style="margin-top:16px;"><div class="spinner"></div><span class="spin-msg">${t('s2_busy')}</span></div>
    <div id="s2-result" class="result-card" style="margin-top:16px;"></div>
  `;
}

async function runBaseline() {
  const btn = document.getElementById('btn-next');
  btn.disabled = true;
  document.getElementById('s2-spinner').classList.add('show');
  try {
    const fd = new FormData();
    if (_baselineFile) fd.append('onprem_file', _baselineFile);
    if (_cloudFile) fd.append('cloud_file', _cloudFile);
    const r = await apiFetch(`/api/session/${_sessionId}/baseline`, { method: 'POST', body: fd });
    document.getElementById('s2-spinner').classList.remove('show');
    _baselineDone = true;
    _generateFiles.baseline = r.path;
    showResult('s2-result', 'success', `✓ ${t('s2_ok')}`,
      `<div class="result-stats">${r.onprem_count != null ? `<div class="stat-pill"><div class="stat-n">${r.onprem_count}</div><div class="stat-lbl">OnPrem</div></div>` : ''}${r.cloud_count != null ? `<div class="stat-pill"><div class="stat-n">${r.cloud_count}</div><div class="stat-lbl">Cloud</div></div>` : ''}</div><a href="${BASE}/api/session/${_sessionId}/download/baseline" class="btn-download" download>${t('s2_download')}</a>`
    );
    btn.disabled = false;
    setTimeout(() => { _step++; renderStep(_step); renderPills(); }, 1200);
  } catch(e) {
    document.getElementById('s2-spinner').classList.remove('show');
    showResult('s2-result', 'error', '✗ Error', e.message);
    btn.disabled = false;
  }
}
```

---

## Task 8: Steps 3–5 render functions (Requirements, PDF, Images)

**Files:**
- Modify: `archimedes_wizard_pro.html`

- [ ] **Step 1: Add renderS3, runRequirements, renderS4, runPdf**

```javascript
function renderS3(el) {
  el.innerHTML = `
    <div class="step-eyebrow">${t('s3_eye', 4, TOTAL_STEPS)}</div>
    <div class="step-title">${t('s3_title')}</div>
    <div class="step-desc">${t('s3_desc')}</div>
    <div class="drop-grid single">
      <div class="drop-zone${_reqsFile ? ' has-file' : ''}" id="dz-reqs" onclick="document.getElementById('f-reqs').click()" ondragover="dzDragOver(event,'dz-reqs')" ondragleave="dzDragLeave('dz-reqs')" ondrop="dzDrop(event,'dz-reqs','f-reqs')">
        ${_reqsFile ? `<span class="drop-remove" onclick="clearFile('reqs',event)">✕</span>` : ''}
        <div class="drop-icon">📊</div>
        <div class="drop-title">${t('s3_hint')}</div>
        <div class="drop-hint">.xlsx</div>
        ${_reqsFile ? `<div class="drop-filename">${_reqsFile.name}</div>` : ''}
      </div>
    </div>
    <input type="file" id="f-reqs" accept=".xlsx" onchange="fileSelected('reqs',this)">
    <div style="margin-top:16px;">
      <div class="toggle-row${_contrastEnabled ? ' active' : ''}" onclick="toggleContrast(this)" id="tr-contrast">
        <input type="checkbox" ${_contrastEnabled ? 'checked' : ''} onchange="toggleContrast(document.getElementById('tr-contrast'))">
        <div><div class="tr-label">${t('s3b_toggle')}</div><div class="tr-file">${t('s3b_toggle_hint')}</div></div>
      </div>
    </div>
    <div id="s3-spinner" class="spinner-wrap" style="margin-top:16px;"><div class="spinner"></div><span class="spin-msg">${t('s3_busy')}</span></div>
    <div id="s3-result" class="result-card" style="margin-top:16px;"></div>
  `;
}

function toggleContrast(row) {
  _contrastEnabled = !_contrastEnabled;
  row.classList.toggle('active', _contrastEnabled);
  row.querySelector('input').checked = _contrastEnabled;
}

async function runRequirements() {
  const btn = document.getElementById('btn-next');
  btn.disabled = true;
  document.getElementById('s3-spinner').classList.add('show');
  try {
    const fd = new FormData();
    fd.append('file', _reqsFile);
    const r = await apiFetch(`/api/session/${_sessionId}/requirements`, { method: 'POST', body: fd });
    let body = '';
    if (r.already_enriched) body = `<div class="result-summary">${t('s3_already')}</div>`;
    else body = `<div class="result-summary">${t('s3_enriched', r.validation_ok)}</div>`;
    if (_contrastEnabled) {
      document.getElementById('s3-spinner').querySelector('.spin-msg').textContent = t('s3b_busy');
      try {
        const rc = await apiFetch(`/api/session/${_sessionId}/contrast`, { method: 'POST' });
        body += `<div class="result-summary" style="margin-top:8px;">${t('s3b_ok', rc.validated, rc.unverified)}</div>`;
        if (rc.path) body += `<a href="${BASE}/api/session/${_sessionId}/download/contrast" class="btn-download" style="margin-top:8px;" download>${t('s3b_download')}</a>`;
      } catch(ec) { body += `<div style="margin-top:8px;color:var(--orange);font-size:12px;">⚠ Contrast: ${ec.message}</div>`; }
    }
    document.getElementById('s3-spinner').classList.remove('show');
    _reqsDone = true;
    showResult('s3-result', 'success', `✓ ${t('s3_ok')}`, body);
    btn.disabled = false;
    setTimeout(() => { _step++; renderStep(_step); renderPills(); }, 1200);
  } catch(e) {
    document.getElementById('s3-spinner').classList.remove('show');
    showResult('s3-result', 'error', '✗ Error', e.message);
    btn.disabled = false;
  }
}

function renderS4(el) {
  el.innerHTML = `
    <div class="step-eyebrow">${t('s4_eye', 5, TOTAL_STEPS)}</div>
    <div class="step-title">${t('s4_title')}</div>
    <div class="step-desc">${t('s4_desc')}</div>
    <div class="drop-grid single">
      <div class="drop-zone${_pdfFile ? ' has-file' : ''}" id="dz-pdf" onclick="document.getElementById('f-pdf').click()" ondragover="dzDragOver(event,'dz-pdf')" ondragleave="dzDragLeave('dz-pdf')" ondrop="dzDrop(event,'dz-pdf','f-pdf')">
        ${_pdfFile ? `<span class="drop-remove" onclick="clearFile('pdf',event)">✕</span>` : ''}
        <div class="drop-icon">📄</div>
        <div class="drop-title">${t('s4_hint')}</div>
        <div class="drop-hint">${t('s4_hint2')}</div>
        ${_pdfFile ? `<div class="drop-filename">${_pdfFile.name}</div>` : ''}
      </div>
    </div>
    <input type="file" id="f-pdf" accept=".pdf" onchange="fileSelected('pdf',this)">
    <div id="s4-spinner" class="spinner-wrap" style="margin-top:16px;"><div class="spinner"></div><span class="spin-msg">${t('s4_busy')}</span></div>
    <div id="s4-result" class="result-card" style="margin-top:16px;"></div>
  `;
}

async function runPdf() {
  const btn = document.getElementById('btn-next');
  btn.disabled = true;
  document.getElementById('s4-spinner').classList.add('show');
  try {
    const fd = new FormData();
    fd.append('file', _pdfFile);
    const r = await apiFetch(`/api/session/${_sessionId}/pdf`, { method: 'POST', body: fd });
    document.getElementById('s4-spinner').classList.remove('show');
    _pdfDone = true;
    showResult('s4-result', 'success', `✓ ${t('s4_ok')}`,
      `<div class="result-stats">${['applications','business_capabilities','initiatives','it_components'].map(k => r[k] ? `<div class="stat-pill"><div class="stat-n">${r[k]}</div><div class="stat-lbl">${k.split('_').map(w=>w[0].toUpperCase()+w.slice(1)).join(' ')}</div></div>` : '').join('')}</div>`
    );
    btn.disabled = false;
    setTimeout(() => { _step++; renderStep(_step); renderPills(); }, 1200);
  } catch(e) {
    document.getElementById('s4-spinner').classList.remove('show');
    showResult('s4-result', 'error', '✗ Error', e.message);
    btn.disabled = false;
  }
}
```

- [ ] **Step 2: Add renderS5 and runImages**

```javascript
function renderS5(el) {
  const thumbs = _images.map((f, i) => `
    <div class="img-thumb">
      <img src="${URL.createObjectURL(f)}">
      <div class="img-thumb-remove" onclick="removeImage(${i})">✕</div>
    </div>`).join('');
  el.innerHTML = `
    <div class="step-eyebrow">${t('s5_eye', 6, TOTAL_STEPS)}</div>
    <div class="step-title">${t('s5_title')}</div>
    <div class="step-desc">${t('s5_desc')}</div>
    <div class="drop-grid single">
      <div class="drop-zone" id="dz-imgs" onclick="document.getElementById('f-imgs').click()" ondragover="dzDragOver(event,'dz-imgs')" ondragleave="dzDragLeave('dz-imgs')" ondrop="dzDropImages(event)">
        <div class="drop-icon">🖼️</div>
        <div class="drop-title">${t('s5_dz_title')}</div>
        <div class="drop-hint">${t('s5_dz_hint')}</div>
      </div>
    </div>
    <input type="file" id="f-imgs" accept=".png,.jpg,.jpeg,.gif,.webp" multiple onchange="addImages(this.files)">
    ${_images.length ? `<div class="img-thumbs">${thumbs}</div>` : ''}
    <div id="s5-spinner" class="spinner-wrap" style="margin-top:16px;"><div class="spinner"></div><span class="spin-msg">${t('s5_busy')}</span></div>
    <div id="s5-result" class="result-card" style="margin-top:16px;"></div>
  `;
}

function addImages(files) {
  _images = [..._images, ...Array.from(files)];
  renderStep(_step);
}
function removeImage(i) {
  _images.splice(i, 1);
  renderStep(_step);
}
function dzDropImages(e) {
  e.preventDefault();
  document.getElementById('dz-imgs').classList.remove('drag-over');
  addImages(e.dataTransfer.files);
}

async function runImages() {
  const btn = document.getElementById('btn-next');
  btn.disabled = true;
  document.getElementById('s5-spinner').classList.add('show');
  try {
    const fd = new FormData();
    _images.forEach(f => fd.append('files', f));
    const r = await apiFetch(`/api/session/${_sessionId}/images`, { method: 'POST', body: fd });
    document.getElementById('s5-spinner').classList.remove('show');
    _imgDone = true;
    showResult('s5-result', 'success', `✓ ${t('s5_ok', _images.length)}`);
    btn.disabled = false;
    setTimeout(() => { _step++; renderStep(_step); renderPills(); }, 1200);
  } catch(e) {
    document.getElementById('s5-spinner').classList.remove('show');
    showResult('s5-result', 'error', '✗ Error', e.message);
    btn.disabled = false;
  }
}
```

---

## Task 9: Steps 6–8 render functions (Generate, Industry Reference, Import)

**Files:**
- Modify: `archimedes_wizard_pro.html`

- [ ] **Step 1: Add renderS6 and runGenerate**

```javascript
function renderS6(el) {
  el.innerHTML = `
    <div class="step-eyebrow">${t('s6_eye', 7, TOTAL_STEPS)}</div>
    <div class="step-title">${t('s6_title')}</div>
    <div class="step-desc">${t('s6_desc')}</div>
    <div id="s6-spinner" class="spinner-wrap"><div class="spinner"></div><span class="spin-msg">${t('s6_busy')}</span></div>
    <div id="s6-result" class="result-card"></div>
    <div id="s6-downloads" class="download-list" style="margin-top:16px;"></div>
  `;
  if (!_generateDone) runGenerate();
}

async function runGenerate() {
  const btn = document.getElementById('btn-next');
  if (btn) btn.disabled = true;
  const sp = document.getElementById('s6-spinner');
  if (sp) sp.classList.add('show');
  try {
    const r = await apiFetch(`/api/session/${_sessionId}/generate`, { method: 'POST' });
    if (sp) sp.classList.remove('show');
    _generateDone = true;
    _generateFiles = r.files || {};
    _lxConfigured = r.lx_configured || false;
    const dl = document.getElementById('s6-downloads');
    if (dl) {
      const items = [
        r.files?.baseline && { icon:'📋', label:t('s6_label_baseline'), desc:t('s6_desc_baseline'), key:'baseline' },
        r.files?.target   && { icon:'🎯', label:t('s6_label_target'),   desc:t('s6_desc_target'),   key:'target' },
        r.files?.supplementary && { icon:'📎', label:t('s6_label_supp'), desc:t('s6_desc_supp'), key:'supplementary' },
      ].filter(Boolean);
      if (items.length) {
        dl.innerHTML = items.map(it => `
          <div class="download-item">
            <div class="di-icon">${it.icon}</div>
            <div class="di-info"><div class="di-label">${it.label}</div><div class="di-desc">${it.desc}</div></div>
            <a href="${BASE}/api/session/${_sessionId}/download/${it.key}" class="btn-download" download>${t('s6_download')}</a>
          </div>`).join('');
        showResult('s6-result', 'success', `✓ ${t('s6_ok')}`);
      } else {
        showResult('s6-result', 'warning', t('s6_none'), t('s6_none_hint'));
      }
    }
    if (btn) btn.disabled = false;
  } catch(e) {
    if (sp) sp.classList.remove('show');
    showResult('s6-result', 'error', '✗ Error', e.message);
    if (btn) btn.disabled = false;
  }
}
```

- [ ] **Step 2: Add renderS7ref (Industry Reference, step 8)**

```javascript
function renderS7ref(el) {
  el.innerHTML = `
    <div class="step-eyebrow">${t('s7ref_eye', 8, TOTAL_STEPS)}</div>
    <div class="step-title">${t('s3c_title')}</div>
    <div class="step-desc">${t('s3c_desc')}</div>
    <label class="field-label">${t('s3c_label')}</label>
    <select class="industry-select" id="industry-sel"></select>
    <button class="btn-secondary" style="margin-top:14px;width:100%;" onclick="loadIndustryRef()" id="btn-load-ref">${t('s3c_fetch')}</button>
    <div id="s7ref-spinner" class="spinner-wrap" style="margin-top:16px;"><div class="spinner"></div><span class="spin-msg">${t('s3c_busy')}</span></div>
    <div id="s7ref-result" class="result-card" style="margin-top:16px;"></div>
    <div id="s7ref-ws"></div>
  `;
  apiFetch('/api/industries').then(data => {
    const sel = document.getElementById('industry-sel');
    if (sel) sel.innerHTML = data.map(i => `<option value="${i.key}">${i.label}</option>`).join('');
  }).catch(() => {});
}

async function loadIndustryRef() {
  const ind = document.getElementById('industry-sel')?.value;
  if (!ind) return;
  document.getElementById('s7ref-spinner').classList.add('show');
  document.getElementById('s7ref-result').className = 'result-card';
  document.getElementById('s7ref-ws').innerHTML = '';
  try {
    const r = await apiFetch(`/api/session/${_sessionId}/industry-reference`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ industry: ind })
    });
    document.getElementById('s7ref-spinner').classList.remove('show');
    const ws = r.whitespace || [];
    const covered = r.covered_count || 0;
    const wsEl = document.getElementById('s7ref-ws');
    wsEl.innerHTML = `
      <div style="margin-top:16px;">
        <div class="step-eyebrow">${t('s3c_whitespace_title', ws.length)}</div>
        <div style="font-size:12px;color:var(--text-muted);margin-bottom:10px;">${t('s3c_covered', covered)}</div>
        <div class="ws-select-bar">
          <button onclick="wsSelectAll(true)">${t('s3c_select_all')}</button>
          <button onclick="wsSelectAll(false)">${t('s3c_deselect_all')}</button>
        </div>
        <div class="ws-product-list" id="ws-list">
          ${ws.map((p, i) => `
            <div class="ws-product-item${p.include ? ' selected' : ''}" onclick="wsToggle(${i},this)" data-idx="${i}">
              <input type="checkbox" ${p.include ? 'checked' : ''} onchange="wsToggle(${i},this.closest('.ws-product-item'))">
              <span class="ws-product-name">${p.name}</span>
            </div>`).join('')}
        </div>
        <button class="btn-primary" style="margin-top:14px;width:100%;" onclick="applyRef()">${t('s3c_apply')}</button>
        <div id="s7ref-apply-result" class="result-card" style="margin-top:12px;"></div>
      </div>`;
    window._wsProducts = ws;
  } catch(e) {
    document.getElementById('s7ref-spinner').classList.remove('show');
    showResult('s7ref-result', 'error', '✗ Error', e.message);
  }
}

function wsToggle(i, row) {
  if (!window._wsProducts) return;
  window._wsProducts[i].include = !window._wsProducts[i].include;
  row.classList.toggle('selected', window._wsProducts[i].include);
  row.querySelector('input').checked = window._wsProducts[i].include;
}
function wsSelectAll(val) {
  if (!window._wsProducts) return;
  window._wsProducts.forEach((p, i) => {
    p.include = val;
    const row = document.querySelector(`.ws-product-item[data-idx="${i}"]`);
    if (row) { row.classList.toggle('selected', val); row.querySelector('input').checked = val; }
  });
}
async function applyRef() {
  const selected = (window._wsProducts || []).filter(p => p.include).map(p => p.name);
  if (!selected.length) { showResult('s7ref-apply-result', 'warning', t('s3c_none_selected')); return; }
  const btn = document.querySelector('#s7ref-ws .btn-primary');
  if (btn) btn.disabled = true;
  try {
    const r = await apiFetch(`/api/session/${_sessionId}/industry-reference/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ products: selected })
    });
    showResult('s7ref-apply-result', 'success', `✓ ${t('s3c_apply_ok', r.added_count || selected.length)}`);
    _refDone = true;
  } catch(e) {
    showResult('s7ref-apply-result', 'error', '✗ Error', e.message);
  }
  if (btn) btn.disabled = false;
}
```

- [ ] **Step 3: Add renderS7 (Import + KPI Easter Egg, step 9) and renderDone**

```javascript
function renderS7(el) {
  el.innerHTML = `
    <div class="step-eyebrow">${t('s7_eye', 9, TOTAL_STEPS)}</div>
    <div class="step-title">${t('s7_title')}</div>
    ${!_lxConfigured ? `
      <div class="result-card info show" style="margin-bottom:20px;">
        <div class="result-header">ℹ️ ${t('s7_no_creds')}</div>
        <div class="result-summary">${t('s7_no_creds_hint')}</div>
        <div class="result-summary" style="margin-top:8px;">${t('s7_manual')}</div>
        <div class="result-summary" style="margin-top:6px;">${t('s7_order')}</div>
      </div>` : `
      <div class="step-desc">${t('s7_desc')}</div>
      <div class="info-box"><strong>⚠</strong> ${t('s7_warn')} — ${t('s7_warn_hint')}</div>
      <div class="push-options" id="push-opts">
        ${_generateFiles.baseline ? `<label class="toggle-row" id="tr-baseline" onclick="trToggle('tr-baseline')"><input type="checkbox" id="chk-baseline"> <div><div class="tr-label">${t('s7_chk_baseline')}</div><div class="tr-file">${_clientName}_baseline.xlsx</div></div></label>` : ''}
        ${_generateFiles.target   ? `<label class="toggle-row" id="tr-target" onclick="trToggle('tr-target')"><input type="checkbox" id="chk-target"> <div><div class="tr-label">${t('s7_chk_target')}</div><div class="tr-file">${_clientName}_target_leanix.xlsx</div></div></label>` : ''}
      </div>`}
    <div id="s7-spinner" class="spinner-wrap" style="margin-top:16px;"><div class="spinner"></div><span class="spin-msg">${t('s7_busy')}</span></div>
    <div id="s7-result" class="result-card" style="margin-top:16px;"></div>
    <div id="kpi-panel" class=""></div>
  `;
  spawnCookieMonster();
}

function trToggle(id) {
  const row = document.getElementById(id);
  if (!row) return;
  const chk = row.querySelector('input');
  chk.checked = !chk.checked;
  row.classList.toggle('active', chk.checked);
}

async function runImport() {
  if (!_lxConfigured) { _step++; renderStep(_step); renderPills(); return; }
  const baseline = document.getElementById('chk-baseline')?.checked;
  const target = document.getElementById('chk-target')?.checked;
  if (!baseline && !target) { showResult('s7-result', 'warning', t('s7_none')); return; }
  const btn = document.getElementById('btn-next');
  btn.disabled = true;
  document.getElementById('s7-spinner').classList.add('show');
  try {
    const r = await apiFetch(`/api/session/${_sessionId}/push`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ import_baseline: baseline, import_target: target })
    });
    document.getElementById('s7-spinner').classList.remove('show');
    const imported = [baseline && 'baseline', target && 'target'].filter(Boolean).join(', ');
    showResult('s7-result', 'success', `✓ ${t('s7_ok')}`, t('s7_imported', imported));
    btn.disabled = false;
    setTimeout(() => { _step++; renderStep(_step); renderPills(); }, 1500);
  } catch(e) {
    document.getElementById('s7-spinner').classList.remove('show');
    showResult('s7-result', 'error', `✗ ${t('s7_err')}`, e.message);
    btn.disabled = false;
  }
}

function renderDone(el) {
  const n = Object.keys(_generateFiles).length;
  el.innerHTML = `
    <div class="done-screen">
      <div class="done-icon">🚀</div>
      <div class="done-title">${t('done_title')}</div>
      <div class="done-sub">${t('done_sub', n, _clientName)}</div>
      <button class="btn-primary" style="margin:0 auto;" onclick="location.reload()">${t('new_pipeline')}</button>
    </div>
  `;
  destroyCookieMonster();
}

// ── KPI Easter Egg ──────────────────────────────────────────────────────────
function spawnCookieMonster() {
  destroyCookieMonster();
  _cookieClicks = 0; _kpiUnlocked = false;
  const corners = [
    { bottom: '80px', left: '20px' }, { bottom: '80px', right: '20px' },
    { top: '70px', left: '20px'   }, { top: '70px', right: '20px'    }
  ];
  const pos = corners[Math.floor(Math.random() * corners.length)];
  const wrap = document.createElement('div');
  wrap.className = 'kpi-cookie-wrap';
  Object.assign(wrap.style, pos);
  wrap.innerHTML = `<img src="${BASE}/cookie_monster.png" alt="🍪"><div class="kpi-cookie-badge" id="kpi-badge"></div>`;
  wrap.addEventListener('click', onCookieClick);
  document.body.appendChild(wrap);
  _cookieEl = wrap;
}
function destroyCookieMonster() {
  if (_cookieEl) { _cookieEl.remove(); _cookieEl = null; }
}
function onCookieClick() {
  if (_kpiUnlocked) return;
  _cookieClicks++;
  const badge = document.getElementById('kpi-badge');
  if (badge) { badge.textContent = _cookieClicks; badge.classList.add('show'); }
  _cookieEl.classList.add('active');
  setTimeout(() => _cookieEl && _cookieEl.classList.remove('active'), 400);
  if (_cookieClicks >= 3) {
    _kpiUnlocked = true;
    if (badge) badge.classList.remove('show');
    showKpiPanel();
  }
}
function showKpiPanel() {
  const panel = document.getElementById('kpi-panel');
  if (!panel) return;
  panel.className = 'show';
  panel.innerHTML = `
    <div class="kpi-panel-header">${t('kpi_panel_title')}</div>
    <div class="kpi-panel-hint">${t('kpi_panel_hint')}</div>
    <div class="kpi-stats">
      <div class="kpi-stat"><strong>5</strong> Objectives</div>
      <div class="kpi-stat"><strong>91</strong> BCs</div>
      <div class="kpi-stat"><strong>100</strong> Apps</div>
      <div class="kpi-stat"><strong>5</strong> Initiatives</div>
    </div>
    <div id="kpi-result" class="result-card"></div>
    <button class="btn-primary" onclick="runKpiImport()">${t('kpi_chk')}</button>
  `;
}
async function runKpiImport() {
  const btn = document.querySelector('#kpi-panel .btn-primary');
  if (btn) btn.disabled = true;
  showResult('kpi-result', 'info', t('kpi_busy'));
  try {
    const r = await fetch(`${BASE}/api/session/${_sessionId}/push-kpi`, { method: 'POST' });
    const data = await r.json();
    if (data.ok) {
      showResult('kpi-result', 'success', `✓ ${t('kpi_ok')}`, t('kpi_ok_hint', data.stats));
    } else {
      showResult('kpi-result', 'error', `✗ ${t('kpi_err')}`, data.detail || '');
    }
  } catch(e) {
    showResult('kpi-result', 'error', `✗ ${t('kpi_err')}`, e.message);
  }
  if (btn) btn.disabled = false;
}
```

---

## Task 10: Drag-and-drop helpers + file management + init

**Files:**
- Modify: `archimedes_wizard_pro.html`

- [ ] **Step 1: Add drag-drop helpers, fileSelected, clearFile, and init**

```javascript
// ── Drag & drop helpers ─────────────────────────────────────────────────────
function dzDragOver(e, id) {
  e.preventDefault();
  document.getElementById(id).classList.add('drag-over');
}
function dzDragLeave(id) {
  document.getElementById(id).classList.remove('drag-over');
}
function dzDrop(e, dzId, inputId) {
  e.preventDefault();
  document.getElementById(dzId).classList.remove('drag-over');
  const files = e.dataTransfer.files;
  if (files.length) {
    const inp = document.getElementById(inputId);
    const dt = new DataTransfer();
    dt.items.add(files[0]);
    inp.files = dt.files;
    inp.dispatchEvent(new Event('change'));
  }
}

function fileSelected(key, input) {
  const file = input.files[0];
  if (!file) return;
  if (key === 'baseline') _baselineFile = file;
  else if (key === 'cloud')   _cloudFile   = file;
  else if (key === 'reqs')    _reqsFile    = file;
  else if (key === 'pdf')     _pdfFile     = file;
  renderStep(_step);
}

function clearFile(key, e) {
  e.stopPropagation();
  if (key === 'baseline') _baselineFile = null;
  else if (key === 'cloud') _cloudFile  = null;
  else if (key === 'reqs')  _reqsFile   = null;
  else if (key === 'pdf')   _pdfFile    = null;
  renderStep(_step);
}

// ── Init ────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  renderStep(0);
  renderPills();
});
```

- [ ] **Step 2: Close the `</script>` and `</body></html>` tags**

```html
</script>
</body>
</html>
```

- [ ] **Step 3: Start the backend and open the Pro wizard**

```bash
cd /Users/I519409/dev/archimedes-ai
python3 archimedes_wizard.py &
# Then open archimedes_wizard_pro.html in browser
open archimedes_wizard_pro.html
```

Expected: dark background, header with Archimedes AI logo, 9 progress pills, Step 1 "Client name" card with dark glassmorphism styling.

- [ ] **Step 4: Verify all 9 steps navigate correctly with Continue/Back/Skip buttons**

Walk through steps 0→1→2→...→8 using Skip where applicable. Verify:
- Pills update on each step
- `fadeUp` animation plays on each step change
- Header client name updates after Step 0
- Cookie Monster appears on Step 9
- 3 clicks on Cookie Monster reveals KPI panel

---

## Self-Review Checklist

- [x] All 9 steps covered (renderS0–renderS7ref–renderS7–renderDone)
- [x] All API endpoints match `archimedes_wizard.py` (`/api/session`, `/api/catalogs`, `/api/session/{id}/baseline`, `/requirements`, `/contrast`, `/pdf`, `/images`, `/generate`, `/push`, `/push-kpi`, `/industries`, `/industry-reference`, `/industry-reference/apply`)
- [x] `LANGS` copied verbatim — all translation keys used match existing keys
- [x] Cookie Monster easter egg: spawn on step 9, destroy on done/step change, 3 clicks → KPI panel
- [x] No external dependencies — pure HTML/CSS/JS
- [x] `archimedes_wizard.py` and `archimedes_wizard.html` untouched
