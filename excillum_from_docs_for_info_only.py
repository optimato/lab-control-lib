""" Copyright 2016, Excillum AB. All rights reserved.

    The copyright to the computer program(s) herein
    is the property of Excillum AB.
    The program(s) may be used and/or copied only with
    the written permission of Excillum AB
    or in accordance with the terms and conditions
    stipulated in the agreement/contract under which
    the program(s) have been supplied.

    Description: Example on how to use the excillum api.
                 The example monitors the vacuum pressure
                 performs a full parametrization and takes
                 the source to on.
    Author: fredrik.bjornsson@excillum.com
"""
import sys
import socket
import time
import threading

"""
 Method that print the message
"""
def log(msg):
    print(msg)

class Msg(object):
    """
    Class thar send and receives data on the tcp socket
    """
    def __init__(self, hostname):
        self.hostname = hostname
        self.fd = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.fd.settimeout(10.0)
        self.port = 4944
        self.fd.connect((self.hostname, self.port))

    def __del__(self):
        self.fd.close()

    def rec(self):
        """
        Receive a message from the source.
        """
        buf = ""
        while True:
            data = self.fd.recv(16384).decode('utf-8')
            buf += data
            len_data = len(data)
            if len_data < 1:
                break
            if data[len_data-1] == "\n":
                break
        return buf

    def send(self, data):
        """
        Send a message to the source.
        """
        send_msg = data + "\n"
        self.fd.sendall(send_msg.encode())

class XcsMonitor(object):
    """
    Class that reads monitors
    """
    def __init__(self, hostname):
        self.hostname = hostname
        self.msg = Msg(self.hostname)

    def get(self, monitor):
        """
        Get a monitor
        """
        self.msg.send(monitor + "?")
        rec = self.msg.rec()
        log(monitor + "=" + rec)

    def run(self):
        """
        Thread loop
        """
        while True:
            time.sleep(60.0)
            self.get("vacuum_pressure_mbar")

class XcsClient(object):
    """
    Class that takes the source to state on.
    """
    def __init__(self, hostname):
        self.hostname = hostname
        self.msg = Msg(self.hostname)

    def heatertune(self):
        """
        Check if heatertune is done, if not perform a heatertune
        """
        self.msg.send("$heatertune.heating_points?")
        rec = self.msg.rec()
        if "[]" in rec:
            log("performing heatertune")
            self.go2state("heatertune")
        else:
            log("heatertune already done")

    def cathodebake(self):
        """
        Check if cathodebake is done, if not bake.
        """
        self.msg.send("$cathodebake.completed?")
        rec = self.msg.rec()
        if "true" not in rec:
            log("performing cathodebake")
            self.go2state("cathodebake")

    def parametrization(self):
        """
        Do a full parametrization.
        """
        self.heatertune()
        self.cathodebake()
        states = ["lowpower", "align", "segment", "focus", "linefocus", "lowpower"]
        for state in states:
            self.go2state(state)

    def run(self):
        """
        Thread loop
        """
        self.msg.send("#version")
        ver = self.msg.rec()
        log("xcs software version is " + ver)
        self.msg.send("#user")
        self.go2state("ready")
        self.setpoints(70000.0, 200.0, 80.0, 20.0)
        self.parametrization()
        self.setpoints(70000.0, 200.0, 80.0, 20.0)

        if self.jet_is_stable() is True:
            self.go2state("on")
        else:
            log("Check jetstability!")


    def setpoints(self, high_voltage, power, spotsize_x, spotsize_y):
        """
        Set high_voltage, power and spotsize
        """
        self.msg.send("spotsize_x_um=" + str(spotsize_x))
        rec = self.msg.rec()
        log("set spotsize x " + rec)
        self.msg.send("spotsize_y_um=" + str(spotsize_y))
        rec = self.msg.rec()
        log("set spotsize y " + rec)

        self.msg.send("generator_high_voltage=" + str(high_voltage))
        rec = self.msg.rec()
        log("set high voltage " + rec)
        emission_current = power / high_voltage
        self.msg.send("generator_emission_current=" + str(emission_current))
        rec = self.msg.rec()
        log("set emission current " + rec)

    def go2state(self, state):
        """
        Goto the specified state
        """
        send_msg = "state=" + state
        self.msg.send(send_msg)
        self.msg.rec()
        while True:
            self.msg.send("state?")
            rec = self.msg.rec()
            rec = rec.replace("\n", "")
            rec = rec.replace("'", "")
            if rec == state:
                break
            else:
                log(rec)
                time.sleep(1.0)

    def jet_is_stable(self):
        """
        Check if the jet is stable
        """
        self.msg.send("jet_is_stable?")
        rec = self.msg.rec()
        return "true" in rec

def main():
    """
    Give the hostname as argument
    """
    size = len(sys.argv)
    if size == 2:
        hostname = sys.argv[1]
        client = XcsClient(hostname)
        thread = threading.Thread(target=client.run)
        thread.start()
        monitor = XcsMonitor(hostname)
        monitor_thread = threading.Thread(target=monitor.run)
        monitor_thread.start()
        thread.join()
        monitor_thread.join()
    else:
        log("usage python xcs_api_example.py <hostname>")

if __name__ == '__main__':
    main()