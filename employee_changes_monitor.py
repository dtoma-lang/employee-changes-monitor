import requests
import json
import os
from datetime import datetime
from dotenv import load_dotenv

# Load config
load_dotenv()

JIRA_URL = os.getenv("JIRA_URL")
TOKEN = os.getenv("JIRA_TOKEN")
SCHEMA_ID = int(os.getenv("SCHEMA_ID", 3))
OBJECT_TYPE_ID = int(os.getenv("OBJECT_TYPE_ID", 405))
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")

HEADERS = {"Authorization": f"Bearer {TOKEN}"}
EMPLOYEES_FILE = "employees.json"
LOG_FILE = "history.log"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def send_to_slack(text):
    if not SLACK_WEBHOOK:
        return
    try:
        requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=10)
    except Exception as e:
        log(f"Slack error: {e}")


def fetch_employees():
    """Fetch all employees with id, label, updated"""
    employees, page = [], 1
    while True:
        url = (
            f"{JIRA_URL}/rest/insight/1.0/iql/objects?"
            f"objectSchemaId={SCHEMA_ID}&iql=objectTypeId={OBJECT_TYPE_ID}"
            f"&resultPerPage=1000&page={page}"
        )
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            log(f"Fetch error: {resp.status_code}")
            break
        data = resp.json().get("objectEntries", [])
        if not data:
            break
        for e in data:
            employees.append({
                "id": e["id"],
                "label": e["label"],
                "updated": e.get("updated")
            })
        if len(data) < 1000:
            break
        page += 1
    return {str(e["id"]): e for e in employees}


def load_employees():
    if not os.path.exists(EMPLOYEES_FILE):
        log("Initial run — creating employee baseline...")
        data = fetch_employees()
        save_employees(data)
        return data
    with open(EMPLOYEES_FILE, encoding="utf-8") as f:
        return {str(e["id"]): e for e in json.load(f)}


def save_employees(data):
    with open(EMPLOYEES_FILE, "w", encoding="utf-8") as f:
        json.dump(list(data.values()), f, ensure_ascii=False, indent=2)


def main():
    log("🚀 Change check started")
    old_data = load_employees()
    new_data = fetch_employees()
    session = requests.Session()

    # created / updated
    for emp_id, emp in new_data.items():
        label = emp["label"]
        emp_url = f"{JIRA_URL}/secure/ShowObject.jspa?id={emp_id}"
        updated = emp.get("updated")
        old_updated = old_data.get(emp_id, {}).get("updated")

        # created
        if emp_id not in old_data:
            msg = f"[CREATED] *<{emp_url}|{label}>* (HR-{emp_id})"
            log(msg)
            send_to_slack(msg)
            old_data[emp_id] = emp
            continue

        # updated
        if updated != old_updated:
            try:
                resp = session.get(
                    f"{JIRA_URL}/rest/insight/1.0/object/{emp_id}/history",
                    headers=HEADERS, timeout=15
                )
                resp.raise_for_status()
                history = resp.json()
            except Exception as e:
                log(f"History error for {label}: {e}")
                continue

            if not history:
                continue

            last_time = old_updated or "0"
            changes = []
            for h in history:
                if h["created"] > last_time:
                    attr = h.get("affectedAttribute", "—")
                    old_val = h.get("oldValue") or "None"
                    new_val = h.get("newValue") or "None"
                    changes.append(f"{attr}: {old_val} → {new_val}")

            if changes:
                actor = history[-1].get("actor", {}).get("displayName", "Unknown")
                created = history[-1].get("created", "Unknown")
                formatted = "\n".join([f"• `{c}`" for c in changes])
                msg = (
                    f"[UPDATED] *<{emp_url}|{label}>* (HR-{emp_id})\n"
                    f"*Changed by:* {actor}\n"
                    f"*Date:* `{created}`\n"
                    f"*Changes:*\n{formatted}"
                )
                log(msg)
                send_to_slack(msg)
            old_data[emp_id]["updated"] = updated

    # deleted
    for emp_id in list(old_data.keys()):
        if emp_id not in new_data:
            label = old_data[emp_id].get("label", f"object_{emp_id}")
            msg = f"[DELETED] {label} (HR-{emp_id})"
            log(msg)
            send_to_slack(msg)
            old_data.pop(emp_id)

    save_employees(old_data)
    log("Check finished\n")


if __name__ == "__main__":
    main()
