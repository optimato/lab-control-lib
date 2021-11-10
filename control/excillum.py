"""
This code was written by Leo to change the state of the Liquid Metal Jet Source
It was modified by Ronan to make it thread safe and for the implememntation.
It was modified to replace code used to add metadata from the source to images.
Always use send_and_receive to even when the response is not required, as it is thread
safe and the extra response can cause issues.
"""
import socket
import time
import sys
import os
from .base import DriverBase


class LMJ(DriverBase):

    def __init__(self, host="192.168.0.132", port=4944, poll_interval=10):
        """
        LMJ driver.
        :param host: host name
        :param port: port
        :param poll_interval: polling interval
        """

        DriverBase.__init__(self, poll_interval=poll_interval)
        self.host = host
        self.port = port
        self.start_thread()

    def _init(self):
        """
        Threaded initalisation.
        """
        self.logger.info("Initialising Excillum Driver")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10.0)
        self._connect()

        self.send("#admin")
        self.logger.info("Current state is: %s" % self.getstate())

    def _connect(self, retries=10):
        """
        Connect to the LMJ source.
        :param retries: Number of attempts before giving up
        """
        connected = False
        for i in range(retries):
            try:
                errno = self.sock.connect_ex((self.host, self.port))
                if errno == 0:
                    connected = True
                    break
            except:
                pass
            self.logger.error('Connection refused. Retrying %d/%d' % (i+1, retries))
            time.sleep(2)
        if not connected:
            raise RuntimeError('Connection refused.')

    def send(self, msg):
        send_msg = msg + "\n"
        self.sock.sendall(send_msg.encode())

    def rec(self):
        buff = ""
        while buff[-1:] != "\n":
            data = self.sock.recv(16384)
            if len(data) < 1:
                break
            buff += data
        buff = buff.split("\n")
        buff = buff[0].decode('utf-8')
        return buff

    def send_and_receive(self, message):
        """Combines sending and receiving and incluse a lock for threading"""
        with self._lock:
            try:
                self.send(message)
                msg = self.rec()
                msg = msg.strip("'")
            except:
                # Reconnect
                self.logger.error('Failed to communicate. Reconnecting')
                try:
                    self.sock.shutdown()
                except:
                    pass
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(10.0)
                self._connect()

        return msg

    def _finish(self):
        """Clean socket shutdown"""
        self.logger.debug("Shutting down.")
        self.sock.shutdown()
        self.sock.close()

    def mqtt_payload(self):
        return {'xnig/drivers/excillum/generator_emission_power_w': self.generator_emission_power_w,
                'xnig/drivers/excillum/state': self.getstate()}

    @property
    def state(self):
        return self.getstate()

    @state.setter
    def state(self, statestr):
        self.statechange(statestr)

    @property
    def spotsize_x_um(self):
        return self.send_and_receive("spotsize_x_um?")

    @property
    def spotsize_y_um(self):
        return self.send_and_receive("spotsize_y_um?")

    @property
    def generator_emission_current_a(self):
        return self.send_and_receive("generator_emission_current?")

    @property
    def generator_emission_power_w(self):
        return self.send_and_receive("generator_emission_power?")

    @property
    def generator_high_voltage(self):
        return self.send_and_receive("generator_high_voltage?")

    @property
    def vacuum_pressure_pa(self):
        return self.send_and_receive("vacuum_pressure_mbar_short_average?")

    @property
    def jet_pressure_pa(self):
        return self.send_and_receive("jet_pressure_average?")

    @property
    def spot_position_x_um(self):
        return self.send_and_receive("spot_position_x_um?")

    @property
    def spot_position_y_um(self):
        return self.send_and_receive("spot_position_y_um?")

    # @spot_size.setter(self, value):

    def _overridebool(self):
        override = input("Excillum is busy, override? y/[n] ")
        if override == '':
            override = 'n'
        while override != 'y' and override != 'n':
            override = input("invalid input, please answer 'y' or 'n': ")
        if override == 'y':
            return True
        else:
            return False         

    def statechange(self, statestr):
        current_state = self.getstate()
        if current_state.endswith("..."):
            if self._overridebool():
                self.logger.info("Aborting %s" % current_state)
            else:
                self.logger.info("Not changing state from %s to %s" % (current_state, statestr))
                return
 
        print(("Changing state from %s to %s" % (current_state, statestr)))
        cmd = "state=" + statestr

        response = self.send_and_receive(cmd)
        current_state = ""
        while self.getstate().endswith("..."):
            read_state = self.getstate()
            if response.startswith("error"):
                raise RuntimeError(response)
            if current_state != read_state:
                print("changing...")
                current_state = read_state
                print(current_state)
            time.sleep(1)
            print(("State is now %s" % self.getstate()))

    def getstate(self):
        state = self.send_and_receive("state?")
        return state


def main():
    ex = LMJ()
    if sys.argv[1] == "critical":
        ex.logger.critical("POWER FAILURE, SHUTDOWN IMMINENT, ATTEMPTING TO STOP AND VENT")
#        timeout = 3000.  # 50 minute timeout
#        t0 = time.time()
#        while(ex.state != "vent" or time.time() - t0 < timeout):
#           ex.state="stop"  # not sure if this works!
#           ex.state="vent"
        exit()

    while True:
        try:
            cmd = eval(input("cmd: "))
            ex.state = str(cmd)
        except KeyboardInterrupt:
            print("Exiting API")


if __name__ == "__main__":
    main()
