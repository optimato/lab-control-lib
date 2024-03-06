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

version_file = os.path.join(os.path.abspath(
    os.path.dirname(__file__)), "lclib/_version.py")
gittag = subprocess.check_output(
    'git log --pretty=format:"%h %D %ci" -n 1', shell=True)
open(version_file, 'w').write(r'''# Version file generated automatically on installation ({date})
version = "{version}"
'''.format(date=time.ctime(), version=gittag))

MAJOR = 0
MINOR = 0
MICRO = 1
ISRELEASED = False
VERSION = '%d.%d.%d' % (MAJOR, MINOR, MICRO)

REQUIRES = ['numpy', 'cython', 'h5py', 'napari', 'rpyc', 'zmq']

setup(
    name='labcontrol-lib',
    version=VERSION,
    author='Pierre Thibault and others',
    description='Laboratory Control library initially designed for the Optimal Imaging and Tomography group, University of Trieste',
    package_dir={'lclib': 'lclib'},
    packages=['lclib',
             'lclib.ui',
             'lclib.util',
             'lclib.util.frameconsumer'],
    scripts=[
        'bin/lc'
        ],
    install_requires=REQUIRES,
    entry_points={'console_scripts': ['lc = lclib.__main__:cli']}
    )
