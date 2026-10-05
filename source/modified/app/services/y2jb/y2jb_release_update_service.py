from dataclasses import replace
from pathlib import PurePosixPath
from typing import Iterable

from app.models.y2jb_backup import Y2JBBackupVariant
from app.services.releases.github_release_service import (
    GitHubReleaseDownload,
    GitHubReleaseService,
    compare_release_versions,
)


class Y2JBReleaseUpdateService:
    """Resolves the latest coherent Y2JB backup release for all firmware variants."""

    def __init__(self, github: GitHubReleaseService):
        self._github = github

    def resolve_latest(
        self,
        variants: Iterable[Y2JBBackupVariant],
    ) -> tuple[Y2JBBackupVariant, ...]:
        current = tuple(variants)
        if not current:
            return current

        parsed = []
        for variant in current:
            release = self._github.parse_download_url(variant.url)
            if release is None:
                return current
            parsed.append((variant, release))

        repositories = {(item.owner.lower(), item.repo.lower()) for _, item in parsed}
        if len(repositories) != 1:
            return current

        first = parsed[0][1]
        latest_release = self._github.latest_release(first.owner, first.repo)
        if latest_release is None:
            return current
        latest_tag = latest_release.tag

        if any(
            compare_release_versions(item.tag, latest_tag) != -1
            for _, item in parsed
        ):
            return current

        resolved = []
        for variant, release in parsed:
            asset = self._resolve_asset_from_listing(
                release,
                latest_tag,
                latest_release.assets,
            )
            if not asset:
                return current
            url = self._github.build_download_url(
                release.owner,
                release.repo,
                latest_tag,
                asset,
            )
            package_label = self._replace_version_token(
                variant.package_label,
                release.tag,
                latest_tag,
            )
            resolved.append(
                replace(
                    variant,
                    url=url,
                    filename=PurePosixPath(asset).name,
                    release_version=latest_tag,
                    package_label=package_label,
                )
            )
        return tuple(resolved)

    @classmethod
    def _resolve_asset_from_listing(
        cls,
        release: GitHubReleaseDownload,
        latest_tag: str,
        assets: Iterable[str],
    ) -> str:
        asset_list = tuple(assets)
        for candidate in cls._candidate_assets(release.asset, release.tag, latest_tag):
            if candidate in asset_list:
                return candidate

        if release.tag not in release.asset:
            return release.asset if release.asset in asset_list else ""

        prefix, suffix = release.asset.split(release.tag, 1)
        matches = [
            asset
            for asset in asset_list
            if asset.startswith(prefix) and asset.endswith(suffix)
        ]
        return matches[0] if len(matches) == 1 else ""

    @staticmethod
    def _candidate_assets(
        asset: str,
        current_tag: str,
        latest_tag: str,
    ) -> tuple[str, ...]:
        if current_tag not in asset:
            return (asset,)

        preferred = latest_tag
        if current_tag.lower().startswith("v") and not latest_tag.lower().startswith("v"):
            preferred = "v" + latest_tag
        elif not current_tag.lower().startswith("v") and latest_tag.lower().startswith("v"):
            preferred = latest_tag[1:]

        candidates = []
        for version_token in (preferred, latest_tag):
            candidate = asset.replace(current_tag, version_token, 1)
            if candidate not in candidates:
                candidates.append(candidate)
        return tuple(candidates)

    @staticmethod
    def _replace_version_token(label: str, current_tag: str, latest_tag: str) -> str:
        if current_tag and current_tag in label:
            return label.replace(current_tag, latest_tag, 1)
        return label
