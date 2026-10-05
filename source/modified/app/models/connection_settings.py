from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionSettings:
    host: str = ''
    port: int = 9021
