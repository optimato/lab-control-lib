
import numpy as np
import socket
import os
import time


class excillum_getter:
    """Code that connects to the Excillum controller for the purpose of recording its current parameters. The connection is
    opened on port 4944 and the current ip address is 192.168.0.132. The exact commands to send can be found in the excillum
    API document."""
    def __init__(self, host='192.168.0.132', port=4944):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM) #defining the socket type
        s.settimeout(10 )  #sets a timeout of 5 seconds
    
        
        # Connecting
    
        # connect_ex does same thing as connect but returns different numbers for different errrors - returns 0 if successful
        conn_errno = s.connect_ex((host, port))
        retry_count = 0  # counter for retries, limit to 10 retries
        while conn_errno != 0: 
            print('trying to connect')
            print(os.strerror(conn_errno))
            time.sleep(.05)

            conn_errno = s.connect_ex((host, port))
            retry_count += 1
            if retry_count > 10:
                raise RuntimeError('Connection refused.')
        
        self.spotsize_x_um = self.cmd_send('spotsize_x_um?\n', s) # SPOTSIZE X DIRECTION - in um
        self.spotsize_y_um = self.cmd_send('spotsize_y_um?\n', s) # SPOTSIZE Y DIRECTION - in um
        self.generator_emission_current_a = self.cmd_send('generator_emission_current?\n', s) # EMISSION CURRENT - in Amps
        self.generator_emission_power_w = self.cmd_send('generator_emission_power?\n', s) # GENERATOR POWER in W
        self.generator_high_voltage = self.cmd_send('generator_high_voltage?\n', s) # GENERATOR HIGH VOLTAGE in V
        self.vacuum_pressure_pa = str(float(self.cmd_send('vacuum_pressure_mbar_short_average?\n', s))/100) # VACUUM PRESSURE in Pa
        self.jet_pressure_pa = str(float(self.cmd_send('jet_pressure_average?\n', s))/100000) # JET PRESSURE in Pa
        self.spot_position_x_um = self.cmd_send('spot_position_x_um?\n', s) # SPOT POSITION in um
        self.spot_position_y_um = self.cmd_send('spot_position_y_um?\n', s) # SPOT POSITION in um
        
        s.close()

    def cmd_send(self, cmd, s):
        """Send a command to a controller and reads back the input"""
        s.sendall(cmd)
        try:
            o = ''
            while o == '':
                o = s.recv(1024)
            return o[:-1]#removing /n from string
        except socket.timeout:
            print('communication timed out...')
            return 