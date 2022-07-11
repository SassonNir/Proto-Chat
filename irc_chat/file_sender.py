import json
import os
import random
import socket
import threading
import time

import utils


# https://datatracker.ietf.org/doc/html/rfc5681
class FileSender:
    def __init__(self, server_address: tuple[str, int], file_path: str, MSS: int,
                 events: list[threading.Event, threading.Event] = None):
        self.running = False
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_address = server_address

        self.file_path = file_path
        self.file_name = os.path.basename(file_path)
        self.file_size = os.path.getsize(file_path)
        self.file = open(file_path, 'rb')

        self.MSS = MSS
        self.buffer_capacity = 65536
        self.buffer_segment_amount = int(self.buffer_capacity / self.MSS)
        # Random initial sequence number according to RFC in order to avoid attacks
        self.initial_seq_num = random.randint(0, 2 ** 16 - 1)
        self.seq_num = self.initial_seq_num
        self.next_byte_seq_num = self.initial_seq_num

        self.progress = 1
        self.duplicate_ack_count = 0
        self.receive_window_size = 0
        self.timeout_interval = 1.0
        self.estimated_RTT = 1.0
        self.deviation_RTT = 0
        self.congestion_status = utils.CCStatus.SLOW_START
        self.congestion_window_size = MSS
        self.ss_threshold = 65536  # RFC 5681 - The initial value of ssthresh SHOULD be set arbitrarily high

        self.alpha = 0.125
        self.beta = 0.25
        self.gamma = 4

        self.start_time = time.time()
        # SYN
        header = utils.pack_header(sequence_number=self.seq_num, syn=1,
                                   data=json.dumps({'filename': self.file_name}).encode())
        # [[SeqNum, Segment, Sent, Start Time]]
        self.buffer = [[self.next_byte_seq_num, header, False, 5]]
        self.next_byte_seq_num += len(self.buffer[0][1]) - utils.HEADER_SIZE

        self.events = events

        self.lock = threading.Lock()
        funcs = [self.__read_to_buffer, self.__receive_response, self.__detect_timeout, self.__slide_window]
        self.wait_for_response = [threading.Event() for _ in range(len(funcs))]
        self.results = [[] for _ in range(len(funcs))]
        self.pool = [threading.Thread(target=f, args=(self.results[i], self.wait_for_response[i])) for i, f in
                     enumerate(funcs)]
        self.first_packet = True

    def start(self):
        """
        Starts the thread pool and waits for the threads to finish.
        :return: The results of the threads.
        """
        self.running = True
        for t in self.pool:
            t.start()
        print('Start')
        for t in self.pool:
            t.join()
        return self.results

    def __read_to_buffer(self, results: list, wait_for_response: threading.Event):
        """
        Reads the file to the buffer.
        :param results: Output of the thread.
        """
        while self.running:
            self.lock.acquire()
            if self.first_packet:
                self.first_packet = False
                header = utils.pack_header(sequence_number=self.next_byte_seq_num,
                                           data=json.dumps(self.file_size).encode())
                self.buffer.append([self.next_byte_seq_num, header, False, time.time()])
                self.next_byte_seq_num += len(self.buffer[-1][1]) - utils.HEADER_SIZE
            if len(self.buffer) < self.buffer_segment_amount:
                segment = self.file.read(self.MSS)
                if len(segment) == 0:
                    self.file.close()
                    header = utils.pack_header(sequence_number=self.next_byte_seq_num, fin=1, data=b'0')
                    self.buffer.append([self.next_byte_seq_num, header, False])  # debugging , time.time()
                    self.lock.release()
                    break
                # Save last byte of the last segment
                if not len(results):
                    results.append(segment[-1])
                else:
                    results[0] = segment[-1]
                header = utils.pack_header(sequence_number=self.next_byte_seq_num, data=segment)
                self.buffer.append([self.next_byte_seq_num, header, False, time.time()])
                self.next_byte_seq_num += len(self.buffer[-1][1]) - utils.HEADER_SIZE
            self.lock.release()

    def __switch_CC_state(self, event: utils.CCEvent):
        """
        Switches the congestion control state.
        :param event: The event that caused the state change.
        """
        old_status = self.congestion_status

        if event == utils.CCEvent.ACK:
            self.duplicate_ack_count = 0
            if self.congestion_status == utils.CCStatus.SLOW_START:
                self.congestion_window_size += self.MSS
            elif self.congestion_status == utils.CCStatus.CONGESTION_AVOIDANCE:
                self.congestion_window_size += self.MSS * (self.MSS / self.congestion_window_size)
            elif self.congestion_status == utils.CCStatus.FAST_RECOVERY:
                self.congestion_window_size = self.ss_threshold
                self.congestion_status = utils.CCStatus.CONGESTION_AVOIDANCE
            else:
                raise Exception('Unknown congestion status')
        elif event == utils.CCEvent.TIMEOUT:
            self.duplicate_ack_count = 0
            self.__retransmit()
            if self.congestion_status in [utils.CCStatus.SLOW_START, utils.CCStatus.CONGESTION_AVOIDANCE,
                                          utils.CCStatus.FAST_RECOVERY]:
                self.ss_threshold = self.congestion_window_size / 2
                self.congestion_window_size = self.MSS
                self.congestion_status = utils.CCStatus.SLOW_START
            else:
                raise Exception('Unknown congestion status')
        elif event == utils.CCEvent.DUP_ACK:
            self.duplicate_ack_count += 1
            if self.duplicate_ack_count == 3:
                self.__retransmit()
                if self.congestion_status in [utils.CCStatus.SLOW_START, utils.CCStatus.CONGESTION_AVOIDANCE]:
                    self.ss_threshold = self.congestion_window_size / 2
                    self.congestion_window_size = self.ss_threshold + 3
                    self.congestion_status = utils.CCStatus.CONGESTION_AVOIDANCE
                elif self.congestion_status == utils.CCStatus.FAST_RECOVERY:
                    pass
                else:
                    raise Exception('Unknown congestion status')
        else:
            raise Exception('Unknown congestion event')
        if self.congestion_window_size >= self.ss_threshold:
            self.congestion_status = utils.CCStatus.CONGESTION_AVOIDANCE
        if old_status is not self.congestion_status:
            print(f'Congestion status switched from {old_status.name} to {self.congestion_status.name}')

    def __retransmit(self):
        """
        Retransmits the oldest segment in the buffer.
        """
        for segment in self.buffer:
            if segment[0] == self.seq_num:
                segment[3] = time.time()
                self.socket.sendto(segment[1], self.server_address)
                # self.duplicate_ack_count = 1
                print(f"Retransmitting {self.seq_num}")
                self.start_time = time.time()
                break

    def __receive_response(self, results: list, wait_for_response: threading.Event):
        """
        Receives the response from the server and handles congestion control state changes.
        :param results: Output of the thread.
        """
        while self.running:
            segment = self.socket.recvfrom(self.MSS + utils.HEADER_SIZE)[0]
            self.lock.acquire()
            _, ack_num, _, _, _, recv_window, _ = utils.unpack_header(segment)
            if ack_num == self.seq_num:  # If the received segment is the next expected segment
                self.__switch_CC_state(utils.CCEvent.DUP_ACK)
            elif ack_num > self.seq_num:
                self.seq_num = ack_num
                self.__switch_CC_state(utils.CCEvent.ACK)
                # Print the progress every 5 percent
                prog_interval = 5
                prog = self.progress
                while (self.seq_num - self.initial_seq_num) / self.file_size >= self.progress * prog_interval / 100:
                    self.progress += 1
                if self.events and (self.progress - 1) * prog_interval == 50:
                    self.events[1].set()
                    self.events[0].wait()
                if prog < self.progress:
                    print(f"Sent {(self.progress - 1) * prog_interval}%")
                    print(
                        f"EstimatedRTT={self.estimated_RTT:.2f} DeviationRTT={self.deviation_RTT:.2f} TimeoutInterval={self.timeout_interval:.2f}")
                while len(self.buffer) and self.buffer[0][0] < self.seq_num:
                    self.__update_timeout_interval(self.buffer[0][3])
                    seg = self.buffer.pop(0)
                    _, _, _, syn, fin, _, data = utils.unpack_header(seg[1])
                    if len(self.buffer) == 0 and fin and not syn:
                        self.running = False
                        self.socket.close()
                        print('Finished')
            self.receive_window_size = recv_window
            self.start_time = time.time()
            self.lock.release()

    def __update_timeout_interval(self, start_time: float):
        """
        Updates the timeout interval based on the RTT.
        :param start_time: Time when the segment was sent.
        """
        end_time = time.time()
        sample_RTT = end_time - start_time
        self.estimated_RTT = (1 - self.alpha) * self.estimated_RTT + self.alpha * sample_RTT
        self.deviation_RTT = (1 - self.beta) * self.deviation_RTT + self.beta * abs(sample_RTT - self.estimated_RTT)
        self.timeout_interval = self.estimated_RTT + self.gamma * self.deviation_RTT

    def __detect_timeout(self, results: list, wait_for_response: threading.Event):
        """
        Detects if the timeout interval has been exceeded.
        :param results: Output of the thread.
        """
        while self.running:
            self.lock.acquire()
            if time.time() - self.start_time > self.timeout_interval:
                self.__switch_CC_state(utils.CCEvent.TIMEOUT)
            self.lock.release()

    def __slide_window(self, results: list, wait_for_response: threading.Event):
        """
        Slides the window based on the congestion control state.
        :param results: Output of the thread.
        """
        while self.running:
            self.lock.acquire()
            for seg in self.buffer:
                # Flow Control
                if not seg[2] and seg[0] - self.seq_num <= min(self.receive_window_size, self.congestion_window_size):
                    seg.append(time.time())
                    self.socket.sendto(seg[1], self.server_address)
                    self.start_time = time.time()
                    seg[2] = True
                elif not seg[2]:
                    break
            self.lock.release()


def send_file(server_address: tuple[str, int], filename: str,
              wait_events: list[threading.Event, threading.Event] = None):
    time.sleep(2)
    client = FileSender(server_address, filename, MSS=1024, events=wait_events)
    out = client.start()
    return out
