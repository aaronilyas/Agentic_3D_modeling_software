"""Stdio ↔ TCP byte relay onto an existing Application MCP listener.

This process never constructs an Application. It authenticates with the
token issued by the live listener and then copies bytes in both directions.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading


def _copy_file_to_socket(src_fd: int, sock: socket.socket, stop: threading.Event) -> None:
    try:
        while not stop.is_set():
            data = os.read(src_fd, 65536)
            if not data:
                try:
                    sock.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                return
            sock.sendall(data)
    except OSError:
        return
    finally:
        stop.set()


def _copy_socket_to_file(sock: socket.socket, dst_fd: int, stop: threading.Event) -> None:
    try:
        while not stop.is_set():
            data = sock.recv(65536)
            if not data:
                return
            os.write(dst_fd, data)
    except OSError:
        return
    finally:
        stop.set()


def relay(host: str, port: int, token: str) -> int:
    sock = socket.create_connection((host, port), timeout=10)
    try:
        if token:
            sock.sendall(token.encode("utf-8") + b"\n")
        stop = threading.Event()
        stdin_fd = sys.stdin.fileno()
        stdout_fd = sys.stdout.fileno()
        inbound = threading.Thread(
            target=_copy_file_to_socket,
            args=(stdin_fd, sock, stop),
            name="jewelry-mcp-proxy-in",
            daemon=True,
        )
        outbound = threading.Thread(
            target=_copy_socket_to_file,
            args=(sock, stdout_fd, stop),
            name="jewelry-mcp-proxy-out",
            daemon=True,
        )
        inbound.start()
        outbound.start()
        while not stop.wait(0.1):
            if not inbound.is_alive() and not outbound.is_alive():
                break
        return 0
    finally:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Relay stdio MCP onto a jewelry TCP listener")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", default=os.environ.get("JEWELRY_MCP_TOKEN", ""))
    args = parser.parse_args(argv)
    try:
        return relay(args.host, args.port, args.token)
    except OSError as exc:
        print(f"jewelry.mcp_proxy: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
