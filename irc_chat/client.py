import argparse
import socket
import threading

import command
import file_receiver
import reply

BUFFER_SIZE = 1024


class Client:
    __server_socket: socket.socket
    __input_prefix: str

    def __init__(self, host: str, port: int, nickname: str = ""):
        self.__host = host
        self.__port = port
        self.__nickname = nickname

        self.__server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # self.__server_socket.setblocking(False)
        self.__server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.__server_socket.connect_ex((self.__host, self.__port))
        self.__input_prefix = ""
        self.__last_pm = ""

        if self.__nickname:
            self.__send_nickname()

        self.__recv_thread = threading.Thread(target=self.__recv_thread_func)
        self.__recv_thread.start()

        self.__send_thread = threading.Thread(target=self.__send_thread_func, daemon=True)
        self.__send_thread.start()

    def __send_message(self, message: str):
        self.__server_socket.sendall(message.encode())

    def __send_thread_func(self):
        while True:
            message = input(self.__input_prefix)
            self.__send_message(message)
            if command.commands["QUIT"].is_format(message):
                break
            elif command.commands["SET_MSG"].is_format(message):
                self.__last_pm = command.commands["SET_MSG"].get_args(message)[0]

    def __recv_thread_func(self):
        while True:
            data = self.__server_socket.recv(BUFFER_SIZE)
            cur_data = data
            while len(cur_data) >= BUFFER_SIZE:
                cur_data = self.__server_socket.recv(BUFFER_SIZE)
                data += cur_data
            if data:
                msg = data.decode()
                rep = reply.parse_base(msg)
                cmd = command.parse_command(msg)
                if rep:
                    if reply.all_replies["RPL_PRVTMSGON"].is_format(msg):
                        self.__input_prefix = "PRIVMSG " + self.__last_pm + ": "
                        continue
                    elif reply.all_replies["RPL_PRVTMSGOFF"].is_format(msg):
                        self.__input_prefix = ""
                        continue
                    print("Server> " + rep.reply_message)
                    if rep is reply.all_replies["RPL_DISCONNECTED"]:
                        break
                elif cmd:
                    if cmd is command.commands["SERVER_DOWNLOAD"]:
                        args = cmd.get_args(msg)
                        self.__receive_file(args[0], int(args[1]))
                else:
                    print(msg)
                # cmd = command.parse_command(data.decode())
            else:
                break

    def __send_nickname(self):
        self.__send_message(command.commands["CONNECT"].format(self.__nickname))

    def __receive_file(self, output_path: str, udp_port: int):
        # file_receiver.getFile(udp_port, output_path)
        threading.Thread(target=file_receiver.get_file, args=(udp_port, output_path)).start()



def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-a",
        "--address",
        dest="listen_address",
        type=str,
        default='127.0.0.1',
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
    parser.add_argument(
        "-n",
        "--nickname",
        dest="nickname",
        default='',
        help="Nickname to use",
        type=str
    )

    return parser.parse_args()


def main():
    options = get_args()
    client = Client(options.listen_address, options.listen_port, nickname=options.nickname)
    # client.run()


if __name__ == '__main__':
    main()
