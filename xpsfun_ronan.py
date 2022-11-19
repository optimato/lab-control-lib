'''
Controller for Newport XPS Motors, written by Ronan

This code is based upon the XPS_Q8_drivers python code available from Newport
https://www.newport.com/medias/sys_master/images/images/hb9/h1d/8797307699230/XPS-Q8-Software-Drivers-Manual.pdf
Communication happens over a socket connection using IP/TCP

This uses the group XYZ, if errors are thrown trying to connect to this group, you should go into the XPS via the
network GUI on 192.168.0.254 and setup the group again.
'''

from .util.uitools import ask_yes_no
from .base import MotorBase
import socket

__all__ = ['XPS', 'Motor']

class XPS:

    # Defines
    MAX_NB_SOCKETS = 100

    # Global variables
    __sockets = {}
    __usedSockets = {}
    __nbSockets = 0

    def __init__(self):
        '''Connects to controller, kills the current group but retains the positional knowledge.
        The motors can then be re-initialised, homed(to callibrate them and moved back.
        If the controller has been powered down it will home to [0,0,0]'''
        self.init_done = False

        #liminting number of connections available
        XPS.__nbSockets = 0
        for socketId in range(self.MAX_NB_SOCKETS):
            XPS.__usedSockets[socketId] = 0

        #connecting to controller
        self.socketId = self.TCP_ConnectToServer('192.168.0.254', 5001, 20)
        if self.socketId == -1:
            raise RuntimeError('Failed to connect to XPS Controller')

        #killing previous group to prevent errors
        if ask_yes_no('Recallibrate XPS Motors?', yes_is_default=False):
            group = 'S'

            self.displayError(self.socketId, self.GroupKill(self.socketId, group))



            #initialise and keep positions
            self.displayError(self.socketId, self.GroupInitializeNoEncoderReset(self.socketId,group))
            #get position
            posn = self.displayError(self.socketId,self.GroupPositionCurrentGet(self.socketId, 'S', 1))
            #move it to [0,0,0] for callibration and move back again
            self.displayError(self.socketId, self.GroupHomeSearchAndRelativeMove(self.socketId,group, posn))
        posn = self.displayError(self.socketId, self.GroupPositionCurrentGet(self.socketId, 'S', 1))
        print('Motor at ' + str(posn) + ' (X,Y,Z)')
        self.init_done = True

    def displayError(self, socketId, x):
        errorCode = x[0]
        null_argument = x[1:]
        if errorCode == 0:
            return null_argument
        if (errorCode!= -2) and (errorCode!= -108):
            [errorCode2, errorString] = self.ErrorStringGet(socketId, errorCode)
            if (errorCode2!= 0):
                print('ERROR ' + str(errorCode))
            else:
                print(errorString)
        else:
            if (errorCode== -2):
                print('TCP timeout')
            if (errorCode == -108):
                print('The TCP/IP connection was closed by an administrator')
        return


    # GroupHomeSearchAndRelativeMove :  Start home search sequence and execute a displacement
    def GroupHomeSearchAndRelativeMove(self, socketId, GroupName, TargetDisplacement):
        if (XPS.__usedSockets[socketId] == 0):
            return

        command = 'GroupHomeSearchAndRelativeMove(' + GroupName + ','
        for i in range(len(TargetDisplacement)):
            if (i > 0):
                command += ','
            command += str(TargetDisplacement[i])
        command += ')'

        [error, returnedString] = self.__sendAndReceive(socketId, command)
        return [error, returnedString]


    # GroupKill :  Kill the group
    def GroupKill(self, socketId, GroupName):
        if (XPS.__usedSockets[socketId] == 0):
            return
        command = 'GroupKill(' + GroupName + ')'
        [error, returnedString] = self.__sendAndReceive(socketId, command)
        return [error, returnedString]


    def __sendAndReceive(self, socketId, command):
        try:
            XPS.__sockets[socketId].send(command)
            ret = XPS.__sockets[socketId].recv(1024)
            while ret.find(',EndOfAPI') == -1:
                ret += XPS.__sockets[socketId].recv(1024)
        except socket.timeout:
            return [-2, '']
        except socket.error(errNb, errString):
            print('Socket error : ' + errString)
            return [-2, '']

        for i in range(len(ret)):
            if (ret[i] == ','):
                return [int(ret[0:i]), ret[i + 1:-9]]


    # TCP_ConnectToServer
    def TCP_ConnectToServer(self, IP, port, timeOut):
        socketId = 0
        if (XPS.__nbSockets < self.MAX_NB_SOCKETS):
            while (XPS.__usedSockets[socketId] == 1 and socketId < self.MAX_NB_SOCKETS):
                socketId += 1
            if (socketId == self.MAX_NB_SOCKETS):
                return -1
        else:
            return -1

        XPS.__usedSockets[socketId] = 1
        XPS.__nbSockets += 1
        try:
            XPS.__sockets[socketId] = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            XPS.__sockets[socketId].connect((IP, port))
            XPS.__sockets[socketId].settimeout(timeOut)
            XPS.__sockets[socketId].setblocking(1)
        except socket.error:
            return -1

        return socketId


    # GroupInitializeNoEncoderReset :  Start the initialization with no encoder reset
    def GroupInitializeNoEncoderReset(self, socketId, GroupName):
        if (XPS.__usedSockets[socketId] == 0):
            return

        command = 'GroupInitializeNoEncoderReset(' + GroupName + ')'
        [error, returnedString] = self.__sendAndReceive(socketId, command)
        return [error, returnedString]


    # GroupPositionCurrentGet :  Return current positions
    def GroupPositionCurrentGet(self, socketId, GroupName, nbElement):
        if (XPS.__usedSockets[socketId] == 0):
            return

        command = 'GroupPositionCurrentGet(' + GroupName + ','
        for i in range(nbElement):
            if (i > 0):
                command += ','
            command += 'double *'
        command += ')'

        [error, returnedString] = self.__sendAndReceive(socketId, command)
        if (error != 0):
            return [error, returnedString]

        i, j, retList = 0, 0, [error]
        for paramNb in range(nbElement):
            while ((i + j) < len(returnedString) and returnedString[i + j] != ','):
                j += 1
            retList.append(eval(returnedString[i:i + j]))
            i, j = i + j + 1, 0

        return retList

    # ErrorStringGet :  Return the error string corresponding to the error code
    def ErrorStringGet(self, socketId, ErrorCode):
        if XPS.__usedSockets[socketId] == 0:
            return
        command = 'ErrorStringGet(' + str(ErrorCode) + ',char *)'
        [error, returnedString] = self.__sendAndReceive(socketId, command)
        return [error, returnedString]

    # GroupMoveAbsolute :  Do an absolute move
    def GroupMoveAbsolute(self, socketId, GroupName, TargetPosition):
        if (XPS.__usedSockets[socketId] == 0):
            return

        command = 'GroupMoveAbsolute(' + GroupName + ','
        for i in range(len(TargetPosition)):
            if (i > 0):
                command += ','
            command += str(TargetPosition[i])
        command += ')'

        [error, returnedString] = self.__sendAndReceive(socketId, command)
        return [error, returnedString]

    # GroupMoveRelative :  Do a relative move
    def GroupMoveRelative(self, socketId, GroupName, TargetDisplacement):
        if (XPS.__usedSockets[socketId] == 0):
            return

        command = 'GroupMoveRelative(' + GroupName + ','
        for i in range(len(TargetDisplacement)):
            if (i > 0):
                command += ','
            command += str(TargetDisplacement[i])
        command += ')'

        [error, returnedString] = self.__sendAndReceive(socketId, command)
        return [error, returnedString]

    def position_with_error(self, axis):
        """
        Gets position and checks for errors
        """
        addon = '.'+axis.upper()
        x = self.displayError(self.socketId, self.GroupPositionCurrentGet(self.socketId, 'XYZ'+addon, 1))
        return x

    def relative_movement(self, axis, dist):
        """
        Moves axis by dist mm
        """
        addon = '.' + axis.upper()
        self.displayError(self.socketId, self.GroupMoveRelative(self.socketId, 'XYZ'+addon, [dist]))
        return self.position_with_error(axis)

    def absolute_movement(self, axis, dist):
        """
        Moves axis to dist mm
        """
        addon = '.' + axis.upper()
        self.displayError(self.socketId, self.GroupMoveAbsolute(self.socketId, 'XYZ'+addon, [dist]))
        return self.position_with_error(axis)


class Motor(MotorBase):

    def __init__(self, name, driver, axis):
        """
        SmarAct Motor. axis is the driver's channel
        """
        super(Motor, self).__init__(name, driver)
        self.axis = axis

    def _get_pos(self):
        """
        Return position in mm
        """
        return self.driver.position_with_error(self.axis)[0]

    def _set_abs_pos(self, x):
        """
        Set absolute dial position
        """
        return self.driver.absolute_movement(self.axis, x)[0]

    def _set_rel_pos(self, x):
        """
        Set absolute position
        """
        return self.driver.relative_movement(self.axis, x)[0]
