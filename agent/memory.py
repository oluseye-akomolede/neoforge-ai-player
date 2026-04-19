import json
import os

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "bot_memory.json")


def load():
    return load_from(MEMORY_FILE)


def load_from(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def save(entries):
    save_to(entries, MEMORY_FILE)


def save_to(entries, path):
    with open(path, "w") as f:
        json.dump(entries, f, indent=2)


def add(entries, note, max_entries=50):
    return add_to(entries, note, MEMORY_FILE, max_entries)


def add_to(entries, note, path, max_entries=50):
    note = note.strip()
    if not note:
        return entries
    if note in entries:
        return entries
    entries.append(note)
    if len(entries) > max_entries:
        entries = entries[-max_entries:]
    save_to(entries, path)
    return entries
