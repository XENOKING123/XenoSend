from dataclasses import dataclass


@dataclass(frozen=True)
class DiscoveryResult:
    local_ip: str
    network_cidr: str
    port: int
    found_ip: str
    elapsed_seconds: float

    @property
    def found(self) -> bool:
        return bool(self.found_ip)
