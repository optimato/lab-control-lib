#!/usr/bin/env python

from setuptools import setup
from setuptools.command.install import install
import os
import subprocess
import time
import logging

CLASSIFIERS = """\
Development Status :: 3 - Alpha
Intended Audience :: Science/Research
License :: OSI Approved
Programming Language :: Python
Topic :: Scientific/Engineering
Topic :: Software Development
Operating System :: Unix
"""
# version tag
version_file = os.path.join(os.path.abspath(
    os.path.dirname(__file__)), "lclib/_version.py")
gittag = subprocess.check_output(
    'git log --pretty=format:"%h %D %ci" -n 1', shell=True)
open(version_file, 'w').write(r'''# Version file generated automatically on installation ({date})
version = "{version}"
'''.format(date=time.ctime(), version=gittag))

class CustomInstallCommand(install):
    """
    Customized setuptools install command to generate service scripts
    """
    def run(self):
        install.run(self)

        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)

        logger.info("Running post-install service script generation...")
        try:
            import service_scripts
            service_scripts.generate_service_scripts()
        except Exception as e:
            logger.exception(f"Failed to generate service scripts: {e}")

MAJOR = 0
MINOR = 0
MICRO = 1
ISRELEASED = False
VERSION = '%d.%d.%d' % (MAJOR, MINOR, MICRO)

REQUIRES = ['numpy', 'ipython', 'h5py', 'napari', 'rpyc', 'zmq', 'click']

setup(
    name='labcontrol-lib',
    version=VERSION,
    author='Pierre Thibault and others',
    description='Laboratory Control library initially designed for the Optimal Imaging and Tomography group, University of Trieste',
    package_dir={'lclib': 'lclib'},
    packages=['lclib',
             'lclib.ui',
             'lclib.util',
             'lclib.util.frameconsumer',
             'lclib.library'],
    scripts=[
        'bin/lc'
        ],
    install_requires=REQUIRES,
    cmdclass={
        'install': CustomInstallCommand,
    },
    )
