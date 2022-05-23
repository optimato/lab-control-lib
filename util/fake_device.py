import socket


class FakeDevice:
    def __init__(self, address, EOL=b'\n'):
        """
        Fake socket device acceptiing a single connection and processing a few commands.
        """
        self.address = address
        self.EOL = EOL
        self.client_sock = socket.socket(
            socket.AF_INET, socket.SOCK_STREAM)  # TCP socket
        self.client_sock.settimeout(100)
        self.client_sock.bind(address)
        self.client_sock.listen(5)
        self.client = None
        self.delay = 10.

        self.listen()

    def listen(self):
        from ..base import _recv_all

        print('Accepting connections.')
        while True:
            try:
                client, address = self.client_sock.accept()
                print('Client connected')
                client.settimeout(.5)
                t0 = 0
                pos0 = 0.
                dx = 0.
                while True:
                    # Read data
                    try:
                        data = _recv_all(client, EOL=self.EOL).strip()
                    except socket.timeout:
                        continue
                    data = data[2:]
                    data = data.decode(errors='ignore')
                    prompt = f'{data} >> '
                    reply = input(prompt)
                    client.sendall(reply.encode() + self.EOL)
            except socket.timeout:
                continue
