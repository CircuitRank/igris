"""
Local IMAP Email Service for Igris AI Assistant.

Uses Python standard library (`imaplib`, `ssl`, `email`, `html`) so no external
dependencies or cloud OAuth consoles are required. Supports Gmail, Outlook,
iCloud, Yahoo, and custom IMAP servers via App Passwords or standard IMAP credentials.
"""

import email
import email.header
import email.utils
import html
import imaplib
import re
import ssl
from email.message import Message
from typing import Any, Optional

IMAP_PRESETS: dict[str, tuple[str, int]] = {
    "gmail": ("imap.gmail.com", 993),
    "outlook": ("outlook.office365.com", 993),
    "icloud": ("imap.mail.me.com", 993),
    "yahoo": ("imap.mail.yahoo.com", 993),
}

# Cache most recent inbox UID list in memory so the LLM can refer to "email #1" or UID
_recent_uid_index: list[str] = []


def init_email_tables(db_conn, db_lock) -> None:
    """Ensure the settings table exists in SQLite."""
    with db_lock:
        cur = db_conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
        )
        db_conn.commit()


def _get_setting(cur, key: str, default: str = "") -> str:
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    return row[0] if row and row[0] is not None else default


def _set_setting(cur, key: str, value: str) -> None:
    cur.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def resolve_imap_endpoint(
    provider: str, imap_host: str = "", imap_port: int | str = 993
) -> tuple[str, int]:
    """Resolve IMAP host and port from provider preset or custom input."""
    prov = (provider or "gmail").strip().lower()
    host = (imap_host or "").strip()
    try:
        port = int(imap_port or 993)
    except (TypeError, ValueError):
        port = 993

    if prov in IMAP_PRESETS and not host:
        return IMAP_PRESETS[prov]
    if prov in IMAP_PRESETS and prov != "custom":
        # Use preset host unless custom provider is selected
        preset_host, preset_port = IMAP_PRESETS[prov]
        return (host or preset_host, port or preset_port)
    return (host, port)


def get_email_settings(
    db_conn, db_lock, include_secret: bool = False
) -> dict[str, Any]:
    """Read stored email configuration from SQLite."""
    with db_lock:
        cur = db_conn.cursor()
        provider = _get_setting(cur, "email_provider", "gmail")
        email_address = _get_setting(cur, "email_address", "")
        password = _get_setting(cur, "email_password", "")
        imap_host = _get_setting(cur, "email_imap_host", "")
        imap_port_str = _get_setting(cur, "email_imap_port", "993")

    resolved_host, resolved_port = resolve_imap_endpoint(
        provider, imap_host, imap_port_str
    )
    configured = bool(email_address and password and resolved_host)

    result: dict[str, Any] = {
        "configured": configured,
        "provider": provider,
        "email_address": email_address,
        "imap_host": resolved_host,
        "imap_port": resolved_port,
        "has_password": bool(password),
    }
    if include_secret:
        result["app_password"] = password
    return result


def save_email_settings(
    db_conn,
    db_lock,
    provider: str,
    email_address: str,
    app_password: Optional[str],
    imap_host: str = "",
    imap_port: int = 993,
) -> dict[str, Any]:
    """Persist email configuration to SQLite."""
    prov = (provider or "gmail").strip().lower()
    addr = (email_address or "").strip()
    resolved_host, resolved_port = resolve_imap_endpoint(prov, imap_host, imap_port)

    with db_lock:
        cur = db_conn.cursor()
        existing_pw = _get_setting(cur, "email_password", "")
        final_pw = app_password if (app_password is not None and app_password != "") else existing_pw

        # Common convenience: Gmail 16-char app passwords are displayed as "xxxx xxxx xxxx xxxx"
        if prov == "gmail" and " " in final_pw and len(final_pw.replace(" ", "")) == 16:
            final_pw = final_pw.replace(" ", "")

        _set_setting(cur, "email_provider", prov)
        _set_setting(cur, "email_address", addr)
        _set_setting(cur, "email_password", final_pw)
        _set_setting(cur, "email_imap_host", resolved_host)
        _set_setting(cur, "email_imap_port", str(resolved_port))
        db_conn.commit()

    return get_email_settings(db_conn, db_lock, include_secret=False)


def clear_email_settings(db_conn, db_lock) -> None:
    """Remove stored email credentials."""
    with db_lock:
        cur = db_conn.cursor()
        cur.execute("DELETE FROM settings WHERE key LIKE 'email_%'")
        db_conn.commit()


def _connect_and_login(
    host: str, port: int, email_address: str, password: str
) -> tuple[imaplib.IMAP4_SSL, str]:
    """Open an IMAP4_SSL connection and authenticate, retrying stripped spaces if needed."""
    if not host:
        raise ValueError("IMAP host is required.")
    if not email_address or not password:
        raise ValueError("Email address and App Password are required.")

    ctx = ssl.create_default_context()
    client = imaplib.IMAP4_SSL(host, int(port), ssl_context=ctx, timeout=15)
    try:
        client.login(email_address, password)
        return client, password
    except imaplib.IMAP4.error as first_err:
        # Retry once with spaces removed in case user pasted grouped App Password
        compact_pw = password.replace(" ", "")
        if compact_pw != password and compact_pw:
            try:
                client = imaplib.IMAP4_SSL(host, int(port), ssl_context=ctx, timeout=15)
                client.login(email_address, compact_pw)
                return client, compact_pw
            except Exception:
                pass
        try:
            client.logout()
        except Exception:
            pass
        raise first_err


def _friendly_imap_error(exc: Exception, provider: str = "") -> str:
    raw = str(exc)
    low = raw.lower()
    if "authenticationfailed" in low or "invalid credentials" in low or "login failed" in low:
        if provider == "gmail":
            return (
                "Authentication failed. Gmail requires a 16-character App Password "
                "(Google Account -> Security -> 2-Step Verification -> App passwords)."
            )
        if provider == "icloud":
            return (
                "Authentication failed. iCloud Mail requires an App-Specific Password "
                "generated at appleid.apple.com."
            )
        return "Authentication failed. Check your email address and App Password."
    if "timed out" in low or "timeout" in low:
        return "Connection timed out reaching the IMAP server. Check host, port, or firewall."
    if "name or service not known" in low or "nodename nor servname" in low or "getaddrinfo" in low:
        return "Could not resolve IMAP server hostname. Check the IMAP host setting."
    return f"IMAP error: {raw}"


def test_imap_connection(
    provider: str,
    email_address: str,
    app_password: str,
    imap_host: str = "",
    imap_port: int = 993,
) -> dict[str, Any]:
    """Verify IMAP credentials and return unread count."""
    prov = (provider or "gmail").strip().lower()
    host, port = resolve_imap_endpoint(prov, imap_host, imap_port)
    client = None
    try:
        client, used_pw = _connect_and_login(host, port, email_address.strip(), app_password)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            return {"ok": False, "message": "Connected, but could not open INBOX."}
        s_unseen, unseen_data = client.uid("search", None, "UNSEEN")
        unread_count = (
            len(unseen_data[0].split())
            if s_unseen == "OK" and unseen_data and unseen_data[0]
            else 0
        )
        return {
            "ok": True,
            "message": f"Connected to {host} ({unread_count} unread in Inbox).",
            "unread_count": unread_count,
            "normalized_password": used_pw,
        }
    except Exception as exc:
        return {"ok": False, "message": _friendly_imap_error(exc, prov)}
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass


def decode_mime_header(value: Optional[str]) -> str:
    """Decode RFC 2047 encoded email header strings safely."""
    if not value:
        return ""
    parts = []
    try:
        for chunk, enc in email.header.decode_header(value):
            if isinstance(chunk, bytes):
                charset = enc or "utf-8"
                try:
                    parts.append(chunk.decode(charset, errors="replace"))
                except LookupError:
                    parts.append(chunk.decode("utf-8", errors="replace"))
            else:
                parts.append(str(chunk))
    except Exception:
        return str(value).strip()
    return "".join(parts).strip()


def html_to_readable_text(raw_html: str) -> str:
    """Convert HTML email markup into clean, readable plain text."""
    if not raw_html:
        return ""
    cleaned = re.sub(r"(?is)<(script|style|head|noscript).*?>.*?</\1>", " ", raw_html)
    cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|blockquote)>", "\n", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    # Normalize horizontal whitespace while keeping paragraph breaks
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in cleaned.splitlines()]
    compact_lines = []
    blank_streak = 0
    for ln in lines:
        if not ln:
            blank_streak += 1
            if blank_streak <= 1:
                compact_lines.append("")
        else:
            blank_streak = 0
            compact_lines.append(ln)
    return "\n".join(compact_lines).strip()


def _extract_body_and_attachments(msg: Message) -> tuple[str, list[dict[str, Any]]]:
    """Extract clean readable text and attachment metadata from an email.message.Message."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict[str, Any]] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition") or "")
            filename = part.get_filename()
            if filename or "attachment" in disposition.lower():
                decoded_name = decode_mime_header(filename) or "attachment"
                payload = part.get_payload(decode=True) or b""
                attachments.append(
                    {
                        "filename": decoded_name,
                        "content_type": content_type,
                        "size": len(payload),
                    }
                )
                continue

            if content_type in ("text/plain", "text/html"):
                payload_bytes = part.get_payload(decode=True)
                if payload_bytes is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                try:
                    decoded = payload_bytes.decode(charset, errors="replace")
                except LookupError:
                    decoded = payload_bytes.decode("utf-8", errors="replace")

                if content_type == "text/plain":
                    plain_parts.append(decoded.strip())
                else:
                    html_parts.append(decoded.strip())
    else:
        content_type = msg.get_content_type()
        payload_bytes = msg.get_payload(decode=True)
        if payload_bytes is not None:
            charset = msg.get_content_charset() or "utf-8"
            try:
                decoded = payload_bytes.decode(charset, errors="replace")
            except LookupError:
                decoded = payload_bytes.decode("utf-8", errors="replace")
            if content_type == "text/html":
                html_parts.append(decoded.strip())
            else:
                plain_parts.append(decoded.strip())

    body = "\n\n".join(p for p in plain_parts if p).strip()
    if not body and html_parts:
        body = html_to_readable_text("\n".join(html_parts))
    elif body and len(body) < 20 and html_parts:
        # Fallback when text/plain is an empty stub
        html_text = html_to_readable_text("\n".join(html_parts))
        if len(html_text) > len(body):
            body = html_text

    return body, attachments


def _parse_date(date_hdr: str) -> tuple[str, str]:
    """Return (display_date, iso_date) from RFC 2822 Date header."""
    if not date_hdr:
        return ("", "")
    try:
        dt = email.utils.parsedate_to_datetime(date_hdr)
        if dt.tzinfo is not None:
            dt_local = dt.astimezone()
        else:
            dt_local = dt
        return (dt_local.strftime("%b %d, %H:%M"), dt_local.isoformat())
    except Exception:
        return (date_hdr[:22], "")


def fetch_inbox_messages(
    db_conn,
    db_lock,
    unread_only: bool = False,
    limit: int = 25,
    search_query: str = "",
) -> dict[str, Any]:
    """Fetch recent or unread inbox emails in a single pipelined IMAP batch."""
    global _recent_uid_index
    cfg = get_email_settings(db_conn, db_lock, include_secret=True)
    if not cfg["configured"]:
        return {
            "ok": False,
            "configured": False,
            "unread_count": 0,
            "email_address": cfg.get("email_address", ""),
            "messages": [],
            "error": "Email account is not configured yet. Open Settings -> Email to connect.",
        }

    limit = max(1, min(int(limit or 25), 50))
    query_lower = (search_query or "").strip().lower()
    client = None

    try:
        client, _ = _connect_and_login(
            cfg["imap_host"],
            cfg["imap_port"],
            cfg["email_address"],
            cfg["app_password"],
        )
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            return {
                "ok": False,
                "configured": True,
                "unread_count": 0,
                "email_address": cfg["email_address"],
                "messages": [],
                "error": "Unable to open INBOX folder.",
            }

        s_unseen, unseen_data = client.uid("search", None, "UNSEEN")
        unseen_uids: list[bytes] = (
            unseen_data[0].split()
            if s_unseen == "OK" and unseen_data and unseen_data[0]
            else []
        )
        unseen_set = {u.decode("ascii", errors="ignore") for u in unseen_uids}
        unread_count = len(unseen_set)

        if unread_only:
            candidate_uids = unseen_uids
        else:
            s_all, all_data = client.uid("search", None, "ALL")
            candidate_uids = (
                all_data[0].split()
                if s_all == "OK" and all_data and all_data[0]
                else []
            )

        if not candidate_uids:
            _recent_uid_index = []
            return {
                "ok": True,
                "configured": True,
                "unread_count": unread_count,
                "email_address": cfg["email_address"],
                "messages": [],
            }

        # Newest UIDs last in IMAP search output -> slice window from the tail
        fetch_window = limit * 3 if query_lower else limit
        selected_uids = candidate_uids[-fetch_window:]
        uid_set_bytes = b",".join(selected_uids)

        # Fetch flags + first 8KB of RFC822 message (headers + preview snippet) in one roundtrip
        f_status, raw_items = client.uid(
            "fetch", uid_set_bytes, "(FLAGS BODY.PEEK[]<0.8192>)"
        )
        if f_status != "OK" or not raw_items:
            return {
                "ok": False,
                "configured": True,
                "unread_count": unread_count,
                "email_address": cfg["email_address"],
                "messages": [],
                "error": "Failed to fetch message headers from IMAP server.",
            }

        parsed_by_uid: dict[str, dict[str, Any]] = {}
        for item in raw_items:
            if not isinstance(item, tuple) or len(item) < 2:
                continue
            meta_bytes, msg_bytes = item[0], item[1]
            meta_str = meta_bytes.decode("ascii", errors="ignore")

            uid_match = re.search(r"\bUID\s+(\d+)\b", meta_str, re.IGNORECASE)
            if not uid_match:
                continue
            uid_str = uid_match.group(1)

            flags_match = re.search(r"FLAGS\s*\(([^)]*)\)", meta_str, re.IGNORECASE)
            flags_str = flags_match.group(1) if flags_match else ""
            is_unread = ("\\Seen" not in flags_str) or (uid_str in unseen_set and "\\Seen" not in flags_str)

            msg_obj = email.message_from_bytes(msg_bytes)
            subject = decode_mime_header(msg_obj.get("Subject")) or "(No subject)"
            from_raw = decode_mime_header(msg_obj.get("From"))
            from_name, from_addr = email.utils.parseaddr(from_raw)
            from_name = decode_mime_header(from_name) or from_addr or "Unknown Sender"
            display_date, iso_date = _parse_date(decode_mime_header(msg_obj.get("Date")))

            body_preview, _ = _extract_body_and_attachments(msg_obj)
            snippet = re.sub(r"\s+", " ", body_preview).strip()[:180]

            if query_lower:
                haystack = f"{subject} {from_name} {from_addr} {snippet}".lower()
                if query_lower not in haystack:
                    continue

            parsed_by_uid[uid_str] = {
                "uid": uid_str,
                "subject": subject,
                "from_name": from_name,
                "from_email": from_addr,
                "date": display_date,
                "date_iso": iso_date,
                "unread": is_unread,
                "snippet": snippet,
            }

        # Order newest first matching selected_uids reversed
        ordered_messages = []
        for u_bytes in reversed(selected_uids):
            u_str = u_bytes.decode("ascii", errors="ignore")
            if u_str in parsed_by_uid:
                ordered_messages.append(parsed_by_uid[u_str])
                if len(ordered_messages) >= limit:
                    break

        _recent_uid_index = [m["uid"] for m in ordered_messages]

        return {
            "ok": True,
            "configured": True,
            "unread_count": unread_count,
            "email_address": cfg["email_address"],
            "messages": ordered_messages,
        }
    except Exception as exc:
        return {
            "ok": False,
            "configured": True,
            "unread_count": 0,
            "email_address": cfg["email_address"],
            "messages": [],
            "error": _friendly_imap_error(exc, cfg.get("provider", "")),
        }
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass


def fetch_email_detail(
    db_conn,
    db_lock,
    uid: Optional[str] = None,
    index: Optional[int] = None,
    mark_read: bool = True,
) -> dict[str, Any]:
    """Fetch full content of a single email by UID or 1-based recent list index."""
    cfg = get_email_settings(db_conn, db_lock, include_secret=True)
    if not cfg["configured"]:
        return {
            "ok": False,
            "error": "Email account is not configured yet.",
        }

    target_uid = (str(uid).strip() if uid else "")
    if not target_uid and index is not None:
        try:
            idx = int(index) - 1
            if 0 <= idx < len(_recent_uid_index):
                target_uid = _recent_uid_index[idx]
        except (TypeError, ValueError):
            pass

    if not target_uid or not target_uid.isdigit():
        return {
            "ok": False,
            "error": "Valid email UID or message index is required.",
        }

    client = None
    try:
        client, _ = _connect_and_login(
            cfg["imap_host"],
            cfg["imap_port"],
            cfg["email_address"],
            cfg["app_password"],
        )
        status, _ = client.select("INBOX", readonly=not mark_read)
        if status != "OK":
            return {"ok": False, "error": "Unable to open INBOX."}

        f_status, raw_items = client.uid(
            "fetch", target_uid.encode("ascii"), "(FLAGS RFC822)"
        )
        if f_status != "OK" or not raw_items:
            return {"ok": False, "error": f"Email UID {target_uid} not found."}

        msg_bytes = None
        flags_str = ""
        for item in raw_items:
            if isinstance(item, tuple) and len(item) >= 2:
                meta_str = item[0].decode("ascii", errors="ignore")
                flags_match = re.search(r"FLAGS\s*\(([^)]*)\)", meta_str, re.IGNORECASE)
                if flags_match:
                    flags_str = flags_match.group(1)
                msg_bytes = item[1]
                break

        if not msg_bytes:
            return {"ok": False, "error": f"Could not read email UID {target_uid}."}

        if mark_read and "\\Seen" not in flags_str:
            try:
                client.uid("store", target_uid.encode("ascii"), "+FLAGS", "(\\Seen)")
                flags_str += " \\Seen"
            except Exception:
                pass

        msg_obj = email.message_from_bytes(msg_bytes)
        subject = decode_mime_header(msg_obj.get("Subject")) or "(No subject)"
        from_raw = decode_mime_header(msg_obj.get("From"))
        from_name, from_addr = email.utils.parseaddr(from_raw)
        from_name = decode_mime_header(from_name) or from_addr or "Unknown Sender"
        to_raw = decode_mime_header(msg_obj.get("To"))
        display_date, iso_date = _parse_date(decode_mime_header(msg_obj.get("Date")))
        body_text, attachments = _extract_body_and_attachments(msg_obj)

        return {
            "ok": True,
            "email": {
                "uid": target_uid,
                "subject": subject,
                "from_name": from_name,
                "from_email": from_addr,
                "to": to_raw,
                "date": display_date,
                "date_iso": iso_date,
                "unread": "\\Seen" not in flags_str,
                "body": body_text[:25000] if body_text else "(Empty message body)",
                "attachments": attachments,
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": _friendly_imap_error(exc, cfg.get("provider", "")),
        }
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass


def format_emails_for_llm(inbox_result: dict[str, Any]) -> str:
    """Format fetched inbox messages as concise structured text for LLM tool output."""
    if not inbox_result.get("ok"):
        return f"Email check failed: {inbox_result.get('error', 'Unknown error')}"

    messages = inbox_result.get("messages", [])
    unread_total = inbox_result.get("unread_count", 0)
    account = inbox_result.get("email_address", "")

    if not messages:
        return f"Inbox ({account}) has {unread_total} unread emails. No matching emails found."

    lines = [
        f"Inbox ({account}) — {unread_total} total unread. Showing {len(messages)} email(s):"
    ]
    for idx, m in enumerate(messages, start=1):
        state = "UNREAD" if m.get("unread") else "READ"
        sender = (
            f"{m['from_name']} <{m['from_email']}>"
            if m.get("from_email") and m["from_email"] != m["from_name"]
            else m["from_name"]
        )
        snippet = m.get("snippet", "")
        lines.append(
            f"{idx}. [UID {m['uid']}] [{state}] {m.get('date', '')} | From: {sender} | "
            f"Subject: {m['subject']}"
            + (f"\n   Preview: {snippet}" if snippet else "")
        )
    return "\n".join(lines)

