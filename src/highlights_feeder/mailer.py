import smtplib
import ssl
from datetime import date
from email.headerregistry import Address
from email.message import EmailMessage

from jinja2 import Environment, PackageLoader
from markupsafe import Markup, escape

from .config import Settings
from .selector import Highlight

# Notion's light-theme palette
TEXT_COLORS = {
    "gray": "#787774",
    "brown": "#9f6b53",
    "orange": "#d9730d",
    "yellow": "#cb912f",
    "green": "#448361",
    "blue": "#337ea9",
    "purple": "#9065b0",
    "pink": "#c14c8a",
    "red": "#d44c47",
}
BACKGROUND_COLORS = {
    "gray": "#f1f1ef",
    "brown": "#f4eeee",
    "orange": "#fbecdd",
    "yellow": "#fbf3db",
    "green": "#edf3ec",
    "blue": "#e7f3f8",
    "purple": "#f6f3f9",
    "pink": "#faf1f5",
    "red": "#fdebec",
}


def color_css(color: str | None) -> str:
    if not color:
        return ""
    if color.endswith("_background"):
        bg = BACKGROUND_COLORS.get(color.removesuffix("_background"))
        return f"background-color:{bg};" if bg else ""
    fg = TEXT_COLORS.get(color)
    return f"color:{fg};" if fg else ""


def rich_html(block: dict) -> Markup:
    """Render a body block's spans as inline HTML, escaping all text."""
    out = []
    for span in block.get("spans") or [{"text": block["text"]}]:
        html = str(escape(span["text"])).replace("\n", "<br>")
        if span.get("code"):
            html = (
                '<code style="font-family:monospace;background:#f0ebe0;'
                f'padding:1px 4px;border-radius:3px;">{html}</code>'
            )
        if span.get("bold"):
            html = f"<strong>{html}</strong>"
        if span.get("italic"):
            html = f"<em>{html}</em>"
        if span.get("underline"):
            html = f"<u>{html}</u>"
        if span.get("strikethrough"):
            html = f"<s>{html}</s>"
        if css := color_css(span.get("color")):
            html = f'<span style="{css}padding:0 2px;border-radius:2px;">{html}</span>'
        href = span.get("href") or ""
        if href.startswith(("https://", "http://")):
            html = f'<a href="{escape(href)}" style="color:inherit;">{html}</a>'
        out.append(html)
    return Markup("".join(out))


_env = Environment(
    loader=PackageLoader("highlights_feeder", "templates"),
    autoescape=lambda name: bool(name and name.endswith(".html.j2")),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["rich"] = rich_html
_env.filters["color_css"] = color_css


def render(
    highlights: list[Highlight], day: date, subject_prefix: str = "Daily Digest"
) -> tuple[str, str, str]:
    """Return (subject, plain text, html)."""
    subject = f"{subject_prefix} | {day:%A, %d %B %Y}"
    ctx = {"highlights": highlights, "day": day, "subject": subject}
    text = _env.get_template("digest.txt.j2").render(ctx)
    html = _env.get_template("digest.html.j2").render(ctx)
    return subject, text, html


def send(s: Settings, subject: str, text: str, html: str) -> None:
    missing = [k for k in ("smtp_user", "smtp_password", "email_to") if not getattr(s, k)]
    if missing:
        raise RuntimeError(f"Email settings missing: {', '.join(m.upper() for m in missing)}")
    assert s.smtp_user and s.smtp_password and s.email_to

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = Address(display_name=s.sender_name, addr_spec=s.email_from or s.smtp_user)
    msg["To"] = s.email_to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=ssl.create_default_context()) as smtp:
        smtp.login(s.smtp_user, s.smtp_password.get_secret_value())
        smtp.send_message(msg)
