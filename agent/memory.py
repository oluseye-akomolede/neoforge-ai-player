import json
import os

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "bot_memory.json")


def load():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE) as f:
            return json.load(f)
    return []


def save(entries):
    with open(MEMORY_FILE, "w") as f:
        json.dump(entries, f, indent=2)


def add(entries, note, max_entries=50):
    note = note.strip()
    if not note:
        return entries
    if note in entries:
        return entries
    entries.append(note)
    if len(entries) > max_entries:
        entries = entries[-max_entries:]
    save(entries)
    return entries
