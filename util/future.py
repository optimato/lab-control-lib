"""
A simple threaded task wrapper.
"""

import threading


class Future:
    """
    Simple thread wrapper that provides the "result" like concurrent.futures.

    concurrent.futures does not kill the threads with atexit, making processes hang.
    """

    def __init__(self, target, args=(), kwargs=None, callback=None):
        """
        Run function "target" with provided arg and kwargs
        callback can be a function of the form f(result, error), which manages
        either the result at task completion or an error (in which case the error is not raised)
        """
        self._target = target
        self._done = False
        self._result = None
        self._error = None
        self._callback = callback
        kwargs = kwargs or {}
        self._thread = threading.Thread(
            target=self._run, args=args, kwargs=kwargs, daemon=True
        )
        self._thread.start()

    def _run(self, *args, **kwargs):
        try:
            self._result = self._target(*args, **kwargs)
        except BaseException as error:
            # Catch any error
            self._error = error
        if self._callback is not None:
            # Callback with result and/or error
            self._callback(self._result, self._error)
            self._done = True
        elif self._error is not None:
            raise self._error
        self._done = True

    def in_error(self):
        return self._error is not None

    def done(self):
        return self._done

    def result(self, timeout=None):
        if not self.done():
            self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            raise TimeoutError
        return self._result

    def join(self, timeout=None):
        self._thread.join(timeout=timeout)
