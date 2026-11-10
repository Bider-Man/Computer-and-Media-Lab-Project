from flask import Flask, render_template, request, redirect, url_for, g
import sqlite3
from datetime import datetime

app = Flask(__name__)
DATABASE = 'database.db'

# --- Database Helper Functions ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row # Allows accessing columns by name
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
        db.commit()

# --- Routes ---
@app.route('/')
def index():
    db = get_db()
    # Get all time blocks for the week
    blocks = db.execute('SELECT * FROM blocks ORDER BY start_time').fetchall()
    # Get all incomplete tasks
    tasks = db.execute('SELECT * FROM tasks WHERE completed = 0').fetchall()
    return render_template('index.html', blocks=blocks, tasks=tasks)

@app.route('/today')
def today():
    db = get_db()
    # Get today's day name (e.g., "Monday")
    today_name = datetime.now().strftime('%A')
    # Get blocks for today
    today_blocks = db.execute('SELECT * FROM blocks WHERE day = ? ORDER BY start_time', (today_name,)).fetchall()
    # Get all tasks
    tasks = db.execute('SELECT * FROM tasks ORDER BY completed, priority DESC').fetchall()
    
    # Calculate progress
    total_tasks = len(tasks)
    completed_tasks = sum(1 for t in tasks if t['completed'])
    progress = int((completed_tasks / total_tasks * 100)) if total_tasks > 0 else 0

    return render_template('today.html', blocks=today_blocks, tasks=tasks, progress=progress, today_name=today_name)

# --- Actions (Quick Add & Updates) ---
@app.route('/add_task', methods=['POST'])
def add_task():
    title = request.form.get('title')
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
    title = request.form.get('title')
    day = request.form.get('day')
    start_time = request.form.get('start_time')
    end_time = request.form.get('end_time')
    
    if title and day and start_time and end_time:
        db = get_db()
        db.execute('INSERT INTO blocks (title, day, start_time, end_time) VALUES (?, ?, ?, ?)',
                   (title, day, start_time, end_time))
        db.commit()
    return redirect(url_for('index'))

@app.route('/toggle_task/<int:task_id>')
def toggle_task(task_id):
    db = get_db()
    task = db.execute('SELECT completed FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if task:
        new_status = 0 if task['completed'] else 1
        db.execute('UPDATE tasks SET completed = ? WHERE id = ?', (new_status, task_id))
        db.commit()
    return redirect(request.referrer or url_for('index'))

if __name__ == '__main__':
    init_db() # Create tables if they don't exist
    app.run(debug=True)
