from app.models.connection_settings import ConnectionSettings
from app.models.discovery_result import DiscoveryResult
from app.repositories.connection_settings_repository import ConnectionSettingsRepository
from app.services.network.local_network_discovery_service import LocalNetworkDiscoveryService


class InvalidPortError(ValueError):
    pass


class DiscoveryController:
    def __init__(
        self,
        service: LocalNetworkDiscoveryService,
        settings_repository: ConnectionSettingsRepository,
    ) -> None:
        self._service = service
        self._settings_repository = settings_repository

    def load_last_connection(self) -> ConnectionSettings:
        return self._settings_repository.load()

    @staticmethod
    def parse_port(raw_port: str) -> int:
        value = str(raw_port or "").strip() or "9021"
        try:
            port = int(value)
        except ValueError as exc:
            raise InvalidPortError("not_numeric") from exc
        if not 1 <= port <= 65535:
            raise InvalidPortError("out_of_range")
        return port

    def discover(self, raw_port: str, is_android: bool) -> DiscoveryResult:
        port = self.parse_port(raw_port)
        result = self._service.discover(port=port, is_android=is_android)
        if result.found:
            self._settings_repository.save(
                ConnectionSettings(host=result.found_ip, port=result.port)
            )
        return result
