from dataclasses import dataclass
from pathlib import Path
import sys

from app.controllers.discovery_controller import DiscoveryController
from app.controllers.payload_controller import PayloadController
from app.controllers.pkg_controller import PkgController
from app.controllers.youtube_update_controller import YouTubeUpdateController
from app.controllers.y2jb_backup_controller import Y2JBBackupController
from app.catalogs import xeno_trainer_catalog
from app.catalogs.payload_catalog import REMOTE_PAYLOAD_CATALOG_URL
from app.catalogs.pkg_catalog import KSTUFF_ASSET_NAME, REMOTE_PKG_CATALOG_URL
from app.catalogs.youtube_update_catalog import REMOTE_YOUTUBE_UPDATE_CATALOG_URL
from app.repositories.connection_settings_repository import ConnectionSettingsRepository
from app.repositories.payload_remote_catalog_repository import PayloadRemoteCatalogRepository
from app.repositories.payload_source_repository import PayloadSourceRepository
from app.repositories.pkg_remote_catalog_repository import PkgRemoteCatalogRepository
from app.repositories.youtube_update_remote_catalog_repository import YouTubeUpdateRemoteCatalogRepository
from app.repositories.youtube_update_source_repository import YouTubeUpdateSourceRepository
from app.repositories.kstuff_release_repository import KstuffReleaseRepository
from app.repositories.pkg_source_repository import PkgSourceRepository
from app.repositories.y2jb_release_repository import Y2JBReleaseRepository
from app.services.archive.zip_archive_service import ZipArchiveService
from app.services.download.download_directory_provider import DownloadDirectoryProvider
from app.services.download.http_download_service import HttpDownloadService
from app.services.download.fixed_directory_provider import FixedDirectoryProvider
from app.services.download.subdirectory_directory_provider import SubdirectoryDirectoryProvider
from app.services.download.public_download_directory_provider import PublicDownloadDirectoryProvider
from app.services.network.local_network_discovery_service import LocalNetworkDiscoveryService
from app.services.host_psm.local_installer_host_service import LocalInstallerHostService
from app.services.payload.payload_catalog_update_service import PayloadCatalogUpdateService
from app.services.payload.payload_execution_service import PayloadExecutionService
from app.services.payload.payload_file_service import PayloadFileService
from app.services.payload.payload_release_update_service import PayloadReleaseUpdateService
from app.services.payload.payload_tcp_sender import PayloadTcpSender
from app.services.platform.local_folder_opener import LocalFolderOpener
from app.services.platform.android_user_storage_access import AndroidUserStorageAccess
from app.services.platform.android_host_session_guard import AndroidHostSessionGuard
from app.services.platform.android_host_service_bridge import AndroidHostServiceBridge
from app.services.pkg.kstuff_dependency_service import KstuffDependencyService
from app.services.pkg.kstuff_release_update_service import KstuffReleaseUpdateService
from app.services.pkg.pkg_catalog_update_service import PkgCatalogUpdateService
from app.services.pkg.pkg_file_service import PkgFileService
from app.services.pkg.pkg_install_service import PkgInstallService
from app.services.pkg.pkg_installer_asset_provider import PkgInstallerAssetProvider
from app.services.pkg.pkg_installer_client import PkgInstallerClient
from app.services.pkg.pkg_release_update_service import PkgReleaseUpdateService
from app.services.releases.github_release_service import GitHubReleaseService
from app.services.storage.removable_storage_service import RemovableStorageService
from app.services.storage.tree_copy_service import TreeCopyService
from app.services.xeno.auto_loader_service import AutoLoaderService
from app.services.xeno.cheatrunner_client import CheatRunnerClient
from app.services.xeno.cheatrunner_release_service import CheatRunnerReleaseService
from app.services.xeno.cover_art_service import CoverArtService
from app.services.xeno.kstuff_elf_release_service import KstuffElfReleaseService
from app.services.youtube_update.youtube_update_catalog_update_service import YouTubeUpdateCatalogUpdateService
from app.services.youtube_update.youtube_update_file_service import YouTubeUpdateFileService
from app.services.youtube_update.youtube_update_install_service import YouTubeUpdateInstallService
from app.services.youtube_update.youtube_update_release_update_service import YouTubeUpdateReleaseUpdateService
from app.services.youtube_update.youtube_account_activation_asset_provider import YouTubeAccountActivationAssetProvider
from app.services.youtube_update.youtube_account_activation_service import YouTubeAccountActivationService
from app.services.y2jb.y2jb_backup_service import Y2JBBackupService
from app.services.y2jb.y2jb_release_update_service import Y2JBReleaseUpdateService
from kivy.utils import platform


@dataclass(frozen=True)
class DependencyContainer:
    discovery_controller: DiscoveryController
    y2jb_backup_controller: Y2JBBackupController
    payload_controller: PayloadController
    youtube_update_controller: YouTubeUpdateController
    pkg_controller: PkgController
    github_release_service: GitHubReleaseService
    host_psm_service: LocalInstallerHostService
    user_storage_access: AndroidUserStorageAccess
    trainer_catalog: object
    cheatrunner_client: CheatRunnerClient
    cover_art_service: CoverArtService
    cheatrunner_release_service: CheatRunnerReleaseService
    auto_loader_service: AutoLoaderService


def _legacy_config_candidates() -> tuple[Path, ...]:
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(
            Path(sys.executable).resolve().parent / ConnectionSettingsRepository.FILE_NAME
        )
    else:
        candidates.append(Path.cwd() / ConnectionSettingsRepository.FILE_NAME)
    return tuple(candidates)


def build_container(data_dir: Path) -> DependencyContainer:
    data_dir = Path(data_dir)

    repository = ConnectionSettingsRepository(
        data_dir=data_dir,
        legacy_candidates=_legacy_config_candidates(),
    )
    discovery_service = LocalNetworkDiscoveryService()
    discovery_controller = DiscoveryController(
        service=discovery_service,
        settings_repository=repository,
    )

    download_directory = DownloadDirectoryProvider(fallback_root=data_dir)
    public_download_directory = PublicDownloadDirectoryProvider(download_directory)
    downloader = HttpDownloadService(directory_provider=download_directory)
    github_release_service = GitHubReleaseService()

    payload_sender = PayloadTcpSender()
    payload_file_service = PayloadFileService(
        download_directory,
        local_directory_provider=public_download_directory,
    )
    payload_service = PayloadExecutionService(
        file_service=payload_file_service,
        sender=payload_sender,
    )

    payload_controller = PayloadController(
        payload_service,
        repository,
        release_updater=PayloadReleaseUpdateService(github_release_service),
        source_repository=PayloadSourceRepository(data_dir),
        catalog_updater=PayloadCatalogUpdateService(REMOTE_PAYLOAD_CATALOG_URL),
        catalog_repository=PayloadRemoteCatalogRepository(data_dir),
        folder_opener=LocalFolderOpener(),
    )

    youtube_update_file_service = YouTubeUpdateFileService(public_download_directory)
    youtube_update_service = YouTubeUpdateInstallService(
        file_service=youtube_update_file_service,
        ftpsrv_file_service=payload_file_service,
        payload_sender=payload_sender,
    )
    youtube_account_activation_service = YouTubeAccountActivationService(
        payload_sender=payload_sender,
        asset_provider=YouTubeAccountActivationAssetProvider(),
    )

    youtube_update_controller = YouTubeUpdateController(
        youtube_update_service,
        repository,
        payload_controller=payload_controller,
        account_activation_service=youtube_account_activation_service,
        catalog_updater=YouTubeUpdateCatalogUpdateService(REMOTE_YOUTUBE_UPDATE_CATALOG_URL),
        catalog_repository=YouTubeUpdateRemoteCatalogRepository(data_dir),
        release_updater=YouTubeUpdateReleaseUpdateService(github_release_service),
        source_repository=YouTubeUpdateSourceRepository(data_dir),
        folder_opener=LocalFolderOpener(),
    )

    pkg_directory = SubdirectoryDirectoryProvider(public_download_directory, "ps5_pkgs")
    pkg_downloader = HttpDownloadService(directory_provider=download_directory)
    kstuff_downloader = HttpDownloadService(
        directory_provider=FixedDirectoryProvider(data_dir / "dependencies" / "kstuff"),
    )
    kstuff_service = KstuffDependencyService(
        downloader=kstuff_downloader,
        release_updater=KstuffReleaseUpdateService(
            github_release_service,
            asset_name=KSTUFF_ASSET_NAME,
        ),
        repository=KstuffReleaseRepository(data_dir),
    )
    pkg_file_service = PkgFileService(pkg_directory, pkg_downloader)
    pkg_installer = PkgInstallerClient(
        payload_sender=payload_sender,
        asset_provider=PkgInstallerAssetProvider(),
    )
    pkg_install_service = PkgInstallService(
        file_service=pkg_file_service,
        kstuff=kstuff_service,
        payload_sender=payload_sender,
        installer=pkg_installer,
    )
    pkg_controller = PkgController(
        pkg_install_service,
        repository,
        kstuff=kstuff_service,
        release_updater=PkgReleaseUpdateService(github_release_service),
        source_repository=PkgSourceRepository(data_dir),
        catalog_updater=PkgCatalogUpdateService(REMOTE_PKG_CATALOG_URL),
        catalog_repository=PkgRemoteCatalogRepository(data_dir),
        folder_opener=LocalFolderOpener(),
    )

    y2jb_service = Y2JBBackupService(
        work_root=data_dir / "work",
        downloader=downloader,
        archive_service=ZipArchiveService(),
        removable_storage=RemovableStorageService(),
        copy_service=TreeCopyService(),
    )
    y2jb_backup_controller = Y2JBBackupController(
        y2jb_service,
        release_updater=Y2JBReleaseUpdateService(github_release_service),
        release_repository=Y2JBReleaseRepository(data_dir),
    )

    android_host_service_bridge = (
        AndroidHostServiceBridge(data_dir)
        if platform == "android"
        else None
    )
    host_psm_service = LocalInstallerHostService(
        data_dir=data_dir,
        platform_name=platform,
        local_ip_provider=LocalNetworkDiscoveryService.get_local_ipv4,
        session_guard=AndroidHostSessionGuard(platform),
        android_service_bridge=android_host_service_bridge,
    )

    cheatrunner_client = CheatRunnerClient()
    cover_art_service = CoverArtService(data_dir=data_dir)
    cheatrunner_release_service = CheatRunnerReleaseService(
        github_release_service,
        downloader,
        payload_sender,
    )
    kstuff_elf_release_service = KstuffElfReleaseService(
        github_release_service,
        downloader,
        payload_sender,
    )
    auto_loader_service = AutoLoaderService(
        kstuff_elf_release_service,
        cheatrunner_release_service,
    )

    return DependencyContainer(
        discovery_controller=discovery_controller,
        y2jb_backup_controller=y2jb_backup_controller,
        payload_controller=payload_controller,
        youtube_update_controller=youtube_update_controller,
        pkg_controller=pkg_controller,
        github_release_service=github_release_service,
        host_psm_service=host_psm_service,
        user_storage_access=AndroidUserStorageAccess(),
        trainer_catalog=xeno_trainer_catalog,
        cheatrunner_client=cheatrunner_client,
        cover_art_service=cover_art_service,
        cheatrunner_release_service=cheatrunner_release_service,
        auto_loader_service=auto_loader_service,
    )
