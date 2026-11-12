from flask import Flask, render_template, request, redirect, url_for, g, flash
import sqlite3
import os
import socket
import ipaddress
import urllib.request
import urllib.parse
from datetime import datetime, date, time, timedelta

import recurring_ical_events
from icalendar import Calendar

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'studyflow-local-dev-key')  # needed for flash messages
DATABASE = 'database.db'

# --- Timetable settings ---
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
START_HOUR = 6      # timetable starts at 06:00
END_HOUR = 23       # ...and ends at 23:00
HOUR_PX = 56        # height of one hour in pixels (keep in sync with --hour-px in style.css)

# --- Reminder / import settings ---
REMINDER_DAYS = 7           # how far ahead the reminder box looks
MAX_REMINDERS = 12
IMPORT_PAST_DAYS = 14       # imported calendars: keep events from 2 weeks ago...
IMPORT_FUTURE_DAYS = 180    # ...to ~6 months ahead
MAX_ICS_BYTES = 5 * 1024 * 1024
MAX_EVENTS = 5000


# --- Database Helper Functions ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row  # Allows accessing columns by name
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''CREATE TABLE IF NOT EXISTS tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        due_date TEXT,
                        priority TEXT,
                        duration INTEGER,
                        completed BOOLEAN DEFAULT 0
                    )''')
        db.execute('''CREATE TABLE IF NOT EXISTS blocks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        day TEXT,
                        start_time TEXT,
                        end_time TEXT
                    )''')
        # NEW: external calendars you've pasted a link for...
        db.execute('''CREATE TABLE IF NOT EXISTS calendars (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        url TEXT NOT NULL UNIQUE,
                        last_synced TEXT
                    )''')
        # ...and the dated events imported from them (ISO strings like 2026-11-13T09:30)
        db.execute('''CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        calendar_id INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        start_dt TEXT NOT NULL,
                        end_dt TEXT NOT NULL,
                        all_day INTEGER DEFAULT 0
                    )''')
        db.commit()


# =====================================================================
#  Calendar import (.ics links)
# =====================================================================
class CalendarImportError(Exception):
    """Raised with a message that is safe to show to the user."""


def _check_public_host(host):
    """Refuse links that point at this machine / your home network."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise CalendarImportError("Couldn't find that website. Check the link.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise CalendarImportError("That link points to a private address, so it can't be imported.")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_public_host(urllib.parse.urlparse(newurl).hostname or '')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def normalize_url(url):
    url = (url or '').strip()
    if url.lower().startswith('webcal://'):          # Apple / Google "webcal" links are just https
        url = 'https://' + url[len('webcal://'):]
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise CalendarImportError("Paste a full calendar link starting with https:// or webcal://")
    return url


def fetch_ics_bytes(url):
    """Download the .ics file. (Kept separate so it's easy to swap/test.)"""
    _check_public_host(urllib.parse.urlparse(url).hostname)
    req = urllib.request.Request(url, headers={'User-Agent': 'StudyFlow/1.0'})
    opener = urllib.request.build_opener(_SafeRedirect)
    try:
        with opener.open(req, timeout=15) as resp:
            data = resp.read(MAX_ICS_BYTES + 1)
    except CalendarImportError:
        raise
    except Exception:
        raise CalendarImportError("Couldn't download that link. Is it public and still valid?")
    if len(data) > MAX_ICS_BYTES:
        raise CalendarImportError("That calendar file is too large (max 5 MB).")
    return data


def _to_local_naive(dt):
    """Timezone-aware -> your computer's local time, no tzinfo. Floating times are left alone."""
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


def parse_ics(data):
    """bytes -> (calendar_name, [(title, start_iso, end_iso, all_day), ...])"""
    if b'BEGIN:VCALENDAR' not in data[:4096].upper():
        raise CalendarImportError("That link didn't return a calendar (.ics) file.")
    try:
        cal = Calendar.from_ical(data)
        name = str(cal.get('X-WR-CALNAME') or '').strip()
        today = date.today()
        components = recurring_ical_events.of(cal).between(
            today - timedelta(days=IMPORT_PAST_DAYS),
            today + timedelta(days=IMPORT_FUTURE_DAYS))
    except Exception:
        raise CalendarImportError("Couldn't read the events in that calendar file.")

    events = []
    for ev in components:
        if str(ev.get('STATUS', '')).upper() == 'CANCELLED' or not ev.get('DTSTART'):
            continue
        s = ev.get('DTSTART').dt
        e = ev.get('DTEND').dt if ev.get('DTEND') else None
        if e is None and ev.get('DURATION'):
            e = s + ev.get('DURATION').dt
        title = str(ev.get('SUMMARY') or '(no title)').strip()

        if isinstance(s, datetime):
            s = _to_local_naive(s)
            e = _to_local_naive(e) if isinstance(e, datetime) else s + timedelta(hours=1)
            if e <= s:
                e = s + timedelta(minutes=30)
            all_day = 0
        else:  # all-day event: DTSTART/DTEND are plain dates, DTEND is exclusive
            s = datetime.combine(s, time.min)
            if isinstance(e, datetime):
                e = e.date()
            e = datetime.combine(e, time.min) if isinstance(e, date) else s + timedelta(days=1)
            if e <= s:
                e = s + timedelta(days=1)
            all_day = 1

        events.append((title, s.isoformat(timespec='minutes'), e.isoformat(timespec='minutes'), all_day))
        if len(events) >= MAX_EVENTS:
            break
    return name, events


def save_calendar(db, url, name_override=None, calendar_id=None):
    """Download + parse + (re)write one calendar's events. Returns (calendar_id, count)."""
    url = normalize_url(url)
    cal_name, events = parse_ics(fetch_ics_bytes(url))
    name = (name_override or cal_name or urllib.parse.urlparse(url).hostname or 'Calendar').strip()[:80]
    now = datetime.now().isoformat(timespec='minutes')

    if calendar_id is None:
        row = db.execute('SELECT id FROM calendars WHERE url = ?', (url,)).fetchone()
        calendar_id = row['id'] if row else None
    if calendar_id is None:
        calendar_id = db.execute('INSERT INTO calendars (name, url, last_synced) VALUES (?, ?, ?)',
                                 (name, url, now)).lastrowid
    else:
        db.execute('UPDATE calendars SET name = COALESCE(?, name), last_synced = ? WHERE id = ?',
                   (name_override or None, now, calendar_id))
        db.execute('DELETE FROM events WHERE calendar_id = ?', (calendar_id,))

    db.executemany('INSERT INTO events (calendar_id, title, start_dt, end_dt, all_day) VALUES (?, ?, ?, ?, ?)',
                   [(calendar_id, *ev) for ev in events])
    db.commit()
    return calendar_id, len(events)


# =====================================================================
#  Timetable layout
# =====================================================================
def to_minutes(t):
    """'09:30' -> 570"""
    h, m = t.split(':')[:2]
    return int(h) * 60 + int(m)


def hhmm(minutes):
    return f'{minutes // 60:02d}:{minutes % 60:02d}'


def hue_for(text):
    return sum(ord(c) for c in text) % 360   # stable colour per title / calendar


def layout_day(items):
    """
    items: [{'s': start_min, 'e': end_min, ...}] -> same items with top/height/left/width added.
    Overlapping items are placed side by side.
    """
    grid_start, grid_end = START_HOUR * 60, END_HOUR * 60
    out = []
    for it in items:
        s, e = max(it['s'], grid_start), min(it['e'], grid_end)   # clip to visible range
        if e <= s:
            continue
        it = dict(it, s=s, e=e,
                  top=(s - grid_start) / 60 * HOUR_PX,
                  height=max((e - s) / 60 * HOUR_PX, 22))
        out.append(it)
    out.sort(key=lambda x: (x['s'], x['e']))

    clusters, cluster, cluster_end = [], [], 0
    for it in out:
        if cluster and it['s'] >= cluster_end:
            clusters.append(cluster)
            cluster, cluster_end = [], 0
        cluster.append(it)
        cluster_end = max(cluster_end, it['e'])
    if cluster:
        clusters.append(cluster)

    for cl in clusters:
        lane_ends = []
        for it in cl:
            for i, end in enumerate(lane_ends):
                if it['s'] >= end:
                    it['lane'] = i
                    lane_ends[i] = it['e']
                    break
            else:
                it['lane'] = len(lane_ends)
                lane_ends.append(it['e'])
        for it in cl:
            it['left'] = it['lane'] / len(lane_ends) * 100
            it['width'] = 100 / len(lane_ends)
    return out


def timetable_context(dates, blocks, events):
    """
    dates: list of date objects to show as columns (7 for the week, 1 for today).
    blocks: weekly recurring blocks (match by weekday name).
    events: imported dated events (match by actual date).
    """
    days = [d.strftime('%A') for d in dates]
    items = {name: [] for name in days}
    allday = {name: [] for name in days}

    for name, d in zip(days, dates):
        for b in blocks:
            if b['day'] == name:
                s, e = to_minutes(b['start_time']), to_minutes(b['end_time'])
                items[name].append({'kind': 'block', 'id': b['id'], 'title': b['title'],
                                    'start': b['start_time'], 'end': b['end_time'],
                                    's': s, 'e': e, 'hue': hue_for(b['title'])})

        day_start = datetime.combine(d, time.min)
        day_end = day_start + timedelta(days=1)
        for ev in events:
            s, e = datetime.fromisoformat(ev['start_dt']), datetime.fromisoformat(ev['end_dt'])
            if e <= day_start or s >= day_end:
                continue
            hue = hue_for(ev['cal_name'])
            if ev['all_day']:
                allday[name].append({'title': ev['title'], 'hue': hue, 'cal': ev['cal_name']})
                continue
            s_min = int((max(s, day_start) - day_start).total_seconds() // 60)
            e_min = int((min(e, day_end) - day_start).total_seconds() // 60)
            items[name].append({'kind': 'event', 'id': ev['id'], 'title': ev['title'],
                                'start': hhmm(s_min), 'end': hhmm(e_min),
                                's': s_min, 'e': e_min, 'hue': hue, 'cal': ev['cal_name']})

    return {
        'days': days,
        'day_dates': dict(zip(days, dates)),
        'today_date': date.today(),
        'timetable': {name: layout_day(items[name]) for name in days},
        'allday': allday,
        'allday_any': any(allday.values()),
        'hours': list(range(START_HOUR, END_HOUR)),
        'hour_px': HOUR_PX,
        'grid_height': (END_HOUR - START_HOUR) * HOUR_PX,
        'start_hour': START_HOUR,
        'end_hour': END_HOUR,
        'today_name': datetime.now().strftime('%A'),
        'has_items': bool(blocks) or bool(events),
    }


def events_between(db, start_day, end_day):
    """Imported events overlapping [start_day, end_day) (dates)."""
    return db.execute(
        '''SELECT events.*, calendars.name AS cal_name FROM events
           JOIN calendars ON calendars.id = events.calendar_id
           WHERE events.end_dt > ? AND events.start_dt < ?
           ORDER BY events.start_dt''',
        (start_day.isoformat() + 'T00:00', end_day.isoformat() + 'T00:00')).fetchall()


# Sort High -> Medium -> Low (plain "ORDER BY priority DESC" sorts alphabetically, which is wrong)
PRIORITY_ORDER = "CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 WHEN 'Low' THEN 2 ELSE 3 END"


# =====================================================================
#  Reminders
# =====================================================================
def _nice_delta(delta):
    mins = max(int(delta.total_seconds() // 60), 0)
    if mins < 60:
        return f'{mins} min'
    h, m = divmod(mins, 60)
    return f'{h}h {m:02d}m' if m else f'{h}h'


def _day_label(d, today):
    diff = (d - today).days
    if diff == 0:
        return 'Today'
    if diff == 1:
        return 'Tomorrow'
    return d.strftime('%a %d %b')


def _level(delta):
    if delta <= timedelta(hours=24):
        return 'urgent'
    if delta <= timedelta(hours=72):
        return 'soon'
    return 'later'


def get_reminders(db):
    """Everything coming up in the next REMINDER_DAYS: task deadlines, imported events, today's classes."""
    now = datetime.now()
    today = now.date()
    items = []

    # 1) Task deadlines (incl. overdue)
    rows = db.execute("SELECT * FROM tasks WHERE completed = 0 AND due_date IS NOT NULL AND due_date != ''").fetchall()
    for t in rows:
        try:
            due = date.fromisoformat(t['due_date'])
        except ValueError:
            continue
        diff = (due - today).days
        if diff > REMINDER_DAYS:
            continue
        if diff < 0:
            when, level = f'Overdue by {-diff} day{"s" if diff < -1 else ""}', 'urgent'
        elif diff == 0:
            when, level = 'Due today', 'urgent'
        elif diff == 1:
            when, level = 'Due tomorrow', 'soon'
        else:
            when, level = f'Due {due.strftime("%a %d %b")}', 'soon' if diff <= 2 else 'later'
        items.append({'kind': 'task', 'icon': '📝', 'title': t['title'], 'when': when,
                      'level': level, 'task_id': t['id'],
                      'sort': datetime.combine(due, time(23, 59))})

    # 2) Imported calendar events (timed + all-day)
    horizon = now + timedelta(days=REMINDER_DAYS)
    ev_rows = db.execute(
        '''SELECT events.*, calendars.name AS cal_name FROM events
           JOIN calendars ON calendars.id = events.calendar_id
           WHERE events.end_dt > ? AND events.start_dt < ? ORDER BY events.start_dt''',
        (now.isoformat(timespec='minutes'), horizon.isoformat(timespec='minutes'))).fetchall()
    for ev in ev_rows:
        s, e = datetime.fromisoformat(ev['start_dt']), datetime.fromisoformat(ev['end_dt'])
        if ev['all_day']:
            first = max(s.date(), today)
            when = f'All day · {_day_label(first, today)}'
            level = 'urgent' if first == today else _level(datetime.combine(first, time.min) - now)
            sort = datetime.combine(first, time.min)
        elif s <= now:
            when, level, sort = f'Happening now · until {e:%H:%M}', 'urgent', s
        else:
            delta = s - now
            if s.date() == today:
                when = f'Today {s:%H:%M} · in {_nice_delta(delta)}'
            else:
                when = f'{_day_label(s.date(), today)} {s:%H:%M}'
            level, sort = _level(delta), s
        items.append({'kind': 'event', 'icon': '📅', 'title': ev['title'], 'when': when,
                      'level': level, 'sub': ev['cal_name'], 'sort': sort})

    # 3) Rest of today's weekly timetable blocks
    for b in db.execute('SELECT * FROM blocks WHERE day = ?', (now.strftime('%A'),)).fetchall():
        s = datetime.combine(today, time(*divmod(to_minutes(b['start_time']), 60)))
        e = datetime.combine(today, time(*divmod(to_minutes(b['end_time']), 60))) if to_minutes(b['end_time']) < 1440 else s
        if s <= now < e:
            items.append({'kind': 'block', 'icon': '📚', 'title': b['title'],
                          'when': f'Happening now · until {b["end_time"]}', 'level': 'urgent', 'sort': s})
        elif s > now:
            delta = s - now
            items.append({'kind': 'block', 'icon': '📚', 'title': b['title'],
                          'when': f'Today {b["start_time"]} · in {_nice_delta(delta)}',
                          'level': 'urgent' if delta <= timedelta(hours=2) else 'soon', 'sort': s})

    items.sort(key=lambda x: x['sort'])
    return items[:MAX_REMINDERS]


@app.context_processor
def inject_reminders():
    """Makes `reminders` available in every template so the box can sit on every page."""
    return {'reminders': get_reminders(get_db())}


# =====================================================================
#  Routes
# =====================================================================
@app.route('/')
def index():
    db = get_db()
    offset = max(-52, min(52, request.args.get('week', 0, type=int)))
    monday = date.today() - timedelta(days=date.today().weekday()) + timedelta(weeks=offset)
    dates = [monday + timedelta(days=i) for i in range(7)]

    blocks = db.execute('SELECT * FROM blocks ORDER BY start_time').fetchall()
    events = events_between(db, dates[0], dates[-1] + timedelta(days=1))
    tasks = db.execute(f'SELECT * FROM tasks WHERE completed = 0 ORDER BY {PRIORITY_ORDER}').fetchall()
    calendars = db.execute('SELECT * FROM calendars ORDER BY name').fetchall()

    ctx = timetable_context(dates, blocks, events)
    week_label = f'{dates[0]:%d %b} – {dates[-1]:%d %b %Y}'
    return render_template('index.html', blocks=blocks, tasks=tasks, calendars=calendars,
                           offset=offset, week_label=week_label, **ctx)


@app.route('/today')
def today():
    db = get_db()
    d = date.today()
    today_name = d.strftime('%A')
    today_blocks = db.execute('SELECT * FROM blocks WHERE day = ? ORDER BY start_time', (today_name,)).fetchall()
    events = events_between(db, d, d + timedelta(days=1))
    tasks = db.execute(f'SELECT * FROM tasks ORDER BY completed, {PRIORITY_ORDER}').fetchall()

    total_tasks = len(tasks)
    completed_tasks = sum(1 for t in tasks if t['completed'])
    progress = int(completed_tasks / total_tasks * 100) if total_tasks > 0 else 0

    ctx = timetable_context([d], today_blocks, events)
    return render_template('today.html', tasks=tasks, progress=progress, **ctx)


@app.route('/reminders')
def reminders_partial():
    """Just the reminder list; the page refreshes it every minute via fetch()."""
    return render_template('_reminder_items.html')


# --- Calendar import actions ---
@app.route('/import_calendar', methods=['POST'])
def import_calendar():
    url = request.form.get('url', '')
    name = (request.form.get('name') or '').strip() or None
    try:
        _, count = save_calendar(get_db(), url, name_override=name)
        flash(f'Imported {count} event{"s" if count != 1 else ""}.', 'success')
    except CalendarImportError as e:
        flash(str(e), 'error')
    return redirect(url_for('index'))


@app.route('/sync_calendar/<int:cal_id>', methods=['POST'])
def sync_calendar(cal_id):
    db = get_db()
    cal = db.execute('SELECT * FROM calendars WHERE id = ?', (cal_id,)).fetchone()
    if cal:
        try:
            _, count = save_calendar(db, cal['url'], calendar_id=cal_id)
            flash(f'Refreshed "{cal["name"]}": {count} event{"s" if count != 1 else ""}.', 'success')
        except CalendarImportError as e:
            flash(f'Could not refresh "{cal["name"]}": {e}', 'error')
    return redirect(url_for('index'))


@app.route('/remove_calendar/<int:cal_id>', methods=['POST'])
def remove_calendar(cal_id):
    db = get_db()
    db.execute('DELETE FROM events WHERE calendar_id = ?', (cal_id,))
    db.execute('DELETE FROM calendars WHERE id = ?', (cal_id,))
    db.commit()
    return redirect(url_for('index'))


# --- Actions (Quick Add & Updates) ---
@app.route('/add_task', methods=['POST'])
def add_task():
    title = (request.form.get('title') or '').strip()
    priority = request.form.get('priority', 'Medium')
    duration = request.form.get('duration', 30)
    due_date = request.form.get('due_date')

    if title:
        db = get_db()
        db.execute('INSERT INTO tasks (title, priority, duration, due_date) VALUES (?, ?, ?, ?)',
                   (title, priority, duration, due_date))
        db.commit()
    return redirect(request.referrer or url_for('index'))


@app.route('/add_block', methods=['POST'])
def add_block():
    title = (request.form.get('title') or '').strip()
    day = request.form.get('day')
    start_time = request.form.get('start_time')
    end_time = request.form.get('end_time')

    valid = title and day in DAYS and start_time and end_time and to_minutes(end_time) > to_minutes(start_time)
    if valid:
        db = get_db()
        db.execute('INSERT INTO blocks (title, day, start_time, end_time) VALUES (?, ?, ?, ?)',
                   (title, day, start_time, end_time))
        db.commit()
    return redirect(request.referrer or url_for('index'))


@app.route('/delete_block/<int:block_id>', methods=['POST'])
def delete_block(block_id):
    db = get_db()
    db.execute('DELETE FROM blocks WHERE id = ?', (block_id,))
    db.commit()
    return redirect(request.referrer or url_for('index'))


@app.route('/toggle_task/<int:task_id>')
def toggle_task(task_id):
    db = get_db()
    task = db.execute('SELECT completed FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if task:
        new_status = 0 if task['completed'] else 1
        db.execute('UPDATE tasks SET completed = ? WHERE id = ?', (new_status, task_id))
        db.commit()
    return redirect(request.referrer or url_for('index'))


@app.route('/delete_task/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    db = get_db()
    db.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    db.commit()
    return redirect(request.referrer or url_for('index'))


init_db()  # make sure tables exist even if you start with `flask run`

if __name__ == '__main__':
    app.run(debug=True)
