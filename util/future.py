"""
A simple threaded task wrapper.
"""

import threading


class Future:
    """
    Simple thread wrapper that provides the "result" like concurrent.futures.

    concurrent.futures does not kill the threads with atexit, making processes hang.
    """

    def __init__(self, target, args=(), kwargs=None):
        """
        Submit the task
        """
        self._target = target
        self._done = False
        self._result = None
        self._thread = threading.Thread(target=self._run, args=args, kwargs=kwargs, daemon=True)
        self._thread.start()

    def _run(self, *args, **kwargs):
        self._result = self._target(*args, **kwargs)
        self._done = True

    def done(self):
        return self._done

    def result(self, timeout=None):
        if not self.done():
            self._thread.join(timeout=None)
        if self._thread.isAlive():
            raise TimeoutError
        return self._result

    def join(self, timeout=None):
        self._thread.join(timeout=timeout)
