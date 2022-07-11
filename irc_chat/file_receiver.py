import json
import os
import socket
import time

import utils


class FileReceiver:
    def __init__(self, client_address: tuple[str, int], output_path: str, MSS: int):
        self.finished = False
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.client_address = client_address
        self.output_path = output_path
        self.file_name = os.path.basename(output_path)
        self.MSS = MSS
        self.buffer_capacity = 65536
        self.buffer_segment_amount = int(self.buffer_capacity / self.MSS)
        self.receive_window_size = 0
        self.buffer = []
        self.first_packet = True
        self.file_size = 0
        self.progress = 0
        self.segment_counter = 0
        self.last_time_received = 0
        self.file = None
        self.seq_num = 0

    def receive_segment(self, segment: bytes) -> bool:
        """
        Receives a segment and writes it to the file. and handles server communication.
        :param segment: The segment to be written to the file.
        :return: True if the segment was the last segment, False otherwise.
        """
        seq_num, _, _, syn, fin, _, data = utils.unpack_header(segment)
        finished_receiving = False
        if syn and not fin:
            # file_info = json.loads(data.decode())
            self.file = open(self.output_path, 'wb')
            print(f'Receiving file {self.file_name} from {self.client_address}')
            self.seq_num = seq_num + len(data)
        elif len(self.buffer) < self.buffer_segment_amount and seq_num >= self.seq_num:
            if self.first_packet:
                self.first_packet = False
                self.file_size = json.loads(data.decode())
                part, unit = utils.convert_size(self.file_size)
                print(f'The size of the file is {part:.3f} {unit}')
                self.seq_num = seq_num + len(data)
                self.last_time_received = time.time()
            else:
                # # Print the progress every 5 percent of progress
                # prog_interval = 5
                # prog = self.progress
                # while self.segment_counter * self.MSS / self.file_size >= self.progress * prog_interval / 100:
                #     self.progress += 1
                # if prog < self.progress:
                #     print(f'Received {(self.progress - 1) * prog_interval}%')
                #     speed = self.segment_counter * self.MSS / (time.time() - self.last_time_received)
                #     part, unit = utils.convert_size(speed)
                #     print(f'Speed: {part:.3f} {unit}/s')
                i = 0
                while i < len(self.buffer) and self.buffer[i][0] < seq_num:
                    i += 1
                # Determine whether duplicate
                if len(self.buffer) == 0 or i == len(self.buffer) or self.buffer[i][0] != seq_num:
                    self.buffer.insert(i, (seq_num, data, utils.to_ASF(ack=False, syn=syn, fin=fin)))
                    # Cast out from self.RcvBuffer
                    i = 0
                    while i < len(self.buffer) and self.seq_num == self.buffer[i][0]:
                        self.seq_num += len(self.buffer[i][1])
                        # FIN
                        if utils.from_ASF(self.buffer[i][2])[2]:
                            self.file.close()
                            print(f'File received from {self.client_address}')
                            finished_receiving = True
                        else:
                            self.file.write(self.buffer[i][1])
                            self.segment_counter += 1
                        i += 1
                    self.buffer = self.buffer[i:]
                    if len(self.buffer) == self.buffer:
                        self.buffer.pop(0)
        # ACK
        header = utils.pack_header(ack_number=self.seq_num, ack=True,
                                   receive_window=(self.buffer_segment_amount - len(self.buffer)) * self.MSS)
        self.socket.sendto(header, self.client_address)
        return finished_receiving


class ServerSocket(object):
    def __init__(self, server_port, MSS):
        self.server_port = server_port
        self.MSS = MSS
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.connections = {}  # {clientAddress: LFTPServer}

    def start(self, filename):
        self.socket.bind(('', self.server_port))
        print(f'The server is listening at {self.server_port}')
        self.listen(filename)

    def listen(self, filename):
        while True:
            segment, client_address = self.socket.recvfrom(self.MSS + utils.HEADER_SIZE)
            for c in list(self.connections.items()):
                if c[1].finished:
                    del (self.connections[c[0]])
            if client_address not in self.connections:
                print(f'Accept connection from {client_address}')
                self.connections[client_address] = FileReceiver(client_address, filename, self.MSS)
            if self.connections[client_address].receive_segment(segment):
                return


def get_file(PORT, filename):
    server = ServerSocket(PORT, 5360)
    server.start(filename)
