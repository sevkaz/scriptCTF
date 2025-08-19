#!/usr/bin/env python3
# oracle_bs.py
# Usage:
#  - Remote: python3 oracle_bs.py --host <host> --port <port>
#  - Local:  python3 oracle_bs.py --bin ./challenge_binary


import socket
import sys
import argparse
import subprocess
import time
import re

PROMPT_TIMEOUT = 5.0

def recv_all(sock, timeout=PROMPT_TIMEOUT):
    sock.settimeout(timeout)
    data = b""
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            # if likely end of prompt, break early (heuristic)
            if b"Choice:" in data or b"Enter a number" in data or b"Enter secret" in data:
                break
    except socket.timeout:
        pass
    return data.decode(errors="ignore")

def interact_remote(host, port):
    s = socket.create_connection((host, port), timeout=10)
    return s

def send_line(sock, line):
    if isinstance(sock, socket.socket):
        sock.sendall((line + "\n").encode())
    else:
        # file-like (process)
        sock.stdin.write((line + "\n").encode())
        sock.stdin.flush()

def recv_process(proc, timeout=PROMPT_TIMEOUT):
    out = b""
    # read non-blocking style
    end = time.time() + timeout
    while time.time() < end:
        chunk = proc.stdout.read(1)
        if not chunk:
            break
        out += chunk
        # heuristics: break when prompt words seen
        if b"Choice:" in out or b"Enter a number" in out or b"Enter secret" in out:
            break
    return out.decode(errors="ignore")

def start_local(binpath):
    proc = subprocess.Popen([binpath], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc

def parse_int_from_text(txt):
    # find first integer in output (the oracle prints an integer on its own line)
    m = re.search(r"(-?\d+)", txt)
    if m:
        return int(m.group(1))
    return None

def get_oracle_response_conn(conn, is_socket=True):
    # read until prompt
    if is_socket:
        txt = recv_all(conn)
    else:
        txt = recv_process(conn)
    # try to parse an integer in returned text
    val = parse_int_from_text(txt)
    return txt, val

def menu_and_query(conn, num, is_socket=True):
    # send choice 1, send number, parse returned integer (int(secret/num))
    # read initial menu
    if is_socket:
        _ = recv_all(conn)
        send_line(conn, "1")
        _ = recv_all(conn)
        send_line(conn, str(num))
        out = recv_all(conn)
    else:
        _ = recv_process(conn)
        send_line(conn, "1")
        _ = recv_process(conn)
        send_line(conn, str(num))
        out = recv_process(conn)
    # parse integer from out
    v = parse_int_from_text(out)
    return out, v

def send_guess(conn, guess, is_socket=True):
    if is_socket:
        _ = recv_all(conn)
        send_line(conn, "2")
        _ = recv_all(conn)
        send_line(conn, str(guess))
        out = recv_all(conn, timeout=2.0)
    else:
        _ = recv_process(conn)
        send_line(conn, "2")
        _ = recv_process(conn)
        send_line(conn, str(guess))
        out = recv_process(conn, timeout=2.0)
    return out

def binary_search_secret(conn, is_socket=True, verbose=True):
    L = 1 << 127
    R = (1 << 128) - 1
    steps = 0
    while L < R:
        mid = (L + R + 1) // 2  # choose upper mid to avoid infinite loop
        # ensure mid has 128-bit (it will by construction)
        if mid.bit_length() != 128:
            # force to minimal 128-bit
            mid = max(mid, 1 << 127)
        if verbose:
            print(f"[+] Query {steps}: testing num = {mid} (range [{L}, {R}])")
        out, v = menu_and_query(conn, mid, is_socket=is_socket)
        steps += 1
        if v is None:
            print("[!] Couldn't parse oracle response; stopping. Raw output:")
            print(out)
            return None
        # v == 1 means mid <= secret
        if v >= 1:
            # num <= secret => secret in [mid, R]
            L = mid
        else:
            # num > secret => secret in [L, mid-1]
            R = mid - 1
        # safety
        if steps > 2000:
            print("[!] Too many steps, aborting.")
            return None
    print(f"[+] Found candidate secret = {L} in {steps} queries")
    return L

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", help="remote host")
    parser.add_argument("--port", type=int, help="remote port")
    parser.add_argument("--bin", help="path to local binary")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.host and args.port:
        print("[*] Connecting remote...")
        s = interact_remote(args.host, args.port)
        try:
            secret = binary_search_secret(s, is_socket=True, verbose=args.verbose)
            if secret is None:
                print("[-] Failed to recover secret.")
                return
            print("[*] Sending guess...")
            out = send_guess(s, secret, is_socket=True)
            print(out)
        finally:
            s.close()
    elif args.bin:
        print("[*] Starting local binary...")
        p = start_local(args.bin)
        secret = binary_search_secret(p, is_socket=False, verbose=args.verbose)
        if secret is None:
            print("[-] Failed.")
            return
        print("[*] Sending guess to local process...")
        out = send_guess(p, secret, is_socket=False)
        print(out)
        p.terminate()
    else:
        print("Provide --host/--port or --bin")
        sys.exit(1)

if __name__ == "__main__":
    main()
