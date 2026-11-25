"""The generic form reader / filler, in a real (headless, offline) browser.

The HTML mimics the structure of LinkedIn's Easy Apply modal and Indeed's apply steps (labels via
`for`, fieldset/legend radio groups, selects with a placeholder option, prefilled fields); it is
written for these tests, not captured from the sites."""
import pytest

from jobscout.apply import form
from jobscout.apply.answers import Answerer
from jobscout.apply.base import NeedsYou

pw_sync = pytest.importorskip("playwright.sync_api")

LINKEDIN_STEP = """
<div role="dialog" class="jobs-easy-apply-modal">
  <label for="email">Email address</label>
  <select id="email" required><option>Select an option</option><option selected>me@example.com</option></select>
  <label for="phone">Mobile phone number *</label><input id="phone" type="text" required>
  <label for="yrs">How many years of work experience do you have with Python?</label>
  <input id="yrs" type="text" required>
  <fieldset><legend>Are you willing to relocate? *</legend>
    <input type="radio" id="r1" name="reloc" value="Yes"><label for="r1">Yes</label>
    <input type="radio" id="r2" name="reloc" value="No"><label for="r2">No</label>
  </fieldset>
  <label for="notice">Notice period</label>
  <select id="notice" required><option>Select an option</option><option>Immediate</option><option>15 days</option><option>1 month</option></select>
  <label><input type="checkbox" id="follow"> Follow Acme to stay up to date</label>
  <label for="cover">Cover letter</label><textarea id="cover"></textarea>
</div>
<input id="outside" type="text" aria-label="Search">
"""

SHEET = {"phone": "+919876543210", "skills_experience": {"python": 4}, "relocate": True, "notice_period_days": 30}


@pytest.fixture(scope="module")
def page():
    with pw_sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"no Playwright browser: {e}")
        yield browser.new_page()
        browser.close()


def test_read_fields(page):
    page.set_content(LINKEDIN_STEP)
    fields = {q.label: q for q in form.read_fields(page, "div[role='dialog']")}
    assert "Search" not in fields                                     # outside the modal
    assert fields["Email address"].kind == "select" and fields["Email address"].value == "me@example.com"
    assert fields["Mobile phone number"].required
    assert fields["Are you willing to relocate?"].kind == "radio"
    assert fields["Are you willing to relocate?"].options == ["Yes", "No"]
    assert fields["Notice period"].options[1:] == ["Immediate", "15 days", "1 month"]
    assert fields["Follow Acme to stay up to date"].kind == "checkbox"
    assert fields["Cover letter"].kind == "textarea" and not fields["Cover letter"].required


def test_fill_step(page):
    page.set_content(LINKEDIN_STEP)
    done = form.fill_step(page, "div[role='dialog']", Answerer(SHEET, {}))
    by_q = {qa.q: (qa.answer, qa.source) for qa in done}
    assert by_q["Email address"] == ("me@example.com", "prefilled")
    assert by_q["How many years of work experience do you have with Python?"] == ("4", "saved")
    assert page.input_value("#phone") == "9876543210"
    assert page.input_value("#yrs") == "4"
    assert page.is_checked("#r1") and not page.is_checked("#r2")
    assert page.eval_on_selector("#notice", "e => e.options[e.selectedIndex].text") == "1 month"
    assert page.input_value("#cover") == ""          # optional and unknown: left empty


def test_required_unknown_question_needs_you(page):
    page.set_content(LINKEDIN_STEP.replace("Python?", "Kubernetes?"))
    with pytest.raises(NeedsYou) as e:
        form.fill_step(page, "div[role='dialog']", Answerer(SHEET, {}))
    assert "Kubernetes" in str(e.value)


def test_resume_upload(page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 test")
    page.set_content('<main><label for="cv">Upload resume</label><input id="cv" type="file"></main>')
    done = form.fill_step(page, "main", Answerer({}, {}), str(resume))
    assert done[0].answer == "resume.pdf"
    assert page.eval_on_selector("#cv", "e => e.files[0].name") == "resume.pdf"


def test_errors(page):
    page.set_content('<div role="dialog"><div class="artdeco-inline-feedback--error">Enter a whole number</div></div>')
    assert form.errors(page, "div[role='dialog']") == ["Enter a whole number"]


def test_rejected_numeric_answer_is_retried_with_the_number(page):
    """LinkedIn's number questions are text boxes: "0 days" comes back as "Invalid input"."""
    from jobscout.apply.base import QA

    page.set_content("""<dialog open data-testid="dialog">
      <label for="n">What is your official notice period?*</label>
      <input id="n" type="text" aria-describedby="n-help" value="0 days">
      <div id="n-help">Invalid input<br>6/20</div></dialog>""")
    form.read_fields(page, "dialog[data-testid='dialog']")
    done = [QA("What is your official notice period?", "0 days", "saved")]
    assert form.invalid_fields(page, "dialog[data-testid='dialog']")
    assert form.fix_invalid(page, "dialog[data-testid='dialog']", Answerer({}, {}), done)
    assert page.input_value("#n") == "0" and done[-1].answer == "0"
    assert "Invalid input" in form.errors(page, "dialog[data-testid='dialog']")


def test_modal_root_priority(page):
    """The apply dialog wins over other dialogs earlier in the page (e.g. messaging)."""
    page.set_content("""<div role="dialog"><label for="m">Message</label><input id="m"></div>
      <dialog open data-testid="dialog"><label for="p">Mobile phone number</label><input id="p" required></dialog>""")
    labels = [q.label for q in form.read_fields(page, "dialog[data-testid='dialog'], div[role='dialog']")]
    assert labels == ["Mobile phone number"]
