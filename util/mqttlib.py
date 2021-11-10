import paho.mqtt.client as paho
import time
import errno
from socket import error as socket_error
import logging

MQTT_HOST = '127.0.0.1'
MQTT_PORT = 1883


class MQTTLostServerException(Exception):
    pass


class MQTTNoServerException(Exception):
    pass


class MQTTSendRelay(object):
    GLOBAL_QOS = 0
    RETAIN = True
    MAX_RECONNECTS = 20

    def __init__(self, name, qos=GLOBAL_QOS, max_reconnects=MAX_RECONNECTS):
        """
        Initialize MQTT class.
        """
        self.logger = logging.getLogger(__name__)
        self.name = name
        self.qos = qos
        self.MAX_RECONNECTS = max_reconnects
        self.host = MQTT_HOST
        self.port = MQTT_PORT

        self.client = paho.Client(name)
        self._connect(True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.disconnect()

    def __del__(self):
        self.client.disconnect()

    def _connect(self, initial=False):
        """
        Handle connections to MQTT server.
        :param initial:
        :return:
        """
        try:
            self.client.connect(host=self.host, port=self.port, keepalive=0)
            self.client.on_publish = self.publish_callback
            self.client.on_disconnect = self._on_disconnect
            if not initial:
                self.logger.info("Reconnected to MQTT as %s." % self.name)
            else:
                self.logger.debug("Connected to MQTT as %s." % self.name)

        except socket_error as serr:
            if serr.errno != errno.ECONNREFUSED and serr.errno != errno.EPIPE:
                raise serr
            else:
                if not initial:
                    self.reconnects = self.reconnects + 1
                    if self.reconnects <= self.MAX_RECONNECTS:
                        time.sleep(1.0)
                        self._connect()
                    else:
                        self.logger.warning("MQTT: Failed to connect to MQTT after 5 attempts as %s." % self.name)
                        raise MQTTLostServerException
                else:
                    raise MQTTNoServerException

    def _on_disconnect(self, client, userdata, rc):
        self.reconnects = 0
        if rc != 0:
            self.logger.warning("MQTT: Unexpected disconnection as %s! Attempting to reconnect." % self.name)
            self._connect()

    def publish(self, stream):
        """
        Update MQTT.
        :param stream: data, or set to false to use stream object (untested)
        :return:
        """
        for topic, payload in stream.items():
            self.client.publish(topic=topic, payload=payload, qos=self.qos, retain=self.RETAIN)

    def publish_callback(self, *args):
        pass


if __name__ == '__main__':
    data_stream = {'tests/test1': 'this is a test data 1'}
    with MQTTSendRelay(name='test') as mqtt_obj:
        mqtt_obj.publish(data_stream)
        time.sleep(10)
