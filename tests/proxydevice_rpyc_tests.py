"""
Testing the rpyc implementation of proxydevice.
"""

from lclib.util import proxycall, ProxyDeviceError, proxydevice

import time


@proxydevice(address=("127.0.0.1", 5055))
class A:
    def __init__(self, x=1):
        self.x = x
        self.a = "abc"
        self.stop = False
        print('Class A is initialized.')

    # A non-exposed call
    def do_something(self, y):
        self.x += y

    # An exposed call
    @proxycall()
    def get_multiple(self, y):
        print('Called get_multiple')
        return self.x * y

    # An exposed call that produces an error
    @proxycall()
    def wrong_call(self):
        print('Called wrong_call')
        raise RuntimeError('oops')

    # An exposed input
    @proxycall()
    def interact(self):
        print('Called interact')
        self.z = input('What is z?')

    # An exposed call allowed only for the client with admin rights
    @proxycall(admin=True)
    def set_a(self, a):
        print('Called set_a')
        self.a = a

    # A long task. Must be made non-blocking otherwise the sever will wait for return value
    @proxycall(admin=True, block=False)
    def long_task(self):
        print('Called long_task')
        for i in range(10):
            print(chr(i + 65))
            time.sleep(1)
            if self.stop:
                self.stop = False
                break
        return 1

    # An long task that produces an error
    @proxycall(block=False)
    def long_task_err(self):
        print('Called long_task_err')
        time.sleep(1)
        raise RuntimeError('oops')

    # Declaring the abort call, to be sent when ctrl-C is hit during a long call.
    @proxycall(interrupt=True)
    def abort(self):
        print("Aborting the long call!")
        self.stop = True

    # An exposed property
    @proxycall()
    @property
    def x_value(self):
        return self.x

    @x_value.setter
    def x_value(self, v):
        self.x = v


if __name__ == "__main__":
    """
    Calling from the command line with the option 'server' starts the server and instantiate
    the test class A.
    
    Calling from the command line with the option 'client' (after the server is started on 
    another process) runs a series of tests.
    
    Otherwise, it is possible to "%run ... interactive" from ipython and play with the client.
    """
    import sys
    print(sys.argv)
    if sys.argv[1] == 'server':
        s = A.Server()
        s.wait()
        sys.exit(0)
    elif sys.argv[1] == 'interactive':
        c = A.Client()
    elif sys.argv[1] == 'client':
        c = A.Client()
        # Check that client is admin by default
        assert c.ask_admin()
        print('ask_admin pass')

        # Set value as admin
        c.set_a(1)
        print('set as admin pass')

        # Rescind admin and try again
        c.ask_admin(False)
        try:
            c.set_a(1)
        except ProxyDeviceError:
            print('trying to set not as admin pass')

        # Ask admin again
        c.ask_admin(True)

        # Call a simple exposed method
        c.get_multiple(6)
        print('exposed method pass')

        # Call a the simple exposed method with an incompatible argument
        try:
            c.get_multiple({})
        except TypeError:
            print('caught TypeError pass')

        # Call long task that errors
        try:
            c.long_task_err()
        except RuntimeError:
            print('caught long task error - pass')

        # Call long task
        c.long_task()
        print('long task pass')

        # Call long task not in clean mode
        c.clean = False
        c.long_task()
        print('long task started in background')
        while True:
            if c.awaited_result is not None:
                break
            print('waiting...')
            time.sleep(.5)
        print('long task completed')
        c.clean = True

        # Set and get properties
        c.x_value = 'abc'
        assert c.x_value == 'abc'
        print('get set properties pass')
