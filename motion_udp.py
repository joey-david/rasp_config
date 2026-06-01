"""Small UDP motion receiver for latest-wins low-latency control."""
import json
import os
import socket
import threading


UDP_MOTION_PORT = int(os.environ.get("MOTION_UDP_PORT", "8766"))


class UDPMotionServer:
    def __init__(self, robot, host="0.0.0.0", port=UDP_MOTION_PORT):
        self.robot = robot
        self.addr = (host, port)
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(self.addr)
        self._sock.settimeout(0.2)
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._sock.close()

    def _run(self):
        while not self._stop.is_set():
            try:
                data, _ = self._sock.recvfrom(1024)
                msg = json.loads(data.decode("utf-8"))
                seq = msg.get("seq")
                if msg.get("stop"):
                    self.robot.stop(seq=seq, source="udp")
                else:
                    self.robot.set_velocity(msg.get("linear", 0), msg.get("angular", 0), seq=seq, source="udp")
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as e:
                print(f"[motion-udp] {e}", flush=True)
