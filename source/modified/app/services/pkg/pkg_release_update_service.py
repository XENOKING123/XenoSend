from typing import Iterable

from app.models.pkg import PkgSource
from app.services.releases.github_release_service import (
    GitHubReleaseAccessError,
    GitHubReleaseService,
)
from app.services.releases.release_resolution_result import ReleaseResolutionResult
from app.services.pkg.pkg_url_presentation import derive_pkg_presentation


class PkgReleaseUpdateService:
    """Resolve PKGs somente por LATEST + Pre-release sem adivinhar assets."""

    def __init__(self, github: GitHubReleaseService):
        self._github = github

    def resolve_latest(self, sources: Iterable[PkgSource]) -> tuple[PkgSource, ...]:
        result = self.resolve_latest_with_status(sources)
        if not result.complete:
            raise GitHubReleaseAccessError("pkg_release_resolution_incomplete")
        return result.items

    def resolve_latest_with_status(
        self,
        sources: Iterable[PkgSource],
    ) -> ReleaseResolutionResult[PkgSource]:
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
                    asset = ""
                    if release.asset in candidate.assets:
                        asset = release.asset
                    elif release.tag and release.tag in release.asset:
                        prefix, suffix = release.asset.split(release.tag, 1)
                        structural = [
                            item
                            for item in candidate.assets
                            if item.startswith(prefix) and item.endswith(suffix)
                        ]
                        if len(structural) == 1:
                            asset = structural[0]
                    if not asset:
                        compatible = [item for item in candidate.assets if item.lower().endswith(".pkg")]
                        if len(compatible) == 1:
                            asset = compatible[0]
                    if not asset:
                        continue
                    url = self._github.build_download_url(
                        release.owner,
                        release.repo,
                        candidate_tag,
                        asset,
                    )

                    name, version = derive_pkg_presentation(url)
                    updated = source.with_resolution(
                        name=name, version=version, url=url
                    )
                    break
            except GitHubReleaseAccessError:
                complete = False
                updated = None

            resolved.append(updated or source)

        return ReleaseResolutionResult(tuple(resolved), complete)
