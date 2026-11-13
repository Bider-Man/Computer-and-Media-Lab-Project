# Computer-and-Media-Lab-Project

A repo for Computer and Media Lab Project, so that the codebase stays in one place that is easily accessible.

This is the repository for our project, **StudyFlow**. It is a web-based planner designed for university students. The goal is to provide a simple, fast way to organize weekly timetables and daily tasks without the clutter of larger productivity apps. The app is built using Python (Flask) for the backend and standard HTML/CSS for the frontend, with all data saved locally in an SQLite database.

## Core Features
- Weekly and Daily timetable views
- Task manager with priorities and estimated durations
- Aesthetic themes (switching between CSS styles)
- Local-first data storage

## Tech Stack
- Backend: Python, Flask
- Database: SQLite
- Frontend: HTML, CSS, JavaScript

## How to Run the App

If you are running this project for the first time, follow these steps to set up the environment and start the server.

1. Clone the repository:
```bash
git clone https://github.com/your-username/Computer-and-Media-Lab-Project.git
cd Computer-and-Media-Lab-Project
```

2. Create a virtual environment (if you are on Linux):
```bash
python -m venv venv
source venn/bin/activate
```
3. Install the required packages:
```bash
pip install -r requirements.txt
```
4. Run Python:
```bash
python app.py
```

5. Open your browser (or click the link within your terminal) to open the web page for the schedule.

## Project Structure
```
Computer-and-Media-Lab-Project/
├── app.py               # Main Flask application and database logic
├── requirements.txt     # Python dependencies
├── database.db          # Local SQLite database (ignored by Git)
├── static/              # CSS, JavaScript, and media assets
│   ├── style.css        
│   └── script.js        
└── templates/           # HTML files
    ├── index.html       # Weekly planner view
    └── today.html       # Daily task view
```

## Team
Karthik Polpakkara Mana (Project Manager/Backend)
Chirag Nagesh (Frontend)
Anish Sharma (Quality Control/Presentation)
