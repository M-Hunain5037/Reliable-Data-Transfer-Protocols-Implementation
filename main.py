import random
import time
import threading
from enum import Enum

# Configuration Parameters
PROB_CORRUPTION = 0.1
PROB_LOSS = 0.1
PROB_DELAY = 0.1
MAX_DELAY = 0.5

TIMEOUT_DURATION = 1.0
WINDOW_SIZE = 4
TOTAL_PACKETS = 10

# Packet Type Enum
class PacketType(Enum):
    DATA = 1
    ACK = 2

# Packet Structure
class Packet:
    def __init__(self, sequence_number, payload=None, packet_type=PacketType.DATA):
        self.seq = sequence_number
        self.payload = payload
        self.type = packet_type
        self.checksum = self._compute_checksum()

    def _compute_checksum(self):
        data = f"{self.seq}{self.payload}{self.type}".encode()
        return sum(data) % 256

    def is_corrupt(self):
        return self.checksum != self._compute_checksum()

    def __str__(self):
        return f"<Packet type={self.type.name}, seq={self.seq}, checksum={self.checksum}, payload={self.payload}>"

# Simulated Unreliable Channel
class UnreliableChannel:
    def __init__(self, loss=PROB_LOSS, corruption=PROB_CORRUPTION, delay=PROB_DELAY, max_delay=MAX_DELAY):
        self.loss = loss
        self.corruption = corruption
        self.delay = delay
        self.max_delay = max_delay

    def transmit(self, packet, receiver_callback):
        if random.random() < self.loss:
            print(f"[CHANNEL] DROPPED {packet}")
            return

        if random.random() < self.corruption:
            print(f"[CHANNEL] CORRUPTED {packet}")
            packet.checksum = (packet.checksum + 1) % 256

        if random.random() < self.delay:
            delay_time = random.uniform(0, self.max_delay)
            print(f"[CHANNEL] DELAYING {packet} by {delay_time:.2f} sec")
            threading.Timer(delay_time, lambda: receiver_callback(packet)).start()
        else:
            receiver_callback(packet)

# rdt 3.0: Stop-and-Wait
class StopAndWaitRDT:
    def __init__(self, channel, total=TOTAL_PACKETS, timeout=TIMEOUT_DURATION):
        self.channel = channel
        self.total_packets = total
        self.timeout = timeout
        self.seq_num = 0
        self.timer = None
        self.buffer = {}
        self.sent_count = 0
        self.received_count = 0
        self.pending_packet = None
        self.running = False

    def _start_timer(self):
        self.timer = threading.Timer(self.timeout, self._on_timeout)
        self.timer.start()

    def _stop_timer(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def _on_timeout(self):
        print(f"[Sender] TIMEOUT on packet {self.pending_packet.seq}. Retransmitting...")
        self.channel.transmit(self.pending_packet, self.receive)
        self._start_timer()

    def send(self):
        if self.sent_count >= self.total_packets:
            print("[Sender] All packets sent.")
            self.running = False
            return
        packet = Packet(self.seq_num, f"DATA_{self.sent_count}")
        self.pending_packet = packet
        print(f"[Sender] Sending {packet}")
        self.channel.transmit(packet, self.receive)
        self._start_timer()

    def receive(self, packet):
        if packet.type == PacketType.DATA:
            self._receiver(packet)
        elif packet.type == PacketType.ACK:
            self._ack_handler(packet)

    def _receiver(self, packet):
        print(f"[Receiver] Received {packet}")
        if packet.is_corrupt():
            print("[Receiver] Packet corrupted. Resending last ACK.")
            ack = Packet(1 - self.seq_num, packet_type=PacketType.ACK)
        elif packet.seq == self.seq_num:
            print(f"[Receiver] Accepted packet {packet.seq}")
            self.buffer[self.received_count] = packet.payload
            self.received_count += 1
            ack = Packet(packet.seq, packet_type=PacketType.ACK)
            self.seq_num = 1 - self.seq_num
        else:
            print("[Receiver] Duplicate packet received. Resending ACK.")
            ack = Packet(packet.seq, packet_type=PacketType.ACK)

        self.channel.transmit(ack, self.receive)

    def _ack_handler(self, ack):
        print(f"[Sender] ACK received: {ack}")
        if ack.is_corrupt():
            print("[Sender] ACK is corrupt. Ignoring...")
            return
        if ack.seq == self.pending_packet.seq:
            self._stop_timer()
            print(f"[Sender] ACK verified for seq {ack.seq}. Moving on.")
            self.sent_count += 1
            self.send()

    def start(self):
        self.running = True
        self.send()

    def get_data(self):
        return [self.buffer[i] for i in sorted(self.buffer)]

# Go-Back-N Protocol
class GoBackNRDT:
    def __init__(self, channel, total=TOTAL_PACKETS, window_size=WINDOW_SIZE, timeout=TIMEOUT_DURATION):
        self.channel = channel
        self.total_packets = total
        self.window_size = window_size
        self.timeout = timeout
        self.seq_num = 0
        self.ack_received = 0
        self.timer = {}
        self.buffer = {}
        self.pending_packets = []
        self.sent_count = 0
        self.received_count = 0
        self.running = False

    def _start_timer(self, seq_num):
        self.timer[seq_num] = threading.Timer(self.timeout, self._on_timeout, [seq_num])
        self.timer[seq_num].start()

    def _stop_timer(self, seq_num):
        if seq_num in self.timer:
            self.timer[seq_num].cancel()
            del self.timer[seq_num]

    def _on_timeout(self, seq_num):
        print(f"[Sender] TIMEOUT for seq {seq_num}. Retransmitting window...")
        for i in range(self.seq_num, min(self.seq_num + self.window_size, self.total_packets)):
            self.channel.transmit(self.pending_packets[i % self.window_size], self.receive)
            self._start_timer(i)

    def send(self):
        if self.sent_count >= self.total_packets:
            print("[Sender] All packets sent.")
            self.running = False
            return

        for i in range(self.window_size):
            if self.sent_count + i < self.total_packets:
                packet = Packet(self.seq_num + i, f"DATA_{self.sent_count + i}")
                self.pending_packets.append(packet)
                print(f"[Sender] Sending {packet}")
                self.channel.transmit(packet, self.receive)
                self._start_timer(self.seq_num + i)

        self.seq_num += self.window_size

    def receive(self, packet):
        if packet.type == PacketType.DATA:
            self._receiver(packet)
        elif packet.type == PacketType.ACK:
            self._ack_handler(packet)

    def _receiver(self, packet):
        print(f"[Receiver] Received {packet}")
        if packet.is_corrupt():
            print("[Receiver] Packet corrupted. Resending last ACK.")
            ack = Packet(1 - self.seq_num, packet_type=PacketType.ACK)
        elif packet.seq == self.ack_received:
            print(f"[Receiver] Accepted packet {packet.seq}")
            self.buffer[self.received_count] = packet.payload
            self.received_count += 1
            ack = Packet(packet.seq, packet_type=PacketType.ACK)
            self.ack_received += 1
        else:
            print("[Receiver] Duplicate or out-of-order packet received. Resending ACK.")
            ack = Packet(packet.seq, packet_type=PacketType.ACK)

        self.channel.transmit(ack, self.receive)

    def _ack_handler(self, ack):
        print(f"[Sender] ACK received: {ack}")
        if ack.is_corrupt():
            print("[Sender] ACK is corrupt. Ignoring...")
            return

        if ack.seq >= self.seq_num - self.window_size and ack.seq < self.seq_num:
            self._stop_timer(ack.seq)
            print(f"[Sender] ACK verified for seq {ack.seq}. Moving on.")
            self.sent_count += 1
            if self.sent_count < self.total_packets:
                self.send()

    def start(self):
        self.running = True
        self.send()

    def get_data(self):
        return [self.buffer[i] for i in sorted(self.buffer)]

# Selective Repeat Protocol
class SelectiveRepeatRDT:
    def __init__(self, channel, total=TOTAL_PACKETS, window_size=WINDOW_SIZE, timeout=TIMEOUT_DURATION):
        self.channel = channel
        self.total_packets = total
        self.window_size = window_size
        self.timeout = timeout
        self.seq_num = 0
        self.ack_received = 0
        self.timer = {}
        self.buffer = {}
        self.pending_packets = {}
        self.sent_count = 0
        self.received_count = 0
        self.running = False

    def _start_timer(self, seq_num):
        self.timer[seq_num] = threading.Timer(self.timeout, self._on_timeout, [seq_num])
        self.timer[seq_num].start()

    def _stop_timer(self, seq_num):
        if seq_num in self.timer:
            self.timer[seq_num].cancel()
            del self.timer[seq_num]

    def _on_timeout(self, seq_num):
        print(f"[Sender] TIMEOUT for seq {seq_num}. Retransmitting packet...")
        self.channel.transmit(self.pending_packets[seq_num], self.receive)
        self._start_timer(seq_num)

    def send(self):
        if self.sent_count >= self.total_packets:
            print("[Sender] All packets sent.")
            self.running = False
            return

        for i in range(self.window_size):
            if self.sent_count + i < self.total_packets:
                packet = Packet(self.seq_num + i, f"DATA_{self.sent_count + i}")
                self.pending_packets[self.seq_num + i] = packet
                print(f"[Sender] Sending {packet}")
                self.channel.transmit(packet, self.receive)
                self._start_timer(self.seq_num + i)

        self.seq_num += self.window_size

    def receive(self, packet):
        if packet.type == PacketType.DATA:
            self._receiver(packet)
        elif packet.type == PacketType.ACK:
            self._ack_handler(packet)

    def _receiver(self, packet):
        print(f"[Receiver] Received {packet}")
        if packet.is_corrupt():
            print("[Receiver] Packet corrupted. Resending last ACK.")
            ack = Packet(1 - self.seq_num, packet_type=PacketType.ACK)
        elif packet.seq == self.ack_received:
            print(f"[Receiver] Accepted packet {packet.seq}")
            self.buffer[self.received_count] = packet.payload
            self.received_count += 1
            ack = Packet(packet.seq, packet_type=PacketType.ACK)
            self.ack_received += 1
        else:
            print("[Receiver] Out-of-order packet received. Waiting for missing packet...")
            ack = Packet(packet.seq, packet_type=PacketType.ACK)

        self.channel.transmit(ack, self.receive)

    def _ack_handler(self, ack):
        print(f"[Sender] ACK received: {ack}")
        if ack.is_corrupt():
            print("[Sender] ACK is corrupt. Ignoring...")
            return

        if ack.seq in self.pending_packets:
            self._stop_timer(ack.seq)
            print(f"[Sender] ACK verified for seq {ack.seq}. Moving on.")
            self.sent_count += 1
            if self.sent_count < self.total_packets:
                self.send()

    def start(self):
        self.running = True
        self.send()

    def get_data(self):
        return [self.buffer[i] for i in sorted(self.buffer)]

# Main Function to Run the Protocols

def main():
    channel = UnreliableChannel()
    
    print("Starting Stop-and-Wait Protocol")
    sw_rdt = StopAndWaitRDT(channel)
    sw_rdt.start()
    time.sleep(1)  # Give some time for the sender to finish
    print(f"Stop-and-Wait received data: {sw_rdt.get_data()}")

    print("\nStarting Go-Back-N Protocol")
    gbn_rdt = GoBackNRDT(channel)
    gbn_rdt.start()
    time.sleep(1)  # Give some time for the sender to finish
    print(f"Go-Back-N received data: {gbn_rdt.get_data()}")

    print("\nStarting Selective Repeat Protocol")
    sr_rdt = SelectiveRepeatRDT(channel)
    sr_rdt.start()
    time.sleep(1)  # Give some time for the sender to finish
    print(f"Selective Repeat received data: {sr_rdt.get_data()}")


if __name__ == "__main__":
    main()
    

