from typing import Iterable

from app.models.payload import (
    PAYLOAD_ALLOWED_EXTENSIONS,
    PAYLOAD_ARCHIVE_EXTENSIONS,
    PayloadSource,
)
from app.services.releases.github_release_service import (
    GitHubReleaseAccessError,
    GitHubReleaseService,
)
from app.services.releases.release_resolution_result import ReleaseResolutionResult
from app.services.payload.payload_url_presentation import derive_payload_presentation


class PayloadReleaseUpdateService:
    """Resolve somente LATEST + Pre-release sem adivinhar assets ambíguos."""

    def __init__(self, github: GitHubReleaseService):
        self._github = github

    def resolve_latest(
        self, sources: Iterable[PayloadSource]
    ) -> tuple[PayloadSource, ...]:
        result = self.resolve_latest_with_status(sources)
        if not result.complete:
            raise GitHubReleaseAccessError("payload_release_resolution_incomplete")
        return result.items

    def resolve_latest_with_status(
        self,
        sources: Iterable[PayloadSource],
    ) -> ReleaseResolutionResult[PayloadSource]:
        current = tuple(sources)
        candidates_by_release = {}
        resolved = []
        complete = True

        for source in current:
            release = self._github.parse_download_url(source.url)
            if release is None:
                resolved.append(source)
                continue

            try:
                candidate_key = (
                    release.owner.lower(),
                    release.repo.lower(),
                    release.tag.lower(),
                )
                candidates = candidates_by_release.get(candidate_key)
                if candidates is None:
                    candidates = self._github.newer_release_candidates(
                        release.owner,
                        release.repo,
                        release.tag,
                    )
                    candidates_by_release[candidate_key] = candidates

                updated = None
                for candidate in candidates:
                    candidate_tag = candidate.tag
                    asset = self._resolve_unambiguous_asset(
                        current_asset=release.asset,
                        current_tag=release.tag,
                        latest_tag=candidate_tag,
                        assets=candidate.assets,
                    )
                    if not asset:
                        continue
                    url = self._github.build_download_url(
                        release.owner,
                        release.repo,
                        candidate_tag,
                        asset,
                    )

                    name, version = derive_payload_presentation(url)
                    updated = source.with_resolution(
                        name=name, version=version, url=url
                    )
                    break
            except GitHubReleaseAccessError:
                complete = False
                updated = None

            resolved.append(updated or source)

        return ReleaseResolutionResult(tuple(resolved), complete)

    @staticmethod
    def _resolve_unambiguous_asset(
        *,
        current_asset: str,
        current_tag: str,
        latest_tag: str,
        assets: Iterable[str],
    ) -> str:
        asset_list = tuple(str(asset) for asset in assets)
        if current_asset in asset_list:
            return current_asset

        if current_tag and current_tag in current_asset:
            prefix, suffix = current_asset.split(current_tag, 1)
            structural = [
                asset
                for asset in asset_list
                if asset.startswith(prefix) and asset.endswith(suffix)
            ]
            if len(structural) == 1:
                return structural[0]

        supported = tuple(
            ext.lower() for ext in PAYLOAD_ALLOWED_EXTENSIONS + PAYLOAD_ARCHIVE_EXTENSIONS
        )
        compatible = [asset for asset in asset_list if asset.lower().endswith(supported)]
        return compatible[0] if len(compatible) == 1 else ""
