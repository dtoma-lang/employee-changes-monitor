# Employee Changes Monitor

Python script that checks Jira Assets HR schema for employee object updates and sends Slack notifications.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
python3 employee_changes_monitor.py
