"""
Waypoint system — named locations per server.

Stores waypoints in a JSON file keyed by server address so test/prod
waypoints never mix. Bots can set, delete, list, and goto waypoints.
"""

import json
import os
import threading
from config import MOD_API_URL

_lock = threading.Lock()
_waypoints = {}  # server_key -> {name -> {x, y, z, dimension, set_by}}
_filepath = os.path.join(os.path.dirname(__file__), "waypoints.json")


def _server_key():
    return MOD_API_URL.replace("http://", "").replace("https://", "").replace("/", "_")


def load():
    global _waypoints
    with _lock:
        if os.path.exists(_filepath):
            try:
                with open(_filepath) as f:
                    _waypoints = json.load(f)
            except Exception:
                _waypoints = {}
        else:
            _waypoints = {}


def _save():
    with open(_filepath, "w") as f:
        json.dump(_waypoints, f, indent=2)


def set_waypoint(name, x, y, z, dimension=None, set_by=None):
    key = _server_key()
    with _lock:
        if key not in _waypoints:
            _waypoints[key] = {}
        _waypoints[key][name.lower()] = {
            "name": name,
            "x": x, "y": y, "z": z,
            "dimension": dimension,
            "set_by": set_by,
        }
        _save()
    return True


def delete_waypoint(name):
    key = _server_key()
    with _lock:
        if key in _waypoints and name.lower() in _waypoints[key]:
            del _waypoints[key][name.lower()]
            _save()
            return True
    return False


def get_waypoint(name):
    key = _server_key()
    with _lock:
        return _waypoints.get(key, {}).get(name.lower())


def list_waypoints():
    key = _server_key()
    with _lock:
        wps = _waypoints.get(key, {})
        return [
            {"name": v["name"], "x": v["x"], "y": v["y"], "z": v["z"],
             "dimension": v.get("dimension"), "set_by": v.get("set_by")}
            for v in wps.values()
        ]
