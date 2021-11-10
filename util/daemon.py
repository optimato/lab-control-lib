import jupyter_client
import psutil

def get_daemon():
    try:
        cf=jupyter_client.find_connection_file('xnig_kernel.json')
        km = jupyter_client.BlockingKernelClient(connection_file=cf)
        km.load_connection_file()
        return cf, km
    except IOError:
        return False, False

def is_running(address, port):
    connections = psutil.net_connections()

    for connection in connections:
        try:
            if connection.raddr.ip == address and int(connection.raddr.port) == int(port) and connection.status == 'ESTABLISHED':
                return True
        except AttributeError:
            pass
    return False