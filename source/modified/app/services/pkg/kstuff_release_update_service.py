from app.services.releases.github_release_service import GitHubReleaseService, compare_release_versions


class KstuffReleaseUpdateService:
    """Resolves only the exact kstuff.elf asset from the latest release."""

    def __init__(self, github: GitHubReleaseService, *, asset_name: str):
        self._github = github
        self._asset_name = str(asset_name).strip()

    def resolve_latest(self, current_url: str) -> str:
        release = self._github.parse_download_url(current_url)
        if release is None:
            return current_url

        latest_release = self._github.latest_release(release.owner, release.repo)
        if latest_release is None:
            return current_url
        latest_tag = latest_release.tag
        if compare_release_versions(release.tag, latest_tag) != -1:
            return current_url

        exact = [asset for asset in latest_release.assets if asset == self._asset_name]
        if len(exact) != 1:
            return current_url
        return self._github.build_download_url(
            release.owner,
            release.repo,
            latest_tag,
            exact[0],
        )
