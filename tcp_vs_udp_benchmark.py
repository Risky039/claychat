"""
tcp_vs_udp_benchmark.py
Standalone test harness for Compulsory Practical TCP vs. UDP Comparison.
Sends 100 numbered messages under Baseline and Simulated Loss conditions.
"""

import socket
import threading
import time
import json
import statistics
import random

NUM_MESSAGES = 100
PAYLOAD_SIZE = 64
LOCAL_HOST = "127.0.0.1"
TCP_BENCH_PORT = 9993
UDP_BENCH_PORT = 9994

# --- UDP TEST ---
def run_udp_benchmark(drop_rate=0.0):
    received = []
    stop_event = threading.Event()
    
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_sock.bind((LOCAL_HOST, UDP_BENCH_PORT))
    server_sock.settimeout(0.2)
    
    def server_loop():
        while not stop_event.is_set():
            try:
                data, addr = server_sock.recvfrom(4096)
                if drop_rate > 0 and random.random() < drop_rate:
                    continue  # simulated drop
                msg = json.loads(data.decode("utf-8"))
                msg["recv_time"] = time.perf_counter()
                received.append(msg)
                server_sock.sendto(b"ACK", addr)
            except socket.timeout:
                continue
            except Exception:
                break
        server_sock.close()

    t = threading.Thread(target=server_loop, daemon=True)
    t.start()
    time.sleep(0.05)

    client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_sock.settimeout(0.04)  # 40ms timeout per packet
    latencies = []

    for seq in range(NUM_MESSAGES):
        payload = {"seq": seq, "ts": time.perf_counter(), "data": "X" * PAYLOAD_SIZE}
        t0 = time.perf_counter()
        client_sock.sendto(json.dumps(payload).encode("utf-8"), (LOCAL_HOST, UDP_BENCH_PORT))
        try:
            client_sock.recvfrom(1024)
            latencies.append((time.perf_counter() - t0) * 1000)
        except socket.timeout:
            pass  # dropped or unacknowledged
        time.sleep(0.002)

    time.sleep(0.1)
    stop_event.set()
    client_sock.close()
    t.join(timeout=0.5)

    rec_seqs = [m["seq"] for m in received]
    rec_count = len(rec_seqs)
    loss_pct = ((NUM_MESSAGES - rec_count) / NUM_MESSAGES) * 100
    
    inversions = 0
    for i in range(1, len(rec_seqs)):
        if rec_seqs[i] < rec_seqs[i-1]:
            inversions += 1

    return {
        "protocol": "UDP",
        "drop_rate_target": drop_rate,
        "sent": NUM_MESSAGES,
        "received": rec_count,
        "loss_pct": round(loss_pct, 2),
        "inversions": inversions,
        "lat_min_ms": round(min(latencies), 3) if latencies else 0.0,
        "lat_avg_ms": round(statistics.mean(latencies), 3) if latencies else 0.0,
        "lat_max_ms": round(max(latencies), 3) if latencies else 0.0,
    }

# --- TCP TEST ---
def run_tcp_benchmark():
    received = []
    stop_event = threading.Event()
    
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((LOCAL_HOST, TCP_BENCH_PORT))
    server_sock.listen(1)
    
    def server_loop():
        server_sock.settimeout(1.0)
        try:
            conn, _ = server_sock.accept()
            conn.settimeout(1.0)
            buf = b""
            while not stop_event.is_set():
                try:
                    data = conn.recv(4096)
                    if not data:
                        break
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line:
                            msg = json.loads(line.decode("utf-8"))
                            msg["recv_time"] = time.perf_counter()
                            received.append(msg)
                            conn.sendall(b"ACK\n")
                except socket.timeout:
                    continue
            conn.close()
        except Exception:
            pass
        finally:
            server_sock.close()

    t = threading.Thread(target=server_loop, daemon=True)
    t.start()
    time.sleep(0.05)

    client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_sock.connect((LOCAL_HOST, TCP_BENCH_PORT))
    client_sock.settimeout(1.0)
    latencies = []

    for seq in range(NUM_MESSAGES):
        payload = {"seq": seq, "ts": time.perf_counter(), "data": "X" * PAYLOAD_SIZE}
        raw = json.dumps(payload).encode("utf-8") + b"\n"
        t0 = time.perf_counter()
        client_sock.sendall(raw)
        
        # read ACK\n
        ack_buf = b""
        while b"\n" not in ack_buf:
            chunk = client_sock.recv(16)
            if not chunk:
                break
            ack_buf += chunk
        latencies.append((time.perf_counter() - t0) * 1000)
        time.sleep(0.002)

    time.sleep(0.1)
    stop_event.set()
    client_sock.close()
    t.join(timeout=0.5)

    rec_seqs = [m["seq"] for m in received]
    rec_count = len(rec_seqs)
    loss_pct = ((NUM_MESSAGES - rec_count) / NUM_MESSAGES) * 100
    
    inversions = 0
    for i in range(1, len(rec_seqs)):
        if rec_seqs[i] < rec_seqs[i-1]:
            inversions += 1

    return {
        "protocol": "TCP",
        "drop_rate_target": 0.0,
        "sent": NUM_MESSAGES,
        "received": rec_count,
        "loss_pct": round(loss_pct, 2),
        "inversions": inversions,
        "lat_min_ms": round(min(latencies), 3) if latencies else 0.0,
        "lat_avg_ms": round(statistics.mean(latencies), 3) if latencies else 0.0,
        "lat_max_ms": round(max(latencies), 3) if latencies else 0.0,
    }

if __name__ == "__main__":
    print("Starting TCP Baseline...")
    tcp_base = run_tcp_benchmark()
    print("TCP Baseline Results:", tcp_base, flush=True)

    print("Starting UDP Baseline...")
    udp_base = run_udp_benchmark(drop_rate=0.0)
    print("UDP Baseline Results:", udp_base, flush=True)

    print("Starting UDP Controlled Loss (15%)...")
    udp_loss = run_udp_benchmark(drop_rate=0.15)
    print("UDP Loss Results:", udp_loss, flush=True)

    results = {
        "tcp_baseline": tcp_base,
        "udp_baseline": udp_base,
        "udp_controlled_loss_15pct": udp_loss
    }
    with open("evidence/tcp_udp_comparison_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Saved evidence/tcp_udp_comparison_results.json successfully!", flush=True)
