=======
Install
=======


Installing from source
======================
  
Clone the `lab-control-lib <https://github.com/optimato/lab-control-lib>`_  
from GitHub::

    git clone https://github.com/optimato/lab-control-lib.git

then::

    $ cd lab-control-lib
    $ pip install .

After the first installation, it is necessary to install the daemon service. installation
scripts will have been generated automatically in the ``scripts`` directory. On linux::

    $ cd scripts
    $ sudo ./linux_install_daemon.sh

On Windows, you can use the PowerShell script ``windows_install_daemon.ps1``. These
scripts should be run with administrator privileges. The scripts will install the daemon service
(a scheduled task under Windows) and start it. The service will be started automatically on 
system startup. There are also scripts to uninstall the service if needed. When updating the
library, it is not necessary to reinstall the service, but only to restart it. This can be 
done with the following command::

    $ python -m lclib -r
