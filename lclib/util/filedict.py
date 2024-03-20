"""
A Dictionary that keeps its state saved on file.

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import json
import os
import threading

__all__ = ['FileDict']


class FileDict(dict):
    """
    A dictionary that dumps its state on file.
    """
    def __init__(self, filename, *args, **kwargs):
        self.filename = filename
        self.access_lock = threading.Lock()

        if not os.path.exists(filename):
            os.makedirs(os.path.split(filename)[0], exist_ok=True)
        dict.__init__(self, *args, **kwargs)

        try:
            self._load()
        except IOError:
            self._save()

    def __getitem__(self, y):
        #self._load()
        return dict.__getitem__(self, y)

    def __setitem__(self, i, y):
        self._load()
        dict.__setitem__(self, i, y)
        self._save()
        return None

    def __delitem__(self, key):
        self._load()
        dict.__delitem__(self, key)
        self._save()
        return None

    def pop(self, k, *args):
        self._load()
        r = dict.pop(self, k, *args)
        self._save()
        return r

    def popitem(self):
        self._load()
        r = dict.popitem(self)
        self._save()
        return r

    def clear(self):
        dict.clear(self)
        self._save()

    def get(self, k, *args):
        #self._load()
        return dict.get(self, k, *args)

    def _load(self):
        with self.access_lock:
            with open(self.filename, 'r') as f:
                self.update(json.load(f))

    def _save(self):
        with self.access_lock:
            with open(self.filename, 'w') as f:
                json.dump(dict(self), f)