import socket
import threading
import unittest

from vpn_splitter.bridge import relay


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.vpn, self.vpn_peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.tun, self.tun_peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.control, self.control_peer = socket.socketpair()
        for sock in (
            self.vpn,
            self.vpn_peer,
            self.tun,
            self.tun_peer,
            self.control,
            self.control_peer,
        ):
            sock.settimeout(1)
            self.addCleanup(sock.close)
        self.worker = threading.Thread(
            target=relay, args=(self.vpn.fileno(), self.tun.fileno(), self.control)
        )
        self.worker.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.control_peer.close()
        self.worker.join(timeout=2)
        self.assertFalse(self.worker.is_alive())

    def test_preserves_packet_boundaries_in_both_directions(self):
        packets = [b"\x45" + b"a" * 39, b"\x45" + b"b" * 1199]
        for packet in packets:
            self.vpn_peer.send(packet)
        for packet in packets:
            self.assertEqual(self.tun_peer.recv(65535), packet)
        for packet in reversed(packets):
            self.tun_peer.send(packet)
            self.assertEqual(self.vpn_peer.recv(65535), packet)

    def test_ipv6_packets_are_never_forwarded(self):
        self.vpn_peer.send(b"\x60" + bytes(39))
        self.vpn_peer.send(b"\x45" + bytes(19))
        self.assertEqual(self.tun_peer.recv(65535), b"\x45" + bytes(19))

    def test_daemon_disconnect_stops_bridge_without_forwarding_further_packets(self):
        self.stop()
        self.vpn_peer.send(b"\x45" + bytes(19))
        self.tun_peer.settimeout(0.05)
        with self.assertRaises(socket.timeout):
            self.tun_peer.recv(65535)
