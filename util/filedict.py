import json

__all__ = ['FileDict']


class FileDict(dict):
    """
    A dictionary that dumps its state on file.
    """
    def __init__(self, filename, *args, **kwargs):
        self.filename = filename
        dict.__init__(self, *args, **kwargs)
        try:
            self._load()
        except IOError:
            self._save()

    def __getitem__(self, y):
        self._load()
        return dict.__getitem__(self, y)

    def __setitem__(self, i, y):
        dict.__setitem__(self, i, y)
        self._save()
        return None

    def __delitem__(self, key):
        dict.__delitem__(self, key)
        self._save()
        return None

    def pop(self, k, *args):
        r = dict.pop(self, k, *args)
        self._save()
        return r

    def popitem(self):
        r = dict.popitem(self)
        self._save()
        return r

    def clear(self):
        dict.clear(self)
        self._save()

    def get(self, k, *args):
        self._load()
        return dict.get(self, k, *args)

    def _load(self):
        with open(self.filename, 'r') as f:
            self.update(json.load(f))

    def _save(self):
        with open(self.filename, 'w') as f:
            json.dump(dict(self), f)

    def __delitem__(self, key):
        dict.__delitem__(self, key)
        self._save()
        return None
