import socket

class Server_Socket():

    def __init__(self, host, port, transport_type):
        self.buffer_size = 1024
        self.host = host
        self.port = port
        self.transport_type = transport_type

        if self.transport_type == "TCP":
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        elif self.transport_type == "UDP":
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
    def bind(self):
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.host, self.port))

    def accept(self):
        self._socket.listen(5)
        self.client_connection, self.client_address = self._socket.accept()
        return self.client_connection, self.client_address
        
    def receive_message(self):
        if self.transport_type == "TCP":
            message = self.client_connection.recv(self.buffer_size)
        elif self.transport_type == "UDP":
            message = self.client_connection.recvfrom(self.buffer_size)
        else:
            pass   
        message = message.decode("utf-8")
        return message
 
    def send_message(self, message):
        if self.transport_type == "TCP":
            self._socket.send(message.encode("utf-8"))
        elif self.transport_type == "UDP":
            self._socket.sendto(message.encode("utf-8"))
        else:
            pass

    def close(self):
        self._socket.close()

class Client_Socket():
    
    def __init__(self, host, port, transport_type):
        self.buffer_size = 1024
        self.host = host
        self.port = port
        self.transport_type = transport_type

        if self.transport_type == "TCP":
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        elif self.transport_type == "UDP":
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def connect(self):
        self._socket.connect((self.host, self.port))
        
    def receive_message(self):
        if self.transport_type == "TCP":
            message = self._socket.recv(self.buffer_size)
        elif self.transport_type == "UDP":
            message = self._socket.recvfrom(self.buffer_size)
        else:
            pass
        message = message.decode("utf-8")   
        return message 
        
    def send_message(self, message):
        if self.transport_type == "TCP":
            self._socket.send(message.encode("utf-8"))
        elif self.transport_type == "UDP":
            self._socket.sendto(message.encode("utf-8"))
        else:
            pass

    def close(self):
        self._socket.close()