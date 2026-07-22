"""Server-rendered, Olmem-branded HTML for the admin panel.

Pure rendering helpers — no database or network access here. Every dynamic
value is escaped. The look mirrors the Olmem Tech site: deep navy, brand blue,
clean cards.
"""
from __future__ import annotations

import html
from datetime import datetime
from typing import Any

BRAND = {
    "navy": "#071a2d",
    "navy2": "#0d2945",
    "blue": "#1689d8",
    "blue_dark": "#0f6fae",
    "cyan": "#59c7e8",
    "ink": "#102033",
    "muted": "#5f7186",
    "border": "#e0e8f0",
    "bg": "#f4f7fb",
    "danger": "#c94755",
    "warn": "#b77912",
    "success": "#16866c",
}

CSS = f"""
*{{box-sizing:border-box}}
body{{margin:0;background:{BRAND['bg']};color:{BRAND['ink']};
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5}}
a{{color:{BRAND['blue_dark']};text-decoration:none}}
a:hover{{text-decoration:underline}}
button,input,select,textarea{{font:inherit}}
.shell{{width:min(1180px,calc(100% - 40px));margin:0 auto;padding:28px 0 60px}}
.topbar{{background:linear-gradient(135deg,{BRAND['navy']},{BRAND['navy2']});color:#fff}}
.topbar .inner{{width:min(1180px,calc(100% - 40px));margin:0 auto;display:flex;align-items:center;
  justify-content:space-between;min-height:66px;gap:20px;flex-wrap:wrap}}
.brand{{display:flex;align-items:center;gap:11px;color:#fff}}
.brand .mark{{width:34px;height:34px;border-radius:8px;background:{BRAND['blue']};
  display:grid;place-items:center;font-weight:800;color:#fff;font-size:1rem}}
.brand strong{{font-size:1.02rem;letter-spacing:.02em;text-transform:uppercase}}
.brand small{{display:block;font-size:.62rem;color:{BRAND['cyan']};letter-spacing:.13em;text-transform:uppercase}}
.navlinks{{display:flex;align-items:center;gap:6px;flex-wrap:wrap}}
.navlinks a{{color:#cfe0ee;padding:8px 13px;border-radius:7px;font-size:.9rem;font-weight:600}}
.navlinks a:hover{{background:rgba(255,255,255,.08);text-decoration:none}}
.navlinks a.active{{background:{BRAND['blue']};color:#fff}}
.navlinks form{{margin:0}}
.eyebrow{{color:{BRAND['blue']};font-weight:800;text-transform:uppercase;letter-spacing:.13em;font-size:.72rem;margin:0 0 6px}}
h1{{font-size:1.9rem;margin:0 0 4px;color:{BRAND['navy']}}}
h2{{font-size:1.2rem;color:{BRAND['navy']};margin:0 0 12px}}
h3{{font-size:1rem;color:{BRAND['navy']};margin:0 0 8px}}
.muted{{color:{BRAND['muted']}}}
.card{{background:#fff;border:1px solid {BRAND['border']};border-radius:13px;padding:22px;
  box-shadow:0 10px 30px rgba(8,32,54,.05);margin-bottom:18px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px}}
.stat{{background:#fff;border:1px solid {BRAND['border']};border-radius:13px;padding:18px}}
.stat span{{color:{BRAND['muted']};font-size:.82rem}}
.stat strong{{display:block;font-size:1.9rem;color:{BRAND['navy']};margin-top:4px}}
.table{{width:100%;border-collapse:collapse}}
.table th,.table td{{text-align:left;padding:11px 10px;border-bottom:1px solid {BRAND['border']};
  font-size:.9rem;vertical-align:top}}
.table th{{color:{BRAND['muted']};font-size:.72rem;text-transform:uppercase;letter-spacing:.05em}}
.tableWrap{{overflow-x:auto}}
.badge{{display:inline-block;padding:3px 9px;border-radius:999px;font-size:.68rem;font-weight:800;
  text-transform:uppercase;letter-spacing:.04em}}
.b-blue{{background:#e8f4fc;color:{BRAND['blue_dark']}}}
.b-green{{background:#e6f6f1;color:{BRAND['success']}}}
.b-amber{{background:#fff4dc;color:{BRAND['warn']}}}
.b-red{{background:#fdebed;color:{BRAND['danger']}}}
.b-gray{{background:#eef2f7;color:{BRAND['muted']}}}
label{{display:block;font-weight:700;font-size:.83rem;margin:0 0 6px;color:#243a4f}}
input,select,textarea{{width:100%;border:1px solid #cdd9e5;background:#fff;color:{BRAND['ink']};
  padding:10px 11px;border-radius:7px;outline:none}}
input:focus,select:focus,textarea:focus{{border-color:{BRAND['blue']};box-shadow:0 0 0 3px rgba(22,137,216,.13)}}
.field{{margin-bottom:14px}}
.row{{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}}
.row .field{{flex:1;min-width:150px}}
.button{{display:inline-flex;align-items:center;justify-content:center;border:0;border-radius:7px;
  background:{BRAND['blue']};color:#fff;font-weight:700;padding:10px 16px;cursor:pointer}}
.button:hover{{background:{BRAND['blue_dark']}}}
.button.secondary{{background:#fff;color:{BRAND['navy']};border:1px solid #c2d0dd}}
.button.ghost{{background:rgba(255,255,255,.1);color:#fff}}
.button.small{{padding:7px 12px;font-size:.85rem}}
.button:disabled{{opacity:.5;cursor:not-allowed}}
.inline{{display:inline}}
.actions{{display:flex;gap:10px;flex-wrap:wrap;margin-top:6px}}
.flash{{padding:12px 15px;border-radius:9px;margin-bottom:18px;font-weight:600}}
.flash.ok{{background:#e6f6f1;color:{BRAND['success']};border:1px solid #b9e6d8}}
.flash.err{{background:#fdebed;color:{BRAND['danger']};border:1px solid #f2c4ca}}
.kv p{{margin:6px 0}}
.pill-row{{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}}
.login-wrap{{max-width:400px;margin:80px auto}}
.help{{font-size:.8rem;color:{BRAND['muted']};margin-top:4px}}
.weightGrid{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}}
pre{{white-space:pre-wrap;word-break:break-word;background:{BRAND['bg']};border:1px solid {BRAND['border']};
  border-radius:9px;padding:14px;font-size:.85rem}}
@media(max-width:820px){{.stats,.weightGrid{{grid-template-columns:1fr 1fr}}.grid2{{grid-template-columns:1fr}}}}
"""

_STATUS_BADGE = {
    "discovered": "b-gray",
    "needs_rescore": "b-amber",
    "research_failed": "b-red",
    "researched": "b-blue",
    "eligible": "b-green",
    "rejected": "b-red",
    "sending": "b-amber",
    "contacted": "b-blue",
    "drafted": "b-gray",
    "sent": "b-green",
    "delivered": "b-green",
    "opened": "b-green",
    "clicked": "b-green",
    "failed": "b-red",
    "bounce": "b-red",
    "complaint": "b-red",
    "unsubscribed": "b-red",
}


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def badge(status: Any) -> str:
    s = str(status or "—")
    return f'<span class="badge {_STATUS_BADGE.get(s, "b-gray")}">{esc(s)}</span>'


def _dt(value: Any) -> str:
    if not value:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return esc(value)


def _flash(msg: str | None, err: str | None) -> str:
    if err:
        return f'<div class="flash err">{esc(err)}</div>'
    if msg:
        return f'<div class="flash ok">{esc(msg)}</div>'
    return ""


def layout(title: str, active: str, body: str, authed: bool = True) -> str:
    nav = ""
    if authed:
        def link(href: str, key: str, text: str) -> str:
            cls = "active" if key == active else ""
            return f'<a class="{cls}" href="{href}">{text}</a>'
        nav = (
            '<nav class="navlinks">'
            + link("/admin", "dashboard", "Dashboard")
            + link("/admin/prospects", "prospects", "Prospects")
            + link("/admin/emails", "emails", "Emails")
            + link("/admin/criteria", "criteria", "Criteria")
            + '<form method="post" action="/admin/logout"><button class="button ghost small">Sign out</button></form>'
            + "</nav>"
        )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{esc(title)} · Olmem Outreach</title><style>{CSS}</style></head>
<body>
<div class="topbar"><div class="inner">
  <a class="brand" href="/admin"><span class="mark">O</span>
    <span><strong>Olmem Tech</strong><small>Outreach Console</small></span></a>
  {nav}
</div></div>
<div class="shell">{body}</div>
</body></html>"""


def login_page(error: str | None = None, configured: bool = True) -> str:
    warn = "" if configured else (
        '<div class="flash err">ADMIN_PASSWORD is not set on the server, so sign-in is disabled. '
        "Set it in the environment to use the console.</div>"
    )
    err = f'<div class="flash err">{esc(error)}</div>' if error else ""
    body = f"""
    <div class="login-wrap">
      <div class="card">
        <p class="eyebrow">Olmem Tech</p>
        <h1>Outreach Console</h1>
        <p class="muted">Sign in to manage prospects, emails, and criteria.</p>
        {warn}{err}
        <form method="post" action="/admin/login">
          <div class="field"><label for="password">Admin password</label>
            <input id="password" name="password" type="password" required autofocus></div>
          <button class="button" style="width:100%">Sign in</button>
        </form>
      </div>
    </div>"""
    return layout("Sign in", "", body, authed=False)


def _stat(label: str, value: Any) -> str:
    return f'<div class="stat"><span>{esc(label)}</span><strong>{esc(value)}</strong></div>'


def dashboard_page(stats: dict[str, Any], msg: str | None = None, err: str | None = None) -> str:
    totals = stats.get("totals", {})
    by_status = stats.get("by_status", {})
    catalog = stats.get("catalog")
    status_rows = "".join(
        f"<tr><td>{badge(s)}</td><td>{esc(c)}</td></tr>"
        for s, c in sorted(by_status.items(), key=lambda kv: kv[0])
    ) or '<tr><td colspan="2" class="muted">No prospects yet.</td></tr>'

    catalog_html = (
        f"<p><strong>{esc(catalog['catalog_version'])}</strong> · {esc(catalog.get('offers'))} offers "
        f"· built {_dt(catalog.get('created_at'))}</p>"
        if catalog else '<p class="muted">No active offer catalog yet. Run the catalog job.</p>'
    )

    jobs = "".join(
        f'<form class="inline" method="post" action="/admin/jobs/{j}">'
        f'<button class="button secondary small">{label}</button></form> '
        for j, label in [
            ("catalog", "Rebuild catalog"),
            ("discover", "Discover prospects"),
            ("research", "Research &amp; score"),
            ("send", "Run send job"),
        ]
    )

    body = f"""
    {_flash(msg, err)}
    <p class="eyebrow">Overview</p><h1>Dashboard</h1>
    <div class="stats">
      {_stat("Prospects", totals.get("prospects", 0))}
      {_stat("Eligible to send", totals.get("eligible", 0))}
      {_stat("Emails sent", totals.get("sent", 0))}
      {_stat("Sent (7 days)", totals.get("sent_7d", 0))}
    </div>
    <div class="grid2">
      <div class="card"><h2>Prospects by status</h2>
        <table class="table"><tbody>{status_rows}</tbody></table></div>
      <div class="card"><h2>Active offer catalog</h2>{catalog_html}
        <h3 style="margin-top:18px">Run a job now</h3>
        <p class="help">Manually trigger a pipeline step instead of waiting for the daily schedule. These can take a while (they call the LLM).</p>
        <div class="actions">{jobs}</div>
      </div>
    </div>"""
    return layout("Dashboard", "dashboard", body)


def prospects_page(rows: list[dict[str, Any]], status: str, search: str, msg: str | None = None, err: str | None = None) -> str:
    options = ["", "discovered", "researched", "needs_rescore", "eligible", "rejected", "sending", "contacted", "research_failed"]
    opts = "".join(
        f'<option value="{esc(o)}"{" selected" if o == status else ""}>{esc(o or "All statuses")}</option>'
        for o in options
    )
    trs = ""
    for r in rows:
        trs += (
            f"<tr><td><a href=\"/admin/prospects/{esc(r['id'])}\"><strong>{esc(r.get('company_name') or r.get('domain'))}</strong></a>"
            f"<br><span class=\"muted\">{esc(r.get('domain'))}</span></td>"
            f"<td>{esc(r.get('contact_email') or '—')}</td>"
            f"<td>{esc(r.get('fit_score') if r.get('fit_score') is not None else '—')}</td>"
            f"<td>{badge(r.get('status'))}</td>"
            f"<td>{esc(r.get('selected_offer_key') or '—')}</td>"
            f"<td>{_dt(r.get('updated_at'))}</td></tr>"
        )
    if not trs:
        trs = '<tr><td colspan="6" class="muted">No prospects match.</td></tr>'
    body = f"""
    {_flash(msg, err)}
    <p class="eyebrow">Pipeline</p><h1>Prospects</h1>
    <div class="card">
      <form class="row" method="get" action="/admin/prospects">
        <div class="field"><label>Search</label><input name="q" value="{esc(search)}" placeholder="Company, domain, or email"></div>
        <div class="field"><label>Status</label><select name="status">{opts}</select></div>
        <div class="field" style="flex:0"><button class="button">Filter</button></div>
      </form>
    </div>
    <div class="card tableWrap">
      <table class="table"><thead><tr><th>Company</th><th>Contact email</th><th>Fit</th><th>Status</th><th>Offer</th><th>Updated</th></tr></thead>
      <tbody>{trs}</tbody></table>
    </div>"""
    return layout("Prospects", "prospects", body)


def _json_block(value: Any) -> str:
    import json
    try:
        return f"<pre>{esc(json.dumps(value, indent=2, default=str))}</pre>"
    except Exception:
        return f"<pre>{esc(value)}</pre>"


def prospect_detail_page(p: dict[str, Any], messages: list[dict[str, Any]], msg: str | None = None, err: str | None = None) -> str:
    research = p.get("research_json") or {}
    fit = p.get("fit_json") or {}
    email = p.get("contact_email")
    can_send = bool(email and research and fit and p.get("selected_offer_key"))

    problems = research.get("observed_problems") if isinstance(research, dict) else None
    problems_html = "".join(f"<li>{esc(x)}</li>" for x in (problems or [])) or "<li class='muted'>None recorded</li>"

    msg_rows = ""
    for m in messages:
        msg_rows += (
            f"<tr><td>{_dt(m.get('created_at'))}</td>"
            f"<td><a href=\"/admin/emails/{esc(m['id'])}\">{esc(m.get('subject'))}</a></td>"
            f"<td>{esc(m.get('offer_key'))}</td><td>{badge(m.get('status'))}</td></tr>"
        )
    if not msg_rows:
        msg_rows = '<tr><td colspan="4" class="muted">No emails yet.</td></tr>'

    send_draft = (
        f'<form method="post" action="/admin/prospects/{esc(p["id"])}/send-draft" '
        f'onsubmit="return confirm(\'Send the AI-drafted outreach email to {esc(email)} now?\')">'
        f'<button class="button"{"" if can_send else " disabled"}>Approve &amp; send AI draft now</button></form>'
    )
    reason = "" if can_send else '<p class="help">Available once the prospect is researched, scored, has a verified email, and a selected offer.</p>'

    body = f"""
    {_flash(msg, err)}
    <p><a href="/admin/prospects">← Back to prospects</a></p>
    <h1>{esc(p.get('company_name') or p.get('domain'))}</h1>
    <p class="muted">{esc(p.get('website'))} · {badge(p.get('status'))} · fit {esc(p.get('fit_score') if p.get('fit_score') is not None else '—')}</p>

    <div class="grid2">
      <div class="card kv"><h2>Prospect</h2>
        <p><strong>Domain:</strong> {esc(p.get('domain'))}</p>
        <p><strong>Contact email:</strong> {esc(email or 'None verified')}</p>
        <p><strong>Selected offer:</strong> {esc(p.get('selected_offer_key') or '—')}</p>
        <p><strong>Last contacted:</strong> {_dt(p.get('last_contacted_at'))}</p>
        <p><strong>Observed problems:</strong></p><ul>{problems_html}</ul>
      </div>
      <div class="card"><h2>Send an email</h2>
        <h3>Approve the AI draft</h3>
        {send_draft}{reason}
        <h3 style="margin-top:20px">Custom message</h3>
        <form method="post" action="/admin/prospects/{esc(p['id'])}/send-custom">
          <div class="field"><label>To</label><input name="recipient" value="{esc(email or '')}" placeholder="name@company.com" required></div>
          <div class="field"><label>Subject</label><input name="subject" required></div>
          <div class="field"><label>Message</label><textarea name="body" rows="6" required></textarea></div>
          <button class="button secondary">Send custom email</button>
        </form>
        <p class="help">A compliance footer and one-click unsubscribe are added automatically.</p>
      </div>
    </div>

    <div class="card tableWrap"><h2>Email history</h2>
      <table class="table"><thead><tr><th>When</th><th>Subject</th><th>Offer</th><th>Status</th></tr></thead>
      <tbody>{msg_rows}</tbody></table></div>

    <div class="grid2">
      <div class="card"><h2>Research</h2>{_json_block(research)}</div>
      <div class="card"><h2>Fit assessment</h2>{_json_block(fit)}</div>
    </div>"""
    return layout(p.get("company_name") or "Prospect", "prospects", body)


def emails_page(rows: list[dict[str, Any]], counts: dict[str, int], status: str, msg: str | None = None, err: str | None = None) -> str:
    total = sum(counts.values())
    sent = counts.get("sent", 0) + counts.get("delivered", 0) + counts.get("opened", 0) + counts.get("clicked", 0)
    failed = counts.get("failed", 0)
    options = ["", "drafted", "sent", "delivered", "opened", "clicked", "failed", "bounce", "unsubscribed"]
    opts = "".join(
        f'<option value="{esc(o)}"{" selected" if o == status else ""}>{esc(o or "All statuses")}</option>'
        for o in options
    )
    trs = ""
    for r in rows:
        trs += (
            f"<tr><td>{_dt(r.get('created_at'))}</td>"
            f"<td>{esc(r.get('recipient_email'))}</td>"
            f"<td><a href=\"/admin/emails/{esc(r['id'])}\">{esc(r.get('subject'))}</a>"
            f"<br><span class=\"muted\">{esc(r.get('company_name') or '')}</span></td>"
            f"<td>{esc(r.get('offer_key'))}</td>"
            f"<td>{badge(r.get('status'))}</td></tr>"
        )
    if not trs:
        trs = '<tr><td colspan="5" class="muted">No emails match.</td></tr>'
    body = f"""
    {_flash(msg, err)}
    <p class="eyebrow">Delivery</p><h1>Emails</h1>
    <div class="stats">
      {_stat("Total records", total)}
      {_stat("Sent / delivered", sent)}
      {_stat("Failed", failed)}
      {_stat("Drafts", counts.get("drafted", 0))}
    </div>
    <div class="card">
      <form class="row" method="get" action="/admin/emails">
        <div class="field"><label>Status</label><select name="status">{opts}</select></div>
        <div class="field" style="flex:0"><button class="button">Filter</button></div>
      </form>
    </div>
    <div class="card tableWrap">
      <table class="table"><thead><tr><th>When</th><th>Recipient</th><th>Subject</th><th>Offer</th><th>Status</th></tr></thead>
      <tbody>{trs}</tbody></table>
    </div>"""
    return layout("Emails", "emails", body)


def email_detail_page(m: dict[str, Any]) -> str:
    body = f"""
    <p><a href="/admin/emails">← Back to emails</a></p>
    <h1>{esc(m.get('subject'))}</h1>
    <p class="muted">To {esc(m.get('recipient_email'))} · {badge(m.get('status'))} · sent {_dt(m.get('sent_at'))}</p>
    <div class="card kv">
      <p><strong>Company:</strong> {esc(m.get('company_name') or '—')}</p>
      <p><strong>Offer:</strong> {esc(m.get('offer_key'))}</p>
      <p><strong>Provider message id:</strong> {esc(m.get('provider_message_id') or '—')}</p>
      <p><strong>Prospect:</strong> <a href="/admin/prospects/{esc(m.get('prospect_id'))}">open</a></p>
    </div>
    <div class="card"><h2>Message body</h2><pre>{esc(m.get('text_body'))}</pre></div>"""
    return layout("Email", "emails", body)


def _num_field(label: str, name: str, value: Any, help_text: str = "") -> str:
    h = f'<p class="help">{esc(help_text)}</p>' if help_text else ""
    return f'<div class="field"><label>{esc(label)}</label><input type="number" name="{esc(name)}" value="{esc(value)}">{h}</div>'


def _checkbox(label: str, name: str, checked: bool) -> str:
    c = " checked" if checked else ""
    return (
        f'<div class="field"><label style="cursor:pointer"><input type="checkbox" name="{esc(name)}" value="true"'
        f'{c} style="width:auto;margin-right:8px">{esc(label)}</label></div>'
    )


def criteria_page(criteria: dict[str, Any], total_possible: int, msg: str | None = None, err: str | None = None) -> str:
    w = criteria["weights"]
    weights_html = "".join(
        _num_field(k.replace("_", " ").title(), f"w_{k}", w[k])
        for k in ["problem_evidence", "offer_alignment", "customer_fit", "contact_quality", "timing_signal"]
    )
    body = f"""
    {_flash(msg, err)}
    <p class="eyebrow">Configuration</p><h1>Criteria</h1>
    <p class="muted">These control who gets emailed and how prospects are scored. Changes apply to the next research/send run.</p>
    <form method="post" action="/admin/criteria">
      <div class="card"><h2>Send gate</h2>
        <div class="row">
          {_num_field("Minimum fit score", "min_fit_score", criteria["min_fit_score"], f"Out of {total_possible} possible points.")}
          {_num_field("Min. problem evidence", "min_problem_evidence", criteria["min_problem_evidence"])}
          {_num_field("Min. offer alignment", "min_offer_alignment", criteria["min_offer_alignment"])}
          {_num_field("Min. contact quality", "min_contact_quality", criteria["min_contact_quality"])}
        </div>
      </div>
      <div class="card"><h2>Rubric weights (max points per dimension)</h2>
        <p class="help">Total possible score: <strong>{esc(total_possible)}</strong>. The scorer clamps each dimension to its max here.</p>
        <div class="weightGrid">{weights_html}</div>
      </div>
      <div class="card"><h2>Operational knobs</h2>
        <div class="row">
          {_num_field("Daily send limit", "daily_send_limit", criteria["daily_send_limit"])}
          {_num_field("Contact cooldown (days)", "contact_cooldown_days", criteria["contact_cooldown_days"])}
        </div>
        {_checkbox("Autonomous send (send automatically on the daily job; off = previews only)", "autonomous_send", criteria["autonomous_send"])}
        {_checkbox("Allow named (non role-based) public emails", "allow_named_public_emails", criteria["allow_named_public_emails"])}
        <div class="field"><label>Discovery regions (comma-separated)</label>
          <input name="discovery_regions" value="{esc(criteria["discovery_regions"])}"></div>
      </div>
      <div class="actions">
        <button class="button">Save criteria</button>
        <a class="button secondary" href="/admin/criteria?reset=1" onclick="return confirm('Reset all criteria to the configured defaults?')">Reset to defaults</a>
      </div>
    </form>"""
    return layout("Criteria", "criteria", body)
