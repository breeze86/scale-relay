"""Small RC4 implementation for Xiaomi Cloud encrypted API calls."""

from __future__ import annotations


def rc4_crypt(key: bytes, payload: bytes, drop: int = 1024) -> bytes:
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) % 256
        state[i], state[j] = state[j], state[i]

    i = 0
    j = 0
    output = bytearray()
    for index in range(drop + len(payload)):
        i = (i + 1) % 256
        j = (j + state[i]) % 256
        state[i], state[j] = state[j], state[i]
        stream_byte = state[(state[i] + state[j]) % 256]
        if index >= drop:
            output.append(payload[index - drop] ^ stream_byte)
    return bytes(output)
