"""
Dummy example lab

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import os
import lclib

# IPs of computer hosting some devices
host_ips = {
            'control': 'localhost',
            'other': '192.168.1.2'
            }

# This can be the location of a mounted file server
data_path = os.path.expanduser('~/dummylab-data/')
os.makedirs(data_path, exist_ok=True)
short_branch_data_path = data_path

# Dummy-specific hack: add 'localhost' as valid ip
lclib.local_ip_list.append('localhost')


from .drivers import Dummymotor, Dummydetector

# For demonstration purposes: define two lab layouts
lclib.register_layout(name='longbranch',
                data_path=data_path,
                manager_address=('localhost', 5001),
                components=[Dummymotor, Dummydetector])

lclib.register_layout(name='shortbranch',
                data_path=short_branch_data_path,
                manager_address=('localhost', 5003),
                components=[Dummymotor, Dummydetector])

