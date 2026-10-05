import json
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar
from urllib.parse import unquote

try:
    import requests
except ImportError:
    requests = None


_RELEASE_DOWNLOAD_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/releases/download/(?P<tag>[^/]+)/(?P<asset>.+)$",
    re.IGNORECASE,
)

_CACHE_VALUE = TypeVar("_CACHE_VALUE")


@dataclass(frozen=True)
class GitHubReleaseDownload:
    owner: str
    repo: str
    tag: str
    asset: str


@dataclass(frozen=True)
class GitHubReleaseCandidate:
    tag: str
    prerelease: bool
    assets: tuple[str, ...] = ()


class GitHubReleaseAccessError(RuntimeError):
    """A consulta remota não terminou e, portanto, não pode ser cacheada como sucesso."""


class GitHubReleaseCycleUnavailable(GitHubReleaseAccessError):
    """O acesso remoto inteiro está indisponível durante o ciclo atual."""


_VERSION_HEAD_RE = re.compile(r"^[vV]?(?P<core>\d+(?:[._]\d+)*)(?P<suffix>.*)$")
_PRERELEASE_LONG_RE = re.compile(
    r"(?:^|[-_.])(?P<stage>alpha|beta|rc)(?P<number>\d*)(?:(?:[-_.])?fix(?P<fix_number>\d+))?(?=$|[-_.])",
    re.IGNORECASE,
)
_PRERELEASE_SHORT_RE = re.compile(
    r"(?:^|[-_.])(?P<stage>a|b)(?P<number>\d+)(?:(?:[-_.])?fix(?P<fix_number>\d+))?(?=$|[-_.])",
    re.IGNORECASE,
)


def _numeric_core_and_stage(tag: str):
    value = str(tag or "").strip()
    match = _VERSION_HEAD_RE.fullmatch(value)
    if not match:
        return None
    core = tuple(int(part) for part in re.split("[._]", match.group("core")))
    suffix = str(match.group("suffix") or "").strip()
    if not suffix:
        return core, (3, 0, 0)
    pre = _PRERELEASE_LONG_RE.search(suffix) or _PRERELEASE_SHORT_RE.search(suffix)
    if pre:
        rank = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2}[pre.group("stage").lower()]
        return core, (
            rank,
            int(pre.group("number") or 0),
            int(pre.group("fix_number") or 0),
        )
    return core, None


def compare_release_versions(left: str, right: str):
    """Compara tags de forma conservadora; None significa que não há prova de ordem."""
    parsed_left = _numeric_core_and_stage(left)
    parsed_right = _numeric_core_and_stage(right)
    if parsed_left is None or parsed_right is None:
        return None
    left_core, left_stage = parsed_left
    right_core, right_stage = parsed_right
    width = max(len(left_core), len(right_core))
    left_padded = left_core + (0,) * (width - len(left_core))
    right_padded = right_core + (0,) * (width - len(right_core))
    if left_padded < right_padded:
        return -1
    if left_padded > right_padded:
        return 1
    if left_stage is None or right_stage is None:
        return 0 if str(left).strip().lower() == str(right).strip().lower() else None
    if left_stage < right_stage:
        return -1
    if left_stage > right_stage:
        return 1
    return 0


class GitHubReleaseService:
    """Cliente de releases com um índice único para LATEST + Pre-release + assets."""

    INDEX_TIMEOUT = (3.05, 10)
    NOT_FOUND = frozenset({404, 410})

    def __init__(self, session: Optional[Any] = None):
        if session is None:
            if requests is None:
                raise RuntimeError("github_release_requests_unavailable")
            session = requests.Session()
        self._session = session
        self._cache_condition = threading.Condition()
        self._success_cache = {}
        self._failure_cache = {}
        self._in_flight = {}
        self._refresh_cycle = 0
        self._cycle_failure = None
        self._request_lock = threading.Lock()
        try:
            self._session.headers.update({"User-Agent": "PS5-Send-PKG-Payload"})
        except Exception:
            pass

    def begin_refresh_cycle(self) -> None:
        """Inicia uma verificação explícita nova.

        Sucessos e falhas continuam compartilhados entre todos os módulos dentro
        do mesmo ciclo. Nenhum resultado de LATEST ou Pre-release atravessa uma
        nova abertura do aplicativo, evitando esconder releases publicadas após
        a verificação anterior.
        """
        with self._cache_condition:
            self._refresh_cycle += 1
            self._cache_condition.notify_all()

    def begin_retry_cycle(self) -> None:
        """Compatibilidade interna: uma repetição também constitui novo ciclo."""
        self.begin_refresh_cycle()

    @staticmethod
    def parse_download_url(url: str) -> Optional[GitHubReleaseDownload]:
        match = _RELEASE_DOWNLOAD_RE.match((url or "").strip())
        if not match:
            return None
        return GitHubReleaseDownload(
            owner=match.group("owner"),
            repo=match.group("repo"),
            tag=unquote(match.group("tag")).strip(),
            asset=unquote(match.group("asset")).strip(),
        )

    def release_index(
        self,
        owner: str,
        repo: str,
    ) -> tuple[GitHubReleaseCandidate, ...]:
        """Consulta uma vez a origem e preserva a ordem entregue por ela.

        Somente releases publicadas entram no índice. Drafts são descartados e
        cada asset só é aceito quando seu endereço confirma repositório, tag e
        nome. Assim a mesma resposta comprova canal e arquivo, sem HEADs extras.
        """
        owner, repo = self._validate_repository(owner, repo)
        key = ("release-index", owner.lower(), repo.lower())
        return self._cached_completed_query(
            key,
            lambda: self._load_release_index(owner, repo),
        )

    def _load_release_index(
        self,
        owner: str,
        repo: str,
    ) -> tuple[GitHubReleaseCandidate, ...]:
        url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=100"
        try:
            response = self._session.get(url, timeout=self.INDEX_TIMEOUT)
        except Exception as exc:
            raise GitHubReleaseCycleUnavailable("github_release_index_unavailable") from exc

        status = self._status_code(response)
        if status in self.NOT_FOUND:
            return ()
        if not 200 <= status < 300:
            self._raise_access_error(status, "github_release_index_unavailable")

        try:
            try:
                payload = response.json()
            except Exception:
                payload = json.loads(str(getattr(response, "text", "") or ""))
        except Exception as exc:
            raise GitHubReleaseAccessError("github_release_index_unavailable") from exc

        if not isinstance(payload, list):
            raise GitHubReleaseAccessError("github_release_index_unavailable")

        releases = []
        seen = set()
        for raw_release in payload:
            if not isinstance(raw_release, dict) or bool(raw_release.get("draft")):
                continue
            tag = str(raw_release.get("tag_name") or "").strip()
            prerelease = bool(raw_release.get("prerelease"))
            identity = (tag.lower(), prerelease)
            if not tag or identity in seen:
                continue
            seen.add(identity)
            releases.append(
                GitHubReleaseCandidate(
                    tag=tag,
                    prerelease=prerelease,
                    assets=self._validated_asset_names(
                        raw_release.get("assets"),
                        owner,
                        repo,
                        tag,
                    ),
                )
            )
        return tuple(releases)

    @classmethod
    def _validated_asset_names(
        cls,
        raw_assets: object,
        owner: str,
        repo: str,
        tag: str,
    ) -> tuple[str, ...]:
        if not isinstance(raw_assets, list):
            return ()
        result = []
        seen = set()
        for raw_asset in raw_assets:
            if not isinstance(raw_asset, dict):
                continue
            name = str(raw_asset.get("name") or "").strip()
            url = str(raw_asset.get("browser_download_url") or "").strip()
            parsed = cls.parse_download_url(url)
            if (
                not name
                or parsed is None
                or parsed.owner.lower() != owner.lower()
                or parsed.repo.lower() != repo.lower()
                or parsed.tag.lower() != tag.lower()
                or parsed.asset != name
                or name in seen
            ):
                continue
            seen.add(name)
            result.append(name)
        return tuple(result)

    @staticmethod
    def _validate_repository(owner: str, repo: str) -> tuple[str, str]:
        owner = str(owner or "").strip()
        repo = str(repo or "").strip()
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
        if not owner or not repo or any(char not in allowed for char in owner + repo):
            raise GitHubReleaseAccessError("github_repository_invalid")
        return owner, repo

    def latest_release(self, owner: str, repo: str) -> Optional[GitHubReleaseCandidate]:
        return next(
            (release for release in self.release_index(owner, repo) if not release.prerelease),
            None,
        )

    def latest_tag(self, owner: str, repo: str) -> str:
        release = self.latest_release(owner, repo)
        return release.tag if release is not None else ""

    def prerelease_tags(self, owner: str, repo: str) -> tuple[str, ...]:
        return tuple(
            release.tag for release in self.release_index(owner, repo) if release.prerelease
        )

    def release_candidates(
        self,
        owner: str,
        repo: str,
    ) -> tuple[GitHubReleaseCandidate, ...]:
        """Retorna somente a primeira estável e a primeira Pre-release do índice."""
        latest = None
        prerelease = None
        for release in self.release_index(owner, repo):
            if release.prerelease:
                if prerelease is None:
                    prerelease = release
            elif latest is None:
                latest = release
            if latest is not None and prerelease is not None:
                break
        return tuple(item for item in (latest, prerelease) if item is not None)

    @staticmethod
    def _newest_proven_prerelease(
        releases: tuple[GitHubReleaseCandidate, ...],
        current_tag: str,
    ) -> Optional[GitHubReleaseCandidate]:
        """Seleciona a única Pre-release superior que seja maior que as demais.

        A filtragem pela versão atual acontece antes da escolha. Desse modo,
        uma Pre-release histórica que apareça primeiro no índice não esconde uma
        versão mais nova. Quando a ordem entre as candidatas não pode ser
        comprovada semanticamente, o canal falha fechado.
        """
        eligible = tuple(
            release
            for release in releases
            if release.prerelease
            and compare_release_versions(current_tag, release.tag) == -1
        )

        winners = []
        for candidate in eligible:
            if not all(
                other is candidate
                or compare_release_versions(other.tag, candidate.tag) in (-1, 0)
                for other in eligible
            ):
                continue
            winners.append(candidate)
        return winners[0] if len(winners) == 1 else None

    def newer_release_candidates(
        self,
        owner: str,
        repo: str,
        current_tag: str,
    ) -> tuple[GitHubReleaseCandidate, ...]:
        """Retorna LATEST/Pre-release comprovadamente superiores à tag atual.

        Quando LATEST e Pre-release são ambos superiores, a maior versão
        comprovável vem primeiro. Em empate/ordem ambígua, LATEST tem prioridade
        determinística; a Pre-release continua como fallback de asset.
        """
        releases = self.release_index(owner, repo)
        latest = next((release for release in releases if not release.prerelease), None)
        prerelease = self._newest_proven_prerelease(releases, current_tag)
        eligible = [
            candidate
            for candidate in (latest, prerelease)
            if candidate is not None
            and compare_release_versions(current_tag, candidate.tag) == -1
        ]

        if len(eligible) < 2:
            return tuple(eligible)

        first, second = eligible[0], eligible[1]
        comparison = compare_release_versions(first.tag, second.tag)
        if comparison == -1:
            return second, first
        if comparison in (0, 1):
            return first, second

        eligible.sort(key=lambda item: item.prerelease)
        return tuple(eligible)

    def _cached_completed_query(
        self,
        key: tuple,
        loader: Callable[[], _CACHE_VALUE],
    ) -> _CACHE_VALUE:
        """Single-flight: compartilha sucessos e falhas somente no ciclo atual."""
        while True:
            with self._cache_condition:
                cycle = self._refresh_cycle
                cached = self._success_cache.get(key)
                if cached is not None:
                    cached_cycle, cached_value = cached
                    if cached_cycle == cycle:
                        return cached_value
                    self._success_cache.pop(key, None)
                blocked = self._cycle_failure
                if blocked is not None and blocked[0] == cycle:
                    raise GitHubReleaseCycleUnavailable(blocked[1])
                failed = self._failure_cache.get(key)
                if failed is not None and failed[0] == cycle:
                    raise GitHubReleaseAccessError(failed[1])
                if key not in self._in_flight:
                    self._in_flight[key] = cycle
                    attempt_cycle = cycle
                    break
                self._cache_condition.wait()

        try:
            with self._request_lock:
                with self._cache_condition:
                    blocked = self._cycle_failure
                    if blocked is not None and blocked[0] == attempt_cycle:
                        raise GitHubReleaseCycleUnavailable(blocked[1])
                try:
                    value = loader()
                except GitHubReleaseCycleUnavailable as exc:
                    message = str(exc).strip() or "github_release_cycle_unavailable"
                    with self._cache_condition:
                        self._cycle_failure = (attempt_cycle, message)
                    raise
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, GitHubReleaseAccessError)
                else GitHubReleaseAccessError("github_release_query_unavailable")
            )
            message = str(error).strip() or "github_release_query_unavailable"
            with self._cache_condition:
                self._failure_cache[key] = (attempt_cycle, message)
                self._in_flight.pop(key, None)
                self._cache_condition.notify_all()
            if error is exc:
                raise
            raise error from exc

        with self._cache_condition:
            self._success_cache[key] = (attempt_cycle, value)
            self._failure_cache.pop(key, None)
            self._in_flight.pop(key, None)
            self._cache_condition.notify_all()
        return value

    @staticmethod
    def _raise_access_error(status: int, message: str) -> None:
        if status in {401, 403, 408, 425, 429} or status >= 500 or status <= 0:
            raise GitHubReleaseCycleUnavailable(message)
        raise GitHubReleaseAccessError(message)

    @staticmethod
    def build_download_url(owner: str, repo: str, tag: str, asset: str) -> str:
        return f"https://github.com/{owner}/{repo}/releases/download/{tag}/{asset}"

    @staticmethod
    def _status_code(response) -> int:
        try:
            return int(getattr(response, "status_code", 0) or 0)
        except (TypeError, ValueError):
            return 0
