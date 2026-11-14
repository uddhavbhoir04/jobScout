"""Gmail SMTP sender (App Password). Host/port are configurable so tests can use a local fake server."""
import mimetypes
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from jobscout.config import get_settings
from jobscout.mailer.sender_config import SenderConfig


class PermanentSendError(Exception):
    """Recipient rejected: retrying won't help."""


class AuthFailed(Exception):
    """Gmail rejected the address / App Password."""


class ConnectionBlocked(Exception):
    """Neither SMTP port could be reached: something on the PC/network blocks outgoing mail."""


class StageError(Exception):
    def __init__(self, port: int, stage: str, cause: BaseException, issuer: str | None = None):
        self.port, self.stage, self.cause, self.issuer = port, stage, cause, issuer
        super().__init__(f"port {port} failed at {stage} ({type(cause).__name__}: {cause})")


def _auth_failure_message(e: smtplib.SMTPAuthenticationError, gmail: str) -> str:
    """Explain Gmail's actual answer (it uses different codes for different problems)."""
    text = e.smtp_error.decode(errors="replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
    text = " ".join(text.split())
    reply = f"Gmail said: {e.smtp_code} {text}"
    where = getattr(e, "jobscout_where", "")
    low = text.lower()
    if "application-specific password required" in low or "5.7.9" in low:
        hint = "That was your normal Gmail password. Gmail needs a 16-letter App Password here."
    elif "badcredentials" in low or "5.7.8" in low or "not accepted" in low:
        hint = (f"Gmail doesn't accept this App Password for {gmail}. Common reasons: it was created while "
                f"signed in to a different Google account (it must be created for {gmail}); it was revoked "
                "(App Passwords stop working when you change your Google password or delete them); or a "
                "letter was mistyped. Create a new one at myaccount.google.com/apppasswords while signed in "
                f"as {gmail}, and paste it here.")
    elif "webloginrequired" in low or "5.7.14" in low:
        hint = ("Google wants you to sign in once in a browser first (security check). Open gmail.com, "
                "sign in, approve any 'Was this you?' prompt, then try again.")
    elif "too many" in low or "4.7.0" in low:
        hint = "Too many login attempts. Wait 15–30 minutes, then try again."
    elif "google" not in where.lower() and "unknown" not in where.lower():
        hint = ("This answer did not come from Google: something on this PC (antivirus/firewall) answered "
                "the connection. Allow python.exe in it or turn off its email/SSL scanning.")
    else:
        hint = "Create a new App Password at myaccount.google.com/apppasswords and paste it here."
    return f"{reply}. {hint}" + (f" [{where}]" if where else "")


def _cert_issuer(server) -> str | None:
    """Organisation that issued the TLS certificate we got. Google for a clean connection;
    an antivirus/proxy name if something is decrypting the traffic."""
    try:
        cert = server.sock.getpeercert()
        fields = {k: v for rdn in cert.get("issuer", ()) for k, v in rdn}
        return fields.get("organizationName") or fields.get("commonName")
    except Exception:
        return None


def _is_google_issuer(name: str) -> bool:
    n = name.lower()
    return "google" in n or n in {"gts", "gtsca"} or n.startswith("wr2") or n.startswith("we2")


def _quietly_close(server) -> None:
    if server is not None:
        try:
            server.close()
        except Exception:
            pass


class GmailSender:
    def __init__(self, cfg: SenderConfig):
        if not (cfg.gmail and cfg.app_password):
            raise AuthFailed("Gmail address and App Password are required.")
        self.cfg = cfg
        self._server: smtplib.SMTP | None = None
        self._attachment: tuple[bytes, str, str, str] | None = None
        if cfg.resume_path:
            p = Path(cfg.resume_path)
            mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            main, sub = mime.split("/", 1)
            self._attachment = (p.read_bytes(), main, sub, p.name)

    def _attempt(self, port: int, implicit_ssl: bool, mechanism: str | None = None) -> smtplib.SMTP:
        """Connect + secure + log in on one port. Raises StageError naming the step that failed.

        mechanism=None lets smtplib choose (PLAIN for Gmail); "LOGIN" forces AUTH LOGIN, which some
        intercepting proxies handle when they break AUTH PLAIN."""
        s = get_settings()
        ctx = ssl.create_default_context()
        stage = "connect"
        server = None
        issuer = None
        try:
            if implicit_ssl:
                server = smtplib.SMTP_SSL(s.smtp_host, port, timeout=30, context=ctx)
            else:
                server = smtplib.SMTP(s.smtp_host, port, timeout=30)
                if s.smtp_starttls:
                    stage = "secure connection (STARTTLS)"
                    server.starttls(context=ctx)
            issuer = _cert_issuer(server)
            stage = "login" + (f" (AUTH {mechanism})" if mechanism else "")
            user, pw = self.cfg.gmail, self.cfg.app_password.replace(" ", "")
            if mechanism == "LOGIN":
                server.ehlo_or_helo_if_needed()
                server.user, server.password = user, pw
                code, resp = server.auth("LOGIN", server.auth_login, initial_response_ok=False)
                if code not in (235, 503):
                    raise smtplib.SMTPAuthenticationError(code, resp)
            else:
                server.login(user, pw)
            return server
        except smtplib.SMTPAuthenticationError as e:
            _quietly_close(server)
            e.jobscout_where = (f"port {port}, {stage}, connection answered by "
                                f"{issuer or 'unknown'}")
            raise
        except (smtplib.SMTPException, OSError) as e:  # OSError covers ssl.SSLError, timeouts, resets
            _quietly_close(server)
            raise StageError(port, stage, e, issuer) from e

    def __enter__(self) -> "GmailSender":
        """Port 587 + STARTTLS first; if anything cuts the connection (antivirus mail shield, firewall,
        ISP), retry the whole connect + login on Gmail's port 465 with implicit SSL."""
        s = get_settings()
        self.used_fallback = False
        attempts = [(s.smtp_port, False, None)]
        if s.smtp_ssl_fallback_port:
            attempts.append((s.smtp_ssl_fallback_port, True, None))
        attempts.append((s.smtp_port, False, "LOGIN"))
        failures: list[StageError] = []
        for i, (port, implicit_ssl, mechanism) in enumerate(attempts):
            try:
                self._server = self._attempt(port, implicit_ssl, mechanism)
                self.used_fallback = i > 0
                return self
            except smtplib.SMTPAuthenticationError as e:
                raise AuthFailed(_auth_failure_message(e, self.cfg.gmail)) from e
            except StageError as e:
                failures.append(e)
        detail = "; ".join(str(f) for f in failures)
        issuers = {f.issuer for f in failures if f.issuer}
        intercepted = sorted(i for i in issuers if not _is_google_issuer(i))
        if intercepted:
            who = (f"Your connection to Gmail is being intercepted by '{intercepted[0]}' (the secure connection "
                   "was answered by it, not by Google). That is usually antivirus email/SSL scanning: "
                   "turn off its email or SSL/TLS scanning, or add python.exe as an exception.")
        elif issuers:
            who = ("The secure connection was answered by Google itself, so nothing is decrypting it, but the "
                   "connection is still cut during login: usually an antivirus/firewall rule blocking programs "
                   "from sending email (e.g. McAfee firewall), a VPN, or the network.")
        else:
            who = ("Usual causes: antivirus 'email protection' / 'mail shield' / 'SSL scanning', a firewall, "
                   "VPN, or the network (office/college Wi-Fi often blocks email).")
        raise ConnectionBlocked(
            f"Couldn't log in to {s.smtp_host}: {detail}. Gmail never got to check the password, so this "
            f"is the PC or network, not your password. {who}"
        ) from failures[-1]

    def __exit__(self, *exc) -> None:
        self._close()

    def _close(self) -> None:
        if self._server:
            try:
                self._server.quit()
            except (smtplib.SMTPException, OSError):
                pass
            self._server = None

    def send(self, to: str, subject: str, body: str, attach_resume: bool = True) -> str:
        msg = EmailMessage()
        msg["From"] = formataddr((self.cfg.sender_name or "", self.cfg.gmail))
        msg["To"] = to
        msg["Subject"] = subject
        msg["Message-ID"] = make_msgid(domain=self.cfg.gmail.split("@")[-1])
        msg.set_content(body)
        if self._attachment and attach_resume:
            data, main, sub, name = self._attachment
            msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
        try:
            refused = self._server.send_message(msg)
        except smtplib.SMTPRecipientsRefused as e:
            raise PermanentSendError(_describe(e.recipients)) from e
        if refused:
            raise PermanentSendError(_describe(refused))
        return msg["Message-ID"]


def _describe(refused: dict) -> str:
    """{'a@b.c': (550, b'No such user')} -> 'a@b.c: 550 No such user'"""
    parts = []
    for addr, (code, text) in refused.items():
        text = text.decode(errors="replace") if isinstance(text, bytes) else str(text)
        parts.append(f"{addr}: {code} {text}")
    return "; ".join(parts)
