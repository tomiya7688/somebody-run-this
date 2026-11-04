from __future__ import annotations

import socket


TARGETS = (
    ("1.1.1.1", 443),
    ("2606:4700:4700::1111", 443),
)


def main() -> int:
    for host, port in TARGETS:
        try:
            connection = socket.create_connection((host, port), timeout=0.5)
        except OSError:
            continue
        else:
            connection.close()
            raise SystemExit(
                f"network namespace unexpectedly reached {host}:{port}"
            )
    print("no-egress network namespace probe passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
