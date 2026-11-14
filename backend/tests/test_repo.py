"""Per-user dedupe of posts and contacts against a real Postgres (TEST_DATABASE_URL)."""
from sqlalchemy import func, select

from jobscout.db import repo
from jobscout.db.models import Contact, EmailOutreach, EmailStatus, Platform
from jobscout.pipeline.scrape import save_contacts
from jobscout.security.users import create_user


def _user(s, email):
    return create_user(s, email, "password123").id


def _post(s, uid, ext):
    return repo.insert_post(s, user_id=uid, platform=Platform.linkedin, external_id=ext, description="x")


def test_post_dedupe_is_per_user(session):
    a, b = _user(session, "a@x.io"), _user(session, "b@x.io")
    assert _post(session, a, "urn:1") is not None
    assert _post(session, a, "urn:1") is None          # same user: duplicate
    assert _post(session, b, "urn:1") is not None      # other user: their own copy
    assert repo.existing_external_ids(session, a, Platform.linkedin, ["urn:1", "urn:2"]) == {"urn:1"}


def test_same_email_or_phone_is_one_contact_per_user(session):
    a, b = _user(session, "a@x.io"), _user(session, "b@x.io")
    p1, p2, p3, p4 = (_post(session, a, "1"), _post(session, a, "2"), _post(session, a, "3"), _post(session, b, "1"))
    save_contacts(session, a, p1.id, "Priya", ["hr@acme.io"], [])
    save_contacts(session, a, p2.id, None, ["HR@Acme.io"], ["+919876543210"])   # same email, adds phone
    save_contacts(session, a, p3.id, "Someone", [], ["+919876543210"])          # same phone
    save_contacts(session, b, p4.id, "Priya", ["hr@acme.io"], [])                # user B: separate contact
    session.commit()

    mine = session.scalars(select(Contact).where(Contact.user_id == a)).all()
    assert len(mine) == 1
    assert (mine[0].name, mine[0].email, mine[0].phone) == ("Priya", "hr@acme.io", "+919876543210")
    assert session.scalar(select(func.count()).select_from(Contact).where(Contact.user_id == b)) == 1
    assert session.scalar(select(func.count()).select_from(EmailOutreach)) == 2


def test_phone_only_contact_skipped_then_upgraded(session):
    a = _user(session, "a@x.io")
    p1, p2 = _post(session, a, "a"), _post(session, a, "b")
    save_contacts(session, a, p1.id, "Rahul", [], ["+919876543210"])
    session.commit()
    assert session.scalars(select(EmailOutreach)).one().status == EmailStatus.skipped
    save_contacts(session, a, p2.id, "Rahul", ["rahul@acme.io"], ["+919876543210"])
    session.commit()
    assert session.scalars(select(EmailOutreach)).one().status == EmailStatus.pending


def test_save_contacts_reports_only_new_emails_and_phones(session):
    a = _user(session, "a@x.io")
    p1, p2, p3, p4 = (_post(session, a, str(i)) for i in range(4))
    assert save_contacts(session, a, p1.id, "Priya", ["hr@acme.io"], []) == 1                 # new email
    assert save_contacts(session, a, p2.id, None, ["hr@acme.io"], []) == 0                    # already have it
    assert save_contacts(session, a, p3.id, None, ["hr@acme.io"], ["+919876543210"]) == 1     # new phone only
    assert save_contacts(session, a, p4.id, "Name Only", [], []) == 0                         # nothing to count
