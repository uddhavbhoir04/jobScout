"""Read and fill an application form step, whatever the site.

`read_fields(page, root)` lists the visible fields inside `root` (a CSS selector for the modal /
form) as Questions: label, kind, options, whether it's required and what's already filled in.
Each field is tagged with a data attribute so `fill()` finds it again.

`fill_step()` answers every field with the Answerer; a required field we can't answer raises
NeedsYou, so nothing is submitted with a blank or a guess.
"""
import logging
from pathlib import Path

from playwright.sync_api import Page

from jobscout.apply.base import QA, NeedsYou, Question

log = logging.getLogger(__name__)

TAG = "data-js-field"

# Returns [{key, label, kind, options, required, value}] for the visible fields in `root`.
_READ_JS = r"""
([root, TAG]) => {
  // `root` may list several selectors: the first one present wins (priority order, not page order)
  const scope = root.split(',').map(s => document.querySelector(s.trim())).find(Boolean) || document;
  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const clean = (t) => (t || '').replace(/\s+/g, ' ').replace(/\s*\*\s*$/, '').trim();
  const byId = (id) => id ? document.getElementById(id) : null;
  const labelOf = (el) => {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const ids = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
    if (ids.length) return ids.map(i => (byId(i) || {}).innerText || '').join(' ');
    if (el.id) { const l = scope.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return l.innerText; }
    const wrap = el.closest('label'); if (wrap) return wrap.innerText;
    return el.getAttribute('placeholder') || el.getAttribute('name') || '';
  };
  const groupLabel = (el) => {
    const fs = el.closest('fieldset');
    if (fs) { const lg = fs.querySelector('legend'); if (lg) return lg.innerText; }
    const grp = el.closest('[role="radiogroup"], [role="group"]');
    if (grp) return labelOf(grp);
    return '';
  };
  const isRequired = (el, label) => el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$/.test(label || '');
  const out = [];
  const groups = {};
  let n = 0;
  for (const el of scope.querySelectorAll('input, select, textarea')) {
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes(type)) continue;
    if (type !== 'file' && !visible(el)) continue;
    if (type === 'radio' || type === 'checkbox') {
      const gname = el.name || el.id;
      const optLabel = clean(labelOf(el));
      const glabel = groupLabel(el);
      // a lone checkbox with its own label ("I agree...") is a yes/no question
      const lone = type === 'checkbox' && !glabel;
      const key = lone ? `cb-${n++}` : `${type}-${gname}`;
      if (!groups[key]) {
        groups[key] = { key, label: clean(lone ? optLabel : glabel), kind: type, options: [], required: false, value: '' };
        out.push(groups[key]);
      }
      const g = groups[key];
      el.setAttribute(TAG, key);
      if (!lone) { el.setAttribute(TAG + '-opt', optLabel); g.options.push(optLabel); }
      if (el.checked) g.value = lone ? 'Yes' : optLabel;
      g.required = g.required || isRequired(el, glabel || optLabel);
      continue;
    }
    const key = `f-${n++}`;
    el.setAttribute(TAG, key);
    const rawLabel = labelOf(el);
    const kind = el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea'
               : type === 'file' ? 'file' : type === 'number' ? 'number' : 'text';
    const options = el.tagName === 'SELECT' ? [...el.options].map(o => clean(o.textContent)).filter(Boolean) : [];
    let value = el.tagName === 'SELECT' ? (el.selectedIndex > 0 ? clean(el.options[el.selectedIndex].textContent) : '') : (el.value || '');
    if (type === 'file') value = '';
    out.push({ key, label: clean(rawLabel), kind, options, required: isRequired(el, rawLabel), value });
  }
  return out;
}
"""

_ERRORS_JS = r"""
(root) => {
  const scope = root.split(',').map(s => document.querySelector(s.trim())).find(Boolean) || document;
  const sel = '[role="alert"], .artdeco-inline-feedback--error, [class*="error-message"], [class*="errorMessage"], [aria-live="assertive"]';
  const out = [...scope.querySelectorAll(sel)].map(e => (e.innerText || '').trim()).filter(Boolean);
  // LinkedIn's 2026 forms put "Invalid input" / "A resume is required" in plain text: catch those too
  const RX = /(invalid|required|please (enter|select|provide)|enter a (valid|whole|decimal)|must be|between \d|is not valid)/i;
  for (const e of scope.querySelectorAll('p, span, div')) {
    if (e.children.length > 1) continue;
    const t = (e.innerText || '').trim();
    if (t && t.length < 120 && RX.test(t) && !/\*$/.test(t)) out.push(t);
  }
  // first line only: LinkedIn appends a character counter ("Invalid input\n6/20")
  return [...new Set(out.map(t => t.split(/\r?\n/)[0].trim()).filter(Boolean))];
}
"""

# Fields the site marked as wrong: [{key, message}] (needs read_fields() first, for the keys).
_INVALID_JS = r"""
([root, TAG]) => {
  const scope = root.split(',').map(s => document.querySelector(s.trim())).find(Boolean) || document;
  const RX = /(invalid|required|please (enter|select)|enter a (valid|whole|decimal)|must be|between \d|is not valid)/i;
  const out = [];
  for (const el of scope.querySelectorAll(`[${TAG}]`)) {
    const ids = (el.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
    const help = ids.map(i => (document.getElementById(i) || {}).innerText || '').join(' ');
    const bad = el.getAttribute('aria-invalid') === 'true' || RX.test(help);
    if (bad) out.push({ key: el.getAttribute(TAG), message: (help.match(/[^\n]*(invalid|required|enter|must|between|valid)[^\n]*/i) || [help])[0].trim() || 'Invalid input' });
  }
  return out;
}
"""


def read_fields(page: Page, root: str) -> list[Question]:
    return [Question(label=f["label"], kind=f["kind"], options=f["options"], required=f["required"],
                     value=f["value"], key=f["key"])
            for f in page.evaluate(_READ_JS, [root, TAG])]


def errors(page: Page, root: str) -> list[str]:
    return page.evaluate(_ERRORS_JS, root)


def invalid_fields(page: Page, root: str) -> dict[str, str]:
    """{field key: the site's message} for fields marked wrong after trying to go on."""
    seen: dict[str, str] = {}
    for f in page.evaluate(_INVALID_JS, [root, TAG]):
        seen.setdefault(f["key"], f["message"])
    return seen


def fix_invalid(page: Page, root: str, answerer, done: list[QA]) -> bool:
    """Re-answer the fields the site rejected: the bare number if the answer has one ("0 days" -> "0"),
    else the AI with the site's message. False if nothing could be fixed."""
    import re as _re

    bad = invalid_fields(page, root)
    if not bad:
        return False
    fixed = False
    for q in read_fields(page, root):
        if q.key not in bad or q.kind not in ("text", "number", "textarea"):
            continue
        prev = next((qa for qa in reversed(done) if qa.q == q.label and qa.answer), None)
        new, source = None, prev.source if prev else "ai"
        if prev and (m := _re.search(r"\d+(?:\.\d+)?", prev.answer.replace(",", ""))) and m.group(0) != prev.answer:
            new = m.group(0)                      # "0 days" -> "0"
        elif hasattr(answerer, "retry"):
            new, source = answerer.retry(q, prev.answer if prev else None, bad[q.key]), "ai"
        if new:
            fill(page, q, new)
            done.append(QA(q.label, new, source))
            fixed = True
    return fixed


def fill(page: Page, q: Question, answer: str, resume_path: str | None = None) -> None:
    sel = f'[{TAG}="{q.key}"]'
    if q.kind == "file":
        if resume_path and Path(resume_path).is_file():
            page.locator(sel).first.set_input_files(resume_path)
        return
    if q.kind == "select":
        page.locator(sel).first.select_option(label=answer)
        return
    if q.kind == "radio" or (q.kind == "checkbox" and q.options):
        opt = page.locator(f'{sel}[{TAG}-opt="{_css(answer)}"]').first
        try:
            opt.check(timeout=3_000)
        except Exception:  # noqa: BLE001 - custom-styled inputs: click their label instead
            opt.check(force=True)
        return
    if q.kind == "checkbox":
        box = page.locator(sel).first
        (box.check if answer == "Yes" else box.uncheck)(force=True)
        return
    el = page.locator(sel).first
    el.fill(answer)
    if (el.get_attribute("role") or "") == "combobox":  # typeahead (city): pick the first suggestion
        page.wait_for_timeout(1_200)
        el.press("ArrowDown")
        el.press("Enter")


def _css(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def fill_step(page: Page, root: str, answerer, resume_path: str | None = None) -> list[QA]:
    """Answer every field in the current step. Raises NeedsYou if a required one can't be answered."""
    done: list[QA] = []
    for q in read_fields(page, root):
        if q.kind == "file":
            if not q.value and resume_path:
                fill(page, q, "", resume_path)
                done.append(QA(q.label or "Resume", Path(resume_path).name, "saved"))
            continue
        if not q.label and q.kind == "checkbox":
            continue   # unlabeled box (LinkedIn's "Follow company"): handled by the site's applier
        qa = answerer.answer(q)
        if qa.source == "prefilled" or (q.kind in ("radio", "checkbox") and q.value and qa.answer in (None, q.value)):
            done.append(QA(q.label, q.value, "prefilled"))
            continue
        if qa.answer is None:
            if q.required:
                done.append(qa)
                raise NeedsYou(f"Couldn't answer: “{q.label}”", done)
            continue
        fill(page, q, qa.answer, resume_path)
        done.append(qa)
    return done
