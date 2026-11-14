import csv
import logging
from datetime import date, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from jobscout.db.models import Account, Contact, EmailOutreach, EmailStatus, Platform, Post, User
from jobscout.db.session import new_session

app = typer.Typer(help="Crawl hiring posts, store recruiter contacts, send outreach emails.", no_args_is_help=True)
db_app = typer.Typer(help="Database migrations.", no_args_is_help=True)
account_app = typer.Typer(help="Manage connected platform accounts.", no_args_is_help=True)
posts_app = typer.Typer(help="Browse scraped posts.", no_args_is_help=True)
contacts_app = typer.Typer(help="Browse / export contacts.", no_args_is_help=True)
email_app = typer.Typer(help="Draft, send and track outreach emails.", no_args_is_help=True)
user_app = typer.Typer(help="App users (each user has their own accounts and data).", no_args_is_help=True)
for sub, name in [(db_app, "db"), (user_app, "user"), (account_app, "account"), (posts_app, "posts"),
                  (contacts_app, "contacts"), (email_app, "email")]:
    app.add_typer(sub, name=name)

console = Console()


_USER_EMAIL: str | None = None


@app.callback()
def _setup(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging."),
    user: str = typer.Option(None, "--user", "-u", envvar="JOBSCOUT_USER",
                             help="Which app user to act as (email). Optional when only one user exists."),
):
    global _USER_EMAIL
    _USER_EMAIL = user
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(message)s",
                        handlers=[RichHandler(console=console, show_path=False)])
    for noisy in ("httpx", "httpcore", "httpcore2", "google_genai", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _user_id() -> int:
    """The app user this CLI command acts for."""
    with new_session() as s:
        if _USER_EMAIL:
            u = s.scalar(select(User).where(User.email == _USER_EMAIL.strip().lower()))
            if not u:
                raise typer.BadParameter(f"No user {_USER_EMAIL}. See `jobscout user list`.")
            return u.id
        users = s.scalars(select(User).order_by(User.id).limit(2)).all()
    if not users:
        raise typer.BadParameter("No users yet. Sign up in the web UI or run `jobscout user create`.")
    if len(users) > 1:
        raise typer.BadParameter("Several users exist; pass --user you@example.com (before the command).")
    return users[0].id


def _parse_date(value: str | None) -> date | None:
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


# ---------------- web api ----------------
@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000):
    """Start the API server used by the Next.js frontend."""
    import uvicorn

    console.print(f"API on http://{host}:{port}  (frontend: cd frontend && npm run dev)")
    uvicorn.run("jobscout.web.app:app", host=host, port=port, log_level="warning")


# ---------------- misc ----------------
@app.command()
def keygen():
    """Print a new FERNET_KEY for .env (used to encrypt account passwords)."""
    from jobscout.security.crypto import generate_key

    console.print(f"FERNET_KEY={generate_key()}")


# ---------------- db ----------------
@db_app.command("create")
def db_create():
    """Create the database named in DATABASE_URL (if missing), then create all tables."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from jobscout.config import get_settings
    from jobscout.db.migrate import upgrade

    url = make_url(get_settings().database_url)
    name = url.database
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        if c.execute(text("select 1 from pg_database where datname = :n"), {"n": name}).scalar():
            console.print(f"Database [bold]{name}[/bold] already exists.")
        else:
            c.execute(text(f'CREATE DATABASE "{name.replace(chr(34), "")}"'))
            console.print(f"[green]Created database {name}.[/green]")
    admin.dispose()
    upgrade()
    console.print("[green]Tables are up to date.[/green] Refresh the connection in DBeaver to see them.")


@db_app.command("upgrade")
def db_upgrade():
    """Create/upgrade all tables in the database from DATABASE_URL."""
    from jobscout.db.migrate import upgrade

    upgrade()
    console.print("[green]Database is up to date.[/green]")


@db_app.command("revision")
def db_revision(message: str = typer.Option(..., "-m")):
    """Autogenerate a migration after changing models.py."""
    from jobscout.db.migrate import revision

    revision(message)


# ---------------- users ----------------
@user_app.command("create")
def user_create(
    email: str = typer.Option(..., "--email", "-e"),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
    name: str = typer.Option(None, "--name"),
):
    """Create an app user (same as signing up in the web UI)."""
    from jobscout.security.users import AuthError, create_user

    with new_session() as s:
        try:
            u = create_user(s, email, password, name)
        except AuthError as e:
            raise typer.BadParameter(str(e))
        console.print(f"[green]Created user #{u.id} {u.email}[/green]")


@user_app.command("set-plan")
def user_set_plan(email: str, plan: str = typer.Argument(..., help="paid or free")):
    """Give a user the paid plan (AI email outreach) or move them back to free."""
    plan = plan.strip().lower()
    if plan not in ("paid", "free"):
        raise typer.BadParameter("plan must be 'paid' or 'free'")
    with new_session() as s:
        u = s.scalar(select(User).where(User.email == email.strip().lower()))
        if not u:
            raise typer.BadParameter(f"No user {email}. See `jobscout user list`.")
        u.is_paid = plan == "paid"
        s.commit()
        console.print(f"[green]{u.email} is now on the {plan} plan.[/green]")


@user_app.command("list")
def user_list():
    from sqlalchemy import func

    with new_session() as s:
        t = Table("ID", "Email", "Name", "Plan", "LinkedIn accounts", "Posts", "Contacts", "Created")
        for u in s.scalars(select(User).order_by(User.id)):
            count = lambda m: s.scalar(select(func.count()).select_from(m).where(m.user_id == u.id))  # noqa: E731
            t.add_row(str(u.id), u.email, u.name or "-", "paid" if u.is_paid else "free",
                      str(count(Account)), str(count(Post)),
                      str(count(Contact)), u.created_at.strftime("%Y-%m-%d"))
        console.print(t)


# ---------------- accounts ----------------
@account_app.command("add")
def account_add(
    platform: Platform = typer.Option(Platform.linkedin, "--platform", "-p"),
    email: str = typer.Option(..., "--email", "-e"),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
):
    """Connect an account (password is stored encrypted)."""
    from jobscout.security.crypto import encrypt

    with new_session() as s:
        acc = Account(user_id=_user_id(), platform=platform, login_email=email.strip().lower(),
                      password_enc=encrypt(password))
        s.add(acc)
        try:
            s.commit()
        except IntegrityError:
            raise typer.BadParameter(f"{email} is already connected for {platform.value}.")
        console.print(f"[green]Added account #{acc.id}[/green]. Next: [bold]jobscout account login {acc.id}[/bold]")


@account_app.command("list")
def account_list():
    with new_session() as s:
        t = Table("ID", "Platform", "Email", "Active", "Last login", "Status")
        for a in s.scalars(select(Account).where(Account.user_id == _user_id()).order_by(Account.id)):
            t.add_row(str(a.id), a.platform.value, a.login_email, "yes" if a.is_active else "no",
                      a.last_login_at.strftime("%Y-%m-%d %H:%M") if a.last_login_at else "-", a.last_status or "-")
        console.print(t)


@account_app.command("login")
def account_login(account_id: int):
    """Open a visible browser, log in and save the session (solve CAPTCHA/OTP by hand if asked)."""
    from jobscout.browser.manager import open_context
    from jobscout.extract.dates import now
    from jobscout.scrapers import get_scraper
    from jobscout.security.crypto import decrypt

    with new_session() as s:
        acc = s.get(Account, account_id)
        if not acc or acc.user_id != _user_id():
            raise typer.BadParameter(f"No account #{account_id}")
        console.print("A browser window will open. If LinkedIn asks for a code or CAPTCHA, complete it there "
                      "(you have 5 minutes).")
        with open_context(acc, headless=False) as ctx:
            ok = get_scraper(acc.platform, ctx).ensure_logged_in(acc.login_email, decrypt(acc.password_enc), True)
        acc.last_status = "ok" if ok else "login_failed"
        if ok:
            acc.last_login_at = now()
        s.commit()
        console.print("[green]Logged in, session saved.[/green]" if ok else "[red]Login failed.[/red]")


def _set_active(account_id: int, active: bool):
    with new_session() as s:
        acc = s.get(Account, account_id)
        if not acc or acc.user_id != _user_id():
            raise typer.BadParameter(f"No account #{account_id}")
        acc.is_active = active
        s.commit()


@account_app.command("disable")
def account_disable(account_id: int):
    _set_active(account_id, False)
    console.print(f"Account #{account_id} disabled.")


@account_app.command("enable")
def account_enable(account_id: int):
    _set_active(account_id, True)
    console.print(f"Account #{account_id} enabled.")


# ---------------- scrape ----------------
@app.command()
def scrape(
    tags: str = typer.Option("", "--tags", "-t", help='Role hashtags, post needs AT LEAST ONE, e.g. "#processmining,#pythondeveloper"'),
    require: str = typer.Option("", "--require", "-r", help='Extra hashtags the post must ALL contain (#hiring is always required)'),
    platform: Platform = typer.Option(Platform.linkedin, "--platform", "-p"),
    date_filter: str = typer.Option("today", "--date", "-d",
                                    help="today (= last 24 hours) | yesterday | day-before-yesterday | last-3d | last-7d | last-30d"),
    date_from: str = typer.Option(None, "--from", help="YYYY-MM-DD (overrides --date)"),
    date_to: str = typer.Option(None, "--to", help="YYYY-MM-DD"),
    limit: int = typer.Option(20, "--limit", "-n", min=1, max=100, help="New emails/phone numbers to collect (max 100); keeps searching until reached"),
    accounts: str = typer.Option("all", "--accounts", "-a", help='"all" or account IDs like "1,2"'),
    headless: bool = typer.Option(None, "--headless/--headed"),
):
    """Search posts by hashtag and save the ones that contain an email or contact name."""
    from jobscout.extract.dates import resolve
    from jobscout.pipeline.scrape import run_scrape

    dr = resolve(date_filter, _parse_date(date_from), _parse_date(date_to))
    ids = None if accounts.strip().lower() == "all" else [int(x) for x in accounts.split(",") if x.strip()]
    console.print(f"Date range: [bold]{dr.label}[/bold] ({dr.start:%Y-%m-%d %H:%M} → {dr.end:%Y-%m-%d %H:%M})")

    with console.status("Scraping…") as status:
        def progress(r):
            status.update(f"Scanned {r.scanned} posts, saved {r.saved}/{limit}…")

        uid = _user_id()
        with new_session() as s:
            paid = bool(s.get(User, uid).is_paid)
        res = run_scrape(user_id=uid, use_ai=paid, platform=platform, tags=[tags], required_tags=[require], date_range=dr, limit=limit,
                         account_ids=ids, headless=headless, on_progress=progress)

    console.print(f"[green]Run #{res.run_id}: collected {res.collected}/{limit} new emails/numbers[/green] "
                  f"({res.saved} posts saved, {res.scanned} checked). Stopped: {res.stop_reason}.")
    if res.skipped:
        t = Table("Skipped because", "Count")
        for reason, n in sorted(res.skipped.items(), key=lambda x: -x[1]):
            t.add_row(reason, str(n))
        console.print(t)
    if res.failed_accounts:
        console.print(f"[yellow]Accounts needing `jobscout account login`: {', '.join(res.failed_accounts)}[/yellow]")
    if res.unprocessed_tags:
        console.print(f"[yellow]Tags not processed (no working account left): {', '.join(res.unprocessed_tags)}[/yellow]")


# ---------------- posts / contacts ----------------
@posts_app.command("list")
def posts_list(limit: int = typer.Option(20, "--limit", "-n"), run_id: int = typer.Option(None, "--run")):
    with new_session() as s:
        q = select(Post).where(Post.user_id == _user_id()).order_by(Post.id.desc()).limit(limit)
        if run_id:
            q = q.where(Post.run_id == run_id)
        t = Table("ID", "Posted", "Author", "Hiring for", "Emails", "Phones", "URL", show_lines=True)
        for p in s.scalars(q):
            t.add_row(str(p.id), p.posted_at.strftime("%Y-%m-%d") if p.posted_at else "?", p.author_name or "-",
                      p.hiring_for or "-", "\n".join(p.emails) or "-", "\n".join(p.phones) or "-", p.url or "")
        console.print(t)


def _contact_rows(s):
    q = (select(Contact, EmailOutreach.status)
         .outerjoin(EmailOutreach, EmailOutreach.contact_id == Contact.id)
         .where(Contact.user_id == _user_id())
         .order_by(Contact.id))
    return s.execute(q).all()


@contacts_app.command("list")
def contacts_list():
    with new_session() as s:
        t = Table("ID", "Name", "Email", "Phone", "Email status")
        for c, st in _contact_rows(s):
            t.add_row(str(c.id), c.name or "-", c.email or "-", c.phone or "-", st.value if st else "-")
        console.print(t)


@contacts_app.command("export")
def contacts_export(path: Path = typer.Argument(Path("contacts.csv"))):
    with new_session() as s, path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "email", "phone", "email_status", "created_at"])
        n = 0
        for c, st in _contact_rows(s):
            w.writerow([c.id, c.name, c.email, c.phone, st.value if st else "", c.created_at.isoformat()])
            n += 1
    console.print(f"Exported {n} contacts to {path.resolve()}")


# ---------------- email ----------------
@email_app.command("draft")
def email_draft(limit: int = typer.Option(50, "--limit", "-n")):
    """Write emails (Gemini, or template fallback) for all 'pending' contacts."""
    from jobscout.mailer.worker import draft_pending

    with console.status("Drafting…"):
        counts = draft_pending(limit, user_id=_user_id(), env_fallback=True,
                               on_item=lambda r, src: console.print(f"  drafted #{r.id} → {r.contact.email} ({src})"))
    console.print(f"[green]Drafted {sum(counts.values())}[/green] (AI: {counts['ai']}, template: {counts['template']}).")


@email_app.command("show")
def email_show(outreach_id: int):
    """Print one drafted email."""
    with new_session() as s:
        r = s.get(EmailOutreach, outreach_id)
        if not r or r.contact.user_id != _user_id():
            raise typer.BadParameter(f"No email #{outreach_id}")
        console.print(f"[bold]To:[/bold] {r.contact.email}\n[bold]Status:[/bold] {r.status.value}\n"
                      f"[bold]Subject:[/bold] {r.subject}\n\n{r.body}")


@email_app.command("send")
def email_send(limit: int = typer.Option(20, "--limit", "-n"),
               dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent.")):
    """Send drafted emails via Gmail (your saved sender from the UI, else GMAIL_* in .env)."""
    from jobscout.mailer.worker import send_drafted

    def on_item(row, outcome):
        colour = {"sent": "green", "failed": "red", "retry": "yellow"}[outcome]
        err = row.last_error
        console.print(f"  [{colour}]{outcome}[/{colour}] {row.contact.email}" + (f" — {err}" if err and outcome != "sent" else ""))

    res = send_drafted(limit, dry_run, on_item=on_item, user_id=_user_id(), env_fallback=True)
    if res.budget == 0:
        console.print("[yellow]Daily email cap reached (or limit 0). Nothing sent.[/yellow]")
    elif dry_run:
        for to, subj, body in res.previews:
            console.rule(to)
            console.print(f"[bold]{subj}[/bold]\n{body}")
        console.print(f"{len(res.previews)} email(s) would be sent.")
    else:
        console.print(f"sent {res.sent}, failed {res.failed}, will retry {res.retry_later}")


@email_app.command("check")
def email_check():
    """Test the Gmail login only (nothing is sent)."""
    from jobscout.mailer.sender_config import SenderNotConfigured, load_sender
    from jobscout.mailer.smtp import AuthFailed, ConnectionBlocked, GmailSender

    try:
        with new_session() as s:
            cfg = load_sender(s, _user_id(), env_fallback=True)
        with GmailSender(cfg) as sender:
            via = " via port 465 (587 is blocked here)" if sender.used_fallback else ""
        console.print(f"[green]Gmail login OK ({cfg.gmail}){via}.[/green]")
    except (AuthFailed, SenderNotConfigured, ConnectionBlocked) as e:
        console.print(f"[red]{e}[/red]")
    except Exception as e:
        console.print(f"[red]{type(e).__name__}: {e}[/red] (network/firewall/antivirus blocking port 587?)")


@email_app.command("stats")
def email_stats():
    from jobscout.mailer.worker import stats

    t = Table("Status", "Count")
    for k, v in stats(_user_id()).items():
        t.add_row(k, str(v))
    console.print(t)


@email_app.command("mark")
def email_mark(outreach_id: int, status: EmailStatus, reason: str = typer.Option(None, "--reason")):
    """Manually set a status, e.g. replied / bounced / skipped --reason "opted out" / drafted (to resend)."""
    from jobscout.mailer.worker import mark

    mark(outreach_id, status, reason, user_id=_user_id())
    console.print(f"Email #{outreach_id} → {status.value}")


if __name__ == "__main__":
    app()
