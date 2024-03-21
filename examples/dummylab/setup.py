#!/usr/bin/env python

from setuptools import setup
import os
import subprocess
import time

CLASSIFIERS = """\
Development Status :: 3 - Alpha
Intended Audience :: Science/Research
License :: OSI Approved
Programming Language :: Python
Topic :: Scientific/Engineering
Topic :: Software Development
Operating System :: Unix
"""

REQUIRES = ['numpy', 'cython', 'h5py', 'napari', 'rpyc']

setup(
    name='dummy-labcontrol',
    version='0.0.1',
    author='Pierre Thibault',
    description='A Dummy Lab Control demonstration',
    package_dir={'dummylab': 'dummylab'},
    packages=['dummylab'],
    install_requires=REQUIRES
    )
