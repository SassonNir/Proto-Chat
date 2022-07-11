import argparse
import os
import select
import socket
import threading
import time

import command
import file_sender
import reply

BUFFER_SIZE = 1024
FILES_DIR = "files/"


class Server:
    __user2socket: dict[bytes, socket.socket] = {}
    __socket2user: dict[socket.socket, bytes] = {}
    __user_message_mode: dict[socket.socket, socket.socket] = {}
    __connections: list[socket.socket]
    __proceedings: dict[socket.socket, list[threading.Event, threading.Event]]

    def __init__(self, host: str, port: int):
        self.__host = host
        self.__port = port

        self.__user2socket = {}  # nickname: client_socket
        self.__socket2user = {}  # client_socket: nickname
        self.__user_message_mode = {}  # client_socket: client_socket
        self.__proceedings = {}  # client_socket: threading.Event

        self.__user_count = 0

        self.__listening_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.__listening_socket.setblocking(False)
        self.__listening_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.__listening_socket.bind((self.__host, self.__port))
        self.__listening_socket.listen(5)

        self.__connections = [self.__listening_socket]

        print(f"Server started on {self.__host}:{self.__port}")
        self.__files = os.listdir(FILES_DIR)

    def run(self):
        while True:
            readable, writable, exceptional = select.select(self.__connections, [], [])
            for u in readable:
                if u is self.__listening_socket:  # new connection
                    self.__accept_new_client(u)
                else:  # new message
                    self.__handle_user_message(u)

            for sock in exceptional:
                sock.close()
                self.__connections.remove(sock)

    def __broadcast(self, message: bytes, exclude: socket = None, prefix: bytes = b"", excluded_prefix: bool = False):
        """
        Send message to all connected clients except the one specified by exclude.
        :param message: message to be broadcasted
        :param exclude: socket of the client to be excluded
        :param prefix: prefix to be added to the message
        :param excluded_prefix: whether to add the prefix to the message or not
        """
        if exclude and excluded_prefix and exclude in self.__socket2user and not prefix:
            prefix = self.__socket2user[exclude] + b"> "
        for client in self.__socket2user:
            if client is not exclude:
                client.sendall(prefix + message)

    def __private_message(self, client_socket: socket.socket, message: bytes, prefix: bytes = b"",
                          excluded_prefix: bool = False):
        """
        Send a private message to a specific user.
        :param client_socket:  client socket of the user to send the message to
        :param message:  message to be sent
        :param prefix:  prefix to be added to the message
        :param excluded_prefix:  whether to add the prefix to the message or not
        """
        if excluded_prefix and not prefix:
            prefix = self.__socket2user[client_socket] + b"@PM> "
        if client_socket in self.__user_message_mode:
            receiver = self.__user_message_mode[client_socket]
            if receiver in self.__socket2user:
                receiver.sendall(prefix + message)

    def __send_all(self, client_socket: socket.socket, data: bytes, prefix: str = ""):
        """
        Send data to all connected clients except the one specified by client_socket.
        :param client_socket:  client socket of the client to be excluded
        :param data:  data to be sent
        :param prefix:  prefix to be added to the message
        """
        client_socket.sendall(prefix.encode() + data)
        time.sleep(0.1)

    def __accept_new_client(self, listening_socket: socket.socket):
        """
        Accept a new client connection.
        :param listening_socket:  listening socket of the server
        """
        client_socket, client_address = listening_socket.accept()
        client_socket.setblocking(False)
        self.__connections.append(client_socket)
        self.__send_all(client_socket, reply.all_replies["RPL_CONNECTED"].encode())
        if client_socket not in self.__socket2user:
            self.__send_all(client_socket, reply.all_replies["ERR_NONICKNAMEGIVEN"].encode())
        print(f"New client connected: {client_address}")

    def __handle_user_message(self, client_socket: socket.socket):
        """
        Handle a message from a client.
        :param client_socket:  client socket of the client
        :return:  void
        """
        try:
            data = client_socket.recv(BUFFER_SIZE)
            cur_data = data
            while len(cur_data) >= BUFFER_SIZE:
                cur_data = client_socket.recv(BUFFER_SIZE)
                data += cur_data
            if not data:
                self.__handle_user_disconnect(client_socket)
                return

            cmd = command.parse_command(data.decode())
            if cmd is command.commands["CONNECT"]:
                self.__handle_user_connect(client_socket, cmd, data)
                return
            if client_socket not in self.__socket2user:
                self.__send_all(client_socket, reply.all_replies["ERR_NONICKNAMEGIVEN"].encode())
                return
            if cmd is command.commands["DISCONNECT"] or cmd is command.commands["QUIT"]:
                self.__handle_user_disconnect(client_socket)
            elif cmd is command.commands["NICK"]:
                self.__handle_user_connect(client_socket, cmd, data)
            elif cmd is command.commands["LIST"] or cmd is command.commands["GET_USERS"]:
                self.__handle_user_list(client_socket)
            elif cmd is command.commands["SET_MSG"]:
                self.__handle_user_set_msg_mode(client_socket, cmd, data)
            elif cmd is command.commands["SET_MSG_ALL"]:
                self.__handle_user_set_msg_mode(client_socket, cmd, data, True)
            elif cmd is command.commands["GET_LIST_FILE"]:
                self.__handle_user_get_file_list(client_socket)
            elif cmd is command.commands["DOWNLOAD"]:
                self.__handle_user_download(client_socket, cmd, data)
            elif cmd is command.commands["PROCEED"]:
                self.__handle_user_proceed(client_socket, cmd, data)
            else:
                if client_socket in self.__proceedings and self.__proceedings[client_socket][1].is_set():
                    self.__send_all(client_socket, reply.all_replies["RPL_PROCEED"].encode())
                if client_socket in self.__user_message_mode:
                    self.__private_message(client_socket, data, prefix=self.__socket2user[client_socket] + b"@PM> ")
                else:
                    self.__broadcast(data, exclude=client_socket, prefix=self.__socket2user[client_socket] + b"> ")
        except Exception as e:
            self.__handle_user_disconnect(client_socket)

    def __handle_user_connect(self, client_socket: socket.socket, cmd: command.Command, data: bytes):
        """
        Handle a CONNECT command from a client.
        :param client_socket:  client socket of the client
        :param cmd:  command to be handled
        :param data:  data to be handled
        :return:  void
        """
        nickname = cmd.get_args(data.decode())[0].encode()
        if nickname in self.__user2socket:
            self.__send_all(client_socket, reply.all_replies["ERR_NICKNAMEINUSE"].encode())
            return
        if b' ' in nickname:
            self.__send_all(client_socket, reply.base["ERROR"].with_message("Nickname cannot contain spaces").encode())
            return
        old_nickname = self.__socket2user.get(client_socket, None)
        self.__user2socket[nickname] = client_socket
        self.__socket2user[client_socket] = nickname
        if old_nickname is None:
            self.__send_all(client_socket, reply.all_replies["RPL_WELCOME"].encode() + b' ' + nickname)
            self.__broadcast(f"'{nickname.decode()}' joined the chat".encode(), exclude=client_socket,
                             prefix=b"Server> ")
            print(f"{client_socket.getpeername()} connected as {nickname.decode()}")
        else:
            self.__broadcast(f"{old_nickname} is now known as {nickname.decode()}".encode(), exclude=client_socket)
            print(f"{client_socket.getpeername()} changed nickname from {old_nickname.decode()} to {nickname.decode()}")

    def __handle_user_disconnect(self, client_socket: socket.socket):
        if client_socket in self.__socket2user:
            nickname = self.__socket2user[client_socket]
            del self.__user2socket[nickname]
            del self.__socket2user[client_socket]
            self.__broadcast(f"{nickname.decode()} has left the chat".encode())
        print(f"{client_socket.getpeername()} disconnected")
        client_socket.sendall(reply.all_replies["RPL_DISCONNECTED"].encode())
        client_socket.close()
        self.__connections.remove(client_socket)

    def __handle_user_list(self, client_socket: socket.socket):
        user_list = b",".join(self.__user2socket.keys())
        self.__send_all(client_socket, reply.base["REPLY"].with_message(user_list.decode()).encode())

    def __handle_user_set_msg_mode(self, client_socket: socket.socket, cmd: command.Command, data: bytes,
                                   to_all: bool = False):
        if to_all and client_socket in self.__user_message_mode:
            self.__user_message_mode.pop(client_socket, None)
            self.__send_all(client_socket, reply.all_replies["RPL_PRVTMSGOFF"].encode())
            return
        args = cmd.get_args(data.decode())
        nick = args[0].encode()
        if nick not in self.__user2socket:
            self.__send_all(client_socket, reply.all_replies["ERR_NOSUCHNICK"].encode())
            return
        self.__user_message_mode[client_socket] = self.__user2socket[nick]
        self.__send_all(client_socket, reply.all_replies["RPL_PRVTMSGON"].encode())

    def __handle_user_get_file_list(self, client_socket: socket.socket):
        self.__files = os.listdir(FILES_DIR)
        file_list = ", ".join(self.__files)
        self.__send_all(client_socket, reply.base["REPLY"].with_message(file_list).encode())

    def __handle_user_download(self, client_socket: socket.socket, cmd: command.Command, data: bytes):
        down_thread = threading.Thread(target=self.__handle_user_download_thread,
                                       args=(client_socket, cmd, data))
        down_thread.start()

    def __handle_user_download_thread(self, client_socket: socket.socket, cmd: command.Command, data: bytes):
        args = cmd.get_args(data.decode())
        filename = args[0]
        output_path = args[1]

        # Establish new avalible port and closing it for the filesender port - TODO: make this less hacky
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_socket.bind(('', 0))
        server_port = server_socket.getsockname()[1]
        server_socket.close()
        self.__send_all(client_socket, command.commands["SERVER_DOWNLOAD"].format(output_path, server_port).encode())
        client_address = client_socket.getpeername()
        print(f"Starting a new thread from {client_address} at port {server_port}")

        if not os.path.isfile(os.path.join(FILES_DIR, filename)):
            self.__send_all(client_socket, reply.all_replies["ERR_FILENOTFOUND"].encode())
            return

        evee1 = threading.Event()
        evee2 = threading.Event()
        self.__proceedings[client_socket] = [evee1, evee2]
        print(f"Send {filename} to {client_address[0]}")
        results = file_sender.send_file((client_address[0], server_port), os.path.join(FILES_DIR, filename),
                                        self.__proceedings[client_socket])
        last_byte = results[0][0]
        message = f"User {self.__socket2user[client_socket].decode()} downloaded 100%. Last byte: {last_byte}"
        self.__send_all(client_socket, reply.base["REPLY"].with_message(message).encode())

    def __handle_user_proceed(self, client_socket: socket.socket, cmd: command.Command, data: bytes):
        if client_socket not in self.__proceedings:
            return
        self.__proceedings[client_socket][0].set()
        self.__proceedings.pop(client_socket, None)

    def get_number_connected(self):
        return len(self.__connections) - 1  # -1 for the server socket

    def get_connected_users(self):
        return set(u.decode() for u in self.__user2socket.keys())


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-a",
        "--address",
        dest="listen_address",
        default='127.0.0.1',
        type=str,
        help="IP on which to listen",
    )
    parser.add_argument(
        "-p",
        "--port",
        dest="listen_port",
        default=55000,
        type=int,
        help="Port on which to listen",
    )

    return parser.parse_args()


def main():
    options = get_args()
    server = Server(options.listen_address, options.listen_port)
    server.run()


if __name__ == '__main__':
    main()
