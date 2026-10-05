import threading
import webbrowser

from kivy.clock import Clock
from kivy.properties import BooleanProperty, ListProperty, StringProperty
from kivy.utils import get_color_from_hex, platform
from kivymd.uix.screen import MDScreen

from app.i18n import toast
from app.controllers.discovery_controller import InvalidPortError
from app.controllers.payload_controller import InvalidPayloadConnectionError
from app.controllers.pkg_controller import InvalidPkgConnectionError
from app.controllers.youtube_update_controller import InvalidYouTubeUpdateConnectionError
from app.services.platform.local_folder_opener import LocalFolderOpenError
from app.services.update.update_check_service import UpdateCheckService
from app.models.payload import PayloadMenuEntry, PayloadProgress
from app.models.pkg import PkgMenuEntry, PkgProgress
from app.models.youtube_update import YouTubeUpdateMenuEntry, YouTubeUpdateProgress
from app.models.y2jb_backup import Y2JBBackupProgress
from app.services.network.local_network_discovery_service import LocalIPv4UnavailableError
from app.services.y2jb.y2jb_backup_service import RemovableUsbNotFoundError
from app.ui.widgets.payload_selector import PayloadSelectorModal
from app.ui.widgets.pkg_selector import PkgSelectorModal
from app.ui.widgets.trainer_browser import TrainerBrowserModal
from app.ui.widgets.youtube_update_selector import YouTubeUpdateSelectorModal


class MainScreen(MDScreen):
    host_text = StringProperty("")
    port_text = StringProperty("9021")
    status_text = StringProperty("Pronto para buscar o PS5 na rede local.")
    busy = BooleanProperty(False)
    status_color = ListProperty(get_color_from_hex("#A7ADB7"))

    backup_busy = BooleanProperty(False)
    backup_status_text = StringProperty("Pronto para preparar o USB.")
    backup_version_text = StringProperty("")
    backup_status_color = ListProperty(get_color_from_hex("#A7ADB7"))

    payload_busy = BooleanProperty(False)
    payload_status_text = StringProperty("Pronto para selecionar um payload.")
    payload_status_color = ListProperty(get_color_from_hex("#A7ADB7"))

    youtube_update_busy = BooleanProperty(False)
    youtube_update_status_text = StringProperty("Pronto para atualizar o YouTube.")
    youtube_update_status_color = ListProperty(get_color_from_hex("#A7ADB7"))

    pkg_busy = BooleanProperty(False)
    pkg_status_text = StringProperty("Pronto para selecionar um PKG.")
    pkg_status_color = ListProperty(get_color_from_hex("#A7ADB7"))

    host_psm_busy = BooleanProperty(False)
    host_psm_running = BooleanProperty(False)
    host_psm_connected = BooleanProperty(False)
    host_psm_status_text = StringProperty("Parado • WebKit + ReLapse + Instalador")
    host_psm_status_color = ListProperty(get_color_from_hex("#A7ADB7"))

    update_available = BooleanProperty(False)
    update_banner_text = StringProperty("")
    update_url = StringProperty("")
    update_dismissed = BooleanProperty(False)
    update_check_status_text = StringProperty("")

    trainer_busy = BooleanProperty(False)
    trainer_status_text = StringProperty("Pronto para selecionar um trainer.")
    trainer_status_color = ListProperty(get_color_from_hex("#A7ADB7"))

    def __init__(self, container, **kwargs):
        self._container = container
        self._payload_menu = None
        self._youtube_update_menu = None
        self._pkg_menu = None
        self._trainer_browser_modal = None
        self._pending_user_storage_menu = None
        self._host_psm_permission_pending = False
        self._remote_refresh_lock = threading.Lock()
        self._remote_refresh_active = set()
        self._update_check_service = UpdateCheckService()
        self._update_check_done = False
        self._update_check_manual_running = False
        super().__init__(**kwargs)
        self._container.host_psm_service.set_activity_callback(self._on_host_psm_activity)
        self._restore_host_psm_snapshot(self._container.host_psm_service.snapshot())

    def on_kv_post(self, base_widget):
        settings = self._container.discovery_controller.load_last_connection()
        self.host_text = settings.host
        self.port_text = str(settings.port)
        current_version = self._container.y2jb_backup_controller.current_release_version()
        if current_version:
            self.backup_version_text = current_version
        self._start_remote_refresh_checks()

    def refresh_remote_checks_on_resume(self) -> None:
        "Inicia um ciclo novo ao voltar de uma saída real do aplicativo."
        with self._remote_refresh_lock:
            if self._remote_refresh_active:
                return
        if self._pending_user_storage_menu or self._host_psm_permission_pending:
            return
        controllers = (
            self._container.y2jb_backup_controller,
            self._container.payload_controller,
            self._container.youtube_update_controller,
            self._container.pkg_controller,
        )
        if all(controller.refresh_complete for controller in controllers):
            for controller in controllers:
                controller.begin_refresh_cycle()
        self._container.github_release_service.begin_refresh_cycle()
        self._start_remote_refresh_checks()

    def _start_remote_refresh_checks(self) -> None:
        checks = (
            (
                "y2jb-release-check",
                self._container.y2jb_backup_controller.refresh_complete,
                self._refresh_y2jb_release_metadata,
            ),
            (
                "payload-release-check",
                self._container.payload_controller.refresh_complete,
                self._refresh_payload_release_metadata,
            ),
            (
                "youtube-update-catalog-check",
                self._container.youtube_update_controller.refresh_complete,
                self._refresh_youtube_update_catalog,
            ),
            (
                "pkg-dependency-check",
                self._container.pkg_controller.refresh_complete,
                self._refresh_pkg_dependencies,
            ),
            (
                "update-check",
                self._update_check_done,
                self._refresh_update_check,
            ),
        )
        for name, completed, target in checks:
            if completed:
                continue
            self._start_remote_refresh_worker(name, target)

    def _start_remote_refresh_worker(self, name: str, target) -> None:
        with self._remote_refresh_lock:
            if name in self._remote_refresh_active:
                return
            self._remote_refresh_active.add(name)

        def worker() -> None:
            try:
                target()
            finally:
                with self._remote_refresh_lock:
                    self._remote_refresh_active.discard(name)

        threading.Thread(target=worker, daemon=True, name=name).start()

    def _refresh_y2jb_release_metadata(self) -> None:
        try:
            self._container.y2jb_backup_controller.ensure_latest_release_checked()
            version = self._container.y2jb_backup_controller.current_release_version()
        except Exception:
            return
        if version:
            Clock.schedule_once(
                lambda _dt, resolved_version=version: self._apply_y2jb_release_version(
                    resolved_version
                ),
                0,
            )

    def _apply_y2jb_release_version(self, version: str) -> None:
        if version:
            self.backup_version_text = version

    def _refresh_update_check(self) -> None:
        try:
            info = self._update_check_service.check()
        except Exception:
            info = None
        self._update_check_done = True
        if info is not None:
            Clock.schedule_once(
                lambda _dt, resolved_info=info: self._apply_update_info(resolved_info),
                0,
            )

    def _apply_update_info(self, info) -> None:
        self.update_url = info.url
        self.update_banner_text = f"Nova versão disponível: {info.tag}"
        self.update_available = True

    def open_update_url(self) -> None:
        if self.update_url:
            webbrowser.open(self.update_url)

    def check_for_updates_now(self) -> None:
        """Manual trigger from Settings — unlike the silent startup check, this always
        reports back (found, up to date, or failed), and un-hides a previously dismissed
        banner if a newer release turns out to be available."""
        if self._update_check_manual_running:
            return
        self._update_check_manual_running = True
        self.update_check_status_text = "Verificando..."

        def worker() -> None:
            # UpdateCheckService.check() already fails soft (network errors and "no newer
            # release" both come back as None) — there is no reliable way to tell those
            # two cases apart here, so this message only ever claims what's actually true.
            info = self._update_check_service.check()
            self._update_check_done = True
            Clock.schedule_once(
                lambda _dt, resolved_info=info: self._apply_manual_update_result(resolved_info),
                0,
            )

        threading.Thread(target=worker, daemon=True, name="update-check-manual").start()

    def _apply_manual_update_result(self, info) -> None:
        self._update_check_manual_running = False
        if info is not None:
            self.update_dismissed = False
            self._apply_update_info(info)
            self.update_check_status_text = f"Nova versão disponível: {info.tag}"
        else:
            self.update_check_status_text = "Nenhuma atualização encontrada."

    def _ensure_user_storage_access(self, menu_kind: str) -> bool:
        self._pending_user_storage_menu = menu_kind
        ready = self._container.user_storage_access.ensure(
            on_ready=self.resume_pending_user_storage_menu
        )
        if ready:
            self._pending_user_storage_menu = None
            return True
        toast("Permita ao SENDPP acessar os arquivos do usuário e volte ao app.")
        return False

    def resume_pending_user_storage_menu(self) -> None:
        menu_kind = self._pending_user_storage_menu
        if not menu_kind:
            return
        if platform == "android" and not self._container.user_storage_access.has_access():
            self._pending_user_storage_menu = None
            return
        self._pending_user_storage_menu = None
        if menu_kind == "payload":
            self.open_payload_menu(None)
            return
        if menu_kind == "youtube_update":
            self.open_youtube_update_menu(None)
            return
        if menu_kind == "pkg":
            self.open_pkg_menu(None)
            return

    def _refresh_payload_release_metadata(self) -> None:
        try:
            self._container.payload_controller.ensure_latest_sources_checked()
        except Exception:
            return
        Clock.schedule_once(lambda _dt: self._refresh_open_payload_menu(), 0)

    def _refresh_open_payload_menu(self) -> None:
        modal = self._payload_menu
        if modal is None:
            return
        try:
            entries = self._container.payload_controller.menu_entries(
                is_android=platform == "android"
            )
            modal.replace_entries(entries)
        except Exception:
            return

    def _refresh_youtube_update_catalog(self) -> None:
        try:
            self._container.youtube_update_controller.ensure_latest_sources_checked()
        except Exception:
            return
        Clock.schedule_once(lambda _dt: self._refresh_open_youtube_update_menu(), 0)

    def _refresh_open_youtube_update_menu(self) -> None:
        modal = self._youtube_update_menu
        if modal is None:
            return
        try:
            entries = self._container.youtube_update_controller.menu_entries(
                is_android=platform == "android"
            )
            modal.replace_entries(entries)
        except Exception:
            return

    def open_payload_menu(self, caller) -> None:
        if (
            self.busy
            or self.backup_busy
            or self.payload_busy
            or self.youtube_update_busy
            or self.pkg_busy
            or self.host_psm_busy
        ):
            return
        if platform == "android" and not self._ensure_user_storage_access("payload"):
            return

        try:
            if self._payload_menu is not None:
                self._payload_menu.dismiss()
        except Exception:
            pass
        self._payload_menu = None

        entries = self._container.payload_controller.menu_entries(
            is_android=platform == "android"
        )
        if not entries:
            self._set_payload_error("Nenhum payload disponível.")
            return

        self._payload_menu = PayloadSelectorModal(
            entries=entries,
            on_select=self._select_payload_entry,
            on_open_folder=self._open_payload_folder,
        )
        self._payload_menu.open()

    def _open_payload_folder(self) -> None:
        self._payload_menu = None
        try:
            self._container.payload_controller.open_local_payload_folder(
                is_android=platform == "android"
            )
        except LocalFolderOpenError as exc:
            toast(str(exc))

    def _select_payload_entry(self, entry: PayloadMenuEntry) -> None:
        try:
            if self._payload_menu is not None:
                self._payload_menu.dismiss()
        except Exception:
            pass
        self._payload_menu = None
        self._start_payload(entry)

    def _start_payload(self, entry: PayloadMenuEntry) -> None:
        if (
            self.busy
            or self.backup_busy
            or self.payload_busy
            or self.youtube_update_busy
            or self.pkg_busy
            or self.host_psm_busy
        ):
            return

        warning = self._container.payload_controller.warning_for(entry, self.port_text)
        if warning:
            toast(warning)

        self.payload_busy = True
        self.payload_status_color = get_color_from_hex("#B8BDC5")
        self.payload_status_text = f"Preparando • {entry.label}"

        def on_progress(progress: PayloadProgress) -> None:
            Clock.schedule_once(
                lambda _dt, payload_progress=progress: self._apply_payload_progress(
                    payload_progress
                ),
                0,
            )

        def worker() -> None:
            try:
                result = self._container.payload_controller.execute(
                    entry,
                    host=self.host_text,
                    raw_port=self.port_text,
                    is_android=platform == "android",
                    progress=on_progress,
                )
            except InvalidPayloadConnectionError as exc:
                code = str(exc)
                if code == "host_required":
                    message = "Informe o IP do PS5."
                elif code == "port_out_of_range":
                    message = "Porta fora do intervalo 1–65535."
                else:
                    message = "Porta inválida. Use somente números."
                Clock.schedule_once(
                    lambda _dt, error_message=message: self._finish_payload_error(
                        error_message
                    ),
                    0,
                )
                return
            except Exception as exc:
                message = str(exc).strip() or "Falha ao enviar o payload."
                Clock.schedule_once(
                    lambda _dt, error_message=message: self._finish_payload_error(
                        error_message
                    ),
                    0,
                )
                return
            Clock.schedule_once(
                lambda _dt, payload_result=result: self._finish_payload(payload_result),
                0,
            )

        threading.Thread(target=worker, daemon=True, name="payload-send").start()

    def _apply_payload_progress(self, progress: PayloadProgress) -> None:
        if not self.payload_busy:
            return
        message = progress.message.strip().rstrip(".")
        self.payload_status_color = get_color_from_hex("#B8BDC5")
        if progress.percent is None:
            self.payload_status_text = message
            return
        percent = max(0, min(100, int(progress.percent)))
        self.payload_status_text = f"{message} • {percent}%"

    def _finish_payload(self, result) -> None:
        self.payload_busy = False
        self.payload_status_color = get_color_from_hex("#79C98D")
        self.payload_status_text = f"Executado • {result.label}"
        toast(f"Payload enviado: {result.label}")

    def _finish_payload_error(self, message: str) -> None:
        self.payload_busy = False
        self._set_payload_error(message)

    def _set_payload_error(self, message: str) -> None:
        self.payload_status_color = get_color_from_hex("#E47C73")
        self.payload_status_text = f"Falha • {message}"
        toast(message)

    def open_youtube_update_menu(self, caller) -> None:
        if (
            self.busy
            or self.backup_busy
            or self.payload_busy
            or self.youtube_update_busy
            or self.pkg_busy
            or self.host_psm_busy
        ):
            return
        if platform == "android" and not self._ensure_user_storage_access("youtube_update"):
            return

        try:
            if self._youtube_update_menu is not None:
                self._youtube_update_menu.dismiss()
        except Exception:
            pass
        self._youtube_update_menu = None

        entries = self._container.youtube_update_controller.menu_entries(
            is_android=platform == "android"
        )
        if not entries:
            self._set_youtube_update_error("Nenhum update disponível.")
            return

        self._youtube_update_menu = YouTubeUpdateSelectorModal(
            entries=entries,
            on_select=self._select_youtube_update_entry,
            on_open_folder=self._open_youtube_update_folder,
        )
        self._youtube_update_menu.open()

    def _open_youtube_update_folder(self) -> None:
        self._youtube_update_menu = None
        try:
            self._container.youtube_update_controller.open_local_update_folder(
                is_android=platform == "android"
            )
        except LocalFolderOpenError as exc:
            toast(str(exc))

    def _select_youtube_update_entry(self, entry: YouTubeUpdateMenuEntry) -> None:
        try:
            if self._youtube_update_menu is not None:
                self._youtube_update_menu.dismiss()
        except Exception:
            pass
        self._youtube_update_menu = None
        self._start_youtube_update(entry)

    def start_youtube_account_activation(self) -> None:
        if (
            self.busy
            or self.backup_busy
            or self.payload_busy
            or self.youtube_update_busy
            or self.pkg_busy
            or self.host_psm_busy
        ):
            return

        self.youtube_update_busy = True
        self.youtube_update_status_color = get_color_from_hex("#B8BDC5")
        self.youtube_update_status_text = "Ativando conta..."

        def on_progress(progress: YouTubeUpdateProgress) -> None:
            Clock.schedule_once(
                lambda _dt, update_progress=progress: self._apply_youtube_update_progress(
                    update_progress
                ),
                0,
            )

        def worker() -> None:
            try:
                self._container.youtube_update_controller.activate_current_account(
                    host=self.host_text,
                    raw_port=self.port_text,
                    progress=on_progress,
                )
            except InvalidYouTubeUpdateConnectionError as exc:
                code = str(exc)
                if code == "host_required":
                    message = "Informe o IP do PS5."
                elif code == "port_out_of_range":
                    message = "Porta fora do intervalo 1–65535."
                else:
                    message = "Porta inválida. Use somente números."
                Clock.schedule_once(
                    lambda _dt, error_message=message: self._finish_youtube_update_error(
                        error_message
                    ),
                    0,
                )
                return
            except Exception as exc:
                message = str(exc).strip() or "Falha ao enviar ativação."
                Clock.schedule_once(
                    lambda _dt, error_message=message: self._finish_youtube_update_error(
                        error_message
                    ),
                    0,
                )
                return
            Clock.schedule_once(lambda _dt: self._finish_youtube_account_activation(), 0)

        threading.Thread(
            target=worker, daemon=True, name="youtube-account-activation"
        ).start()

    def _finish_youtube_account_activation(self) -> None:
        self.youtube_update_busy = False
        self.youtube_update_status_color = get_color_from_hex("#79C98D")
        self.youtube_update_status_text = "Conta ativa. Reinicie o PS5."
        toast("Reinicie o PS5 antes do jailbreak.")

    def _start_youtube_update(self, entry: YouTubeUpdateMenuEntry) -> None:
        if (
            self.busy
            or self.backup_busy
            or self.payload_busy
            or self.youtube_update_busy
            or self.pkg_busy
            or self.host_psm_busy
        ):
            return

        self.youtube_update_busy = True
        self.youtube_update_status_color = get_color_from_hex("#B8BDC5")
        self.youtube_update_status_text = f"Preparando • {entry.label}"

        def on_progress(progress: YouTubeUpdateProgress) -> None:
            Clock.schedule_once(
                lambda _dt, update_progress=progress: self._apply_youtube_update_progress(
                    update_progress
                ),
                0,
            )

        def worker() -> None:
            try:
                result = self._container.youtube_update_controller.install(
                    entry,
                    host=self.host_text,
                    raw_port=self.port_text,
                    is_android=platform == "android",
                    progress=on_progress,
                )
            except InvalidYouTubeUpdateConnectionError as exc:
                code = str(exc)
                if code == "host_required":
                    message = "Informe o IP do PS5."
                elif code == "port_out_of_range":
                    message = "Porta fora do intervalo 1–65535."
                else:
                    message = "Porta inválida. Use somente números."
                Clock.schedule_once(
                    lambda _dt, error_message=message: self._finish_youtube_update_error(
                        error_message
                    ),
                    0,
                )
                return
            except Exception as exc:
                message = str(exc).strip() or "Falha ao atualizar o YouTube."
                Clock.schedule_once(
                    lambda _dt, error_message=message: self._finish_youtube_update_error(
                        error_message
                    ),
                    0,
                )
                return
            Clock.schedule_once(
                lambda _dt, update_result=result: self._finish_youtube_update(
                    update_result
                ),
                0,
            )

        threading.Thread(target=worker, daemon=True, name="youtube-update-install").start()

    def _apply_youtube_update_progress(self, progress: YouTubeUpdateProgress) -> None:
        if not self.youtube_update_busy:
            return
        message = progress.message.strip().rstrip(".")
        self.youtube_update_status_color = get_color_from_hex("#B8BDC5")
        if progress.percent is None:
            self.youtube_update_status_text = message
            return
        percent = max(0, min(100, int(progress.percent)))
        self.youtube_update_status_text = f"{message} • {percent}%"

    def _finish_youtube_update(self, result) -> None:
        self.youtube_update_busy = False
        self.youtube_update_status_color = get_color_from_hex("#79C98D")
        self.youtube_update_status_text = f"Aplicado • {result.label}"
        toast("YouTube atualizado.")

    def _finish_youtube_update_error(self, message: str) -> None:
        self.youtube_update_busy = False
        self._set_youtube_update_error(message)

    def _set_youtube_update_error(self, message: str) -> None:
        self.youtube_update_status_color = get_color_from_hex("#E47C73")
        self.youtube_update_status_text = f"Falha • {message}"
        toast(message)

    def _refresh_pkg_dependencies(self) -> None:
        try:
            self._container.pkg_controller.ensure_dependencies_checked()
        except Exception:
            return
        Clock.schedule_once(lambda _dt: self._refresh_open_pkg_menu(), 0)

    def _refresh_open_pkg_menu(self) -> None:
        modal = self._pkg_menu
        if modal is None:
            return
        try:
            entries = self._container.pkg_controller.menu_entries(
                is_android=platform == "android"
            )
            modal.replace_entries(entries)
        except Exception:
            return

    def open_pkg_menu(self, caller) -> None:
        if (
            self.busy
            or self.backup_busy
            or self.payload_busy
            or self.youtube_update_busy
            or self.pkg_busy
            or self.host_psm_busy
        ):
            return
        if platform == "android" and not self._ensure_user_storage_access("pkg"):
            return

        try:
            if self._pkg_menu is not None:
                self._pkg_menu.dismiss()
        except Exception:
            pass
        self._pkg_menu = None

        entries = self._container.pkg_controller.menu_entries(
            is_android=platform == "android"
        )
        if not entries:
            self._set_pkg_error("Nenhum PKG disponível.")
            return

        self._pkg_menu = PkgSelectorModal(
            entries=entries,
            on_select=self._select_pkg_entry,
            on_open_folder=self._open_pkg_folder,
        )
        self._pkg_menu.open()

    def _open_pkg_folder(self) -> None:
        self._pkg_menu = None
        try:
            self._container.pkg_controller.open_local_pkg_folder(
                is_android=platform == "android"
            )
        except LocalFolderOpenError as exc:
            toast(str(exc))

    def _select_pkg_entry(self, entry: PkgMenuEntry) -> None:
        try:
            if self._pkg_menu is not None:
                self._pkg_menu.dismiss()
        except Exception:
            pass
        self._pkg_menu = None
        self._start_pkg(entry)

    def _start_pkg(self, entry: PkgMenuEntry) -> None:
        if (
            self.busy
            or self.backup_busy
            or self.payload_busy
            or self.youtube_update_busy
            or self.pkg_busy
            or self.host_psm_busy
        ):
            return

        self.pkg_busy = True
        self.pkg_status_color = get_color_from_hex("#B8BDC5")
        self.pkg_status_text = f"Preparando • {entry.label}"

        def on_progress(progress: PkgProgress) -> None:
            Clock.schedule_once(
                lambda _dt, pkg_progress=progress: self._apply_pkg_progress(
                    pkg_progress
                ),
                0,
            )

        def worker() -> None:
            try:
                result = self._container.pkg_controller.install(
                    entry,
                    host=self.host_text,
                    raw_port=self.port_text,
                    is_android=platform == "android",
                    progress=on_progress,
                )
            except InvalidPkgConnectionError as exc:
                code = str(exc)
                if code == "host_required":
                    message = "Informe o IP do PS5."
                elif code == "port_out_of_range":
                    message = "Porta fora do intervalo 1–65535."
                else:
                    message = "Porta inválida. Use somente números."
                Clock.schedule_once(
                    lambda _dt, error_message=message: self._finish_pkg_error(
                        error_message
                    ),
                    0,
                )
                return
            except Exception as exc:
                message = str(exc).strip() or "Falha ao instalar o PKG."
                Clock.schedule_once(
                    lambda _dt, error_message=message: self._finish_pkg_error(
                        error_message
                    ),
                    0,
                )
                return
            Clock.schedule_once(
                lambda _dt, pkg_result=result: self._finish_pkg(pkg_result),
                0,
            )

        threading.Thread(target=worker, daemon=True, name="pkg-install").start()

    def _apply_pkg_progress(self, progress: PkgProgress) -> None:
        if not self.pkg_busy:
            return
        message = progress.message.strip().rstrip(".")
        self.pkg_status_color = get_color_from_hex("#B8BDC5")
        if progress.percent is None:
            self.pkg_status_text = message
            return
        percent = max(0, min(100, int(progress.percent)))
        self.pkg_status_text = f"{message} • {percent}%"

    def _finish_pkg(self, result) -> None:
        self.pkg_busy = False
        self.pkg_status_color = get_color_from_hex("#79C98D")
        self.pkg_status_text = f"Instalado • {result.label}"
        toast(f"PKG instalado: {result.label}")

    def _finish_pkg_error(self, message: str) -> None:
        self.pkg_busy = False
        self._set_pkg_error(message)

    def _set_pkg_error(self, message: str) -> None:
        self.pkg_status_color = get_color_from_hex("#E47C73")
        self.pkg_status_text = f"Falha • {message}"
        toast(message)

    def toggle_host_psm(self) -> None:
        if self.host_psm_busy:
            return

        if self.host_psm_running:
            self.host_psm_busy = True
            self.host_psm_status_color = get_color_from_hex("#B8BDC5")
            self.host_psm_status_text = "Encerrando Host local..."

            def stop_worker() -> None:
                try:
                    snapshot = self._container.host_psm_service.stop()
                except Exception as exc:
                    message = str(exc).strip() or "Falha ao parar o Host local."
                    Clock.schedule_once(
                        lambda _dt, error_message=message: self._finish_host_psm_error(
                            error_message
                        ),
                        0,
                    )
                    return
                Clock.schedule_once(
                    lambda _dt, resolved_snapshot=snapshot: self._finish_host_psm_stop(
                        resolved_snapshot
                    ),
                    0,
                )

            threading.Thread(target=stop_worker, daemon=True, name="host-psm-stop").start()
            return

        if (
            self.busy
            or self.backup_busy
            or self.payload_busy
            or self.youtube_update_busy
            or self.pkg_busy
        ):
            return

        if platform == "android":
            if self._host_psm_permission_pending:
                return
            session_ready = self._container.host_psm_service.ensure_android_long_session_ready(
                self._resume_host_psm_after_android_readiness
            )
            if not session_ready:
                self._host_psm_permission_pending = True
                self.host_psm_status_color = get_color_from_hex("#D5A45C")
                self.host_psm_status_text = (
                    "Aguardando autorização Android para manter o Host ativo"
                )
                toast("Autorize o Android a manter o Host local ativo.")
                return

        self.host_psm_busy = True
        self.host_psm_connected = False
        self.host_psm_status_color = get_color_from_hex("#B8BDC5")
        self.host_psm_status_text = "Iniciando Host local..."

        def start_worker() -> None:
            try:
                snapshot = self._container.host_psm_service.start()
            except Exception as exc:
                message = str(exc).strip() or "Falha ao iniciar o Host local."
                Clock.schedule_once(
                    lambda _dt, error_message=message: self._finish_host_psm_error(
                        error_message
                    ),
                    0,
                )
                return
            Clock.schedule_once(
                lambda _dt, resolved_snapshot=snapshot: self._finish_host_psm_start(
                    resolved_snapshot
                ),
                0,
            )

        threading.Thread(target=start_worker, daemon=True, name="host-psm-start").start()

    def _finish_host_psm_start(self, snapshot) -> None:
        self.host_psm_busy = False
        self.host_psm_running = bool(snapshot.running)
        self.host_psm_status_color = get_color_from_hex("#79C98D")
        self.host_psm_status_text = f"Ativo • {snapshot.endpoint} • abra o Guia do Usuário"
        if snapshot.client_ip:
            self._apply_host_psm_activity(snapshot)
        toast("Host local iniciado.")

    def _resume_host_psm_after_android_readiness(self, ready: bool) -> None:
        if ready:
            self._host_psm_permission_pending = False
            self.toggle_host_psm()
            return
        self._host_psm_permission_pending = True
        self.host_psm_status_color = get_color_from_hex("#D5A45C")
        self.host_psm_status_text = "Aguardando autorização Android para manter o Host ativo"
        toast("Autorize o Android a manter o Host local ativo.")

    def _finish_host_psm_stop(self, _snapshot) -> None:
        self.host_psm_busy = False
        self.host_psm_running = False
        self.host_psm_connected = False
        self.host_psm_status_color = get_color_from_hex("#A7ADB7")
        self.host_psm_status_text = "Parado • WebKit + ReLapse + Instalador"
        toast("Host PSM parado.")

    def _finish_host_psm_error(self, message: str) -> None:
        self.host_psm_busy = False
        self.host_psm_running = self._container.host_psm_service.snapshot().running
        if not self.host_psm_running:
            self.host_psm_connected = False
        self.host_psm_status_color = get_color_from_hex("#E47C73")
        self.host_psm_status_text = f"Falha • {message}"
        toast(message)

    def _on_host_psm_activity(self, snapshot) -> None:
        Clock.schedule_once(
            lambda _dt, resolved_snapshot=snapshot: self._restore_host_psm_snapshot(
                resolved_snapshot
            ),
            0,
        )

    def _restore_host_psm_snapshot(self, snapshot) -> None:
        self.host_psm_busy = False
        self.host_psm_running = bool(snapshot.running)
        if not self.host_psm_running:
            self.host_psm_connected = False
            if snapshot.phase == "failed" and getattr(snapshot, "error", ""):
                self.host_psm_status_color = get_color_from_hex("#E47C73")
                self.host_psm_status_text = f"Falha • {snapshot.error}"
                return
            self.host_psm_status_color = get_color_from_hex("#A7ADB7")
            self.host_psm_status_text = "Parado • WebKit + ReLapse + Instalador"
            return

        self.host_psm_status_color = get_color_from_hex("#79C98D")
        if snapshot.client_ip:
            self.host_psm_connected = True
            self.host_psm_status_text = (
                f"Guia acessado • {snapshot.client_ip} • {snapshot.endpoint}"
            )
            return

        self.host_psm_connected = False
        self.host_psm_status_text = f"Ativo • {snapshot.endpoint} • abra o Guia do Usuário"

    def _apply_host_psm_activity(self, snapshot) -> None:
        self._restore_host_psm_snapshot(snapshot)

    def resume_host_psm_session(self) -> None:
        self._container.host_psm_service.set_activity_callback(self._on_host_psm_activity)
        self._restore_host_psm_snapshot(self._container.host_psm_service.snapshot())

        if platform == "android":
            if self._host_psm_permission_pending:
                if not self.host_psm_running:
                    if not self.host_psm_busy:
                        self._host_psm_permission_pending = False
                        self.toggle_host_psm()

    def handle_app_stop(self) -> None:
        snapshot = self._container.host_psm_service.snapshot()
        if platform == "android" and snapshot.running:
            self._container.host_psm_service.detach_activity()
            return
        self.shutdown()

    def shutdown(self) -> None:
        self._container.host_psm_service.set_activity_callback(None)
        self._container.host_psm_service.shutdown()
        self.host_psm_busy = False
        self.host_psm_running = False
        self.host_psm_connected = False

    def start_discovery(self) -> None:
        if (
            self.busy
            or self.backup_busy
            or self.payload_busy
            or self.youtube_update_busy
            or self.pkg_busy
            or self.host_psm_busy
        ):
            return

        try:
            port = self._container.discovery_controller.parse_port(self.port_text)
        except InvalidPortError as exc:
            if str(exc) == "out_of_range":
                self._set_error("Porta fora do intervalo 1–65535.")
            else:
                self._set_error("Porta inválida. Use somente números.")
            return

        self.busy = True
        self.status_color = get_color_from_hex("#B8BDC5")
        self.status_text = f"Buscando PS5 na porta {port}..."

        def worker() -> None:
            try:
                result = self._container.discovery_controller.discover(
                    raw_port=str(port),
                    is_android=platform == "android",
                )
            except LocalIPv4UnavailableError:
                Clock.schedule_once(
                    lambda _dt: self._finish_error(
                        "Não consegui descobrir o IP local deste dispositivo."
                    ),
                    0,
                )
                return
            except Exception:
                Clock.schedule_once(
                    lambda _dt: self._finish_error("Falha ao buscar o PS5 na rede local."),
                    0,
                )
                return
            Clock.schedule_once(lambda _dt: self._finish_discovery(result), 0)

        threading.Thread(target=worker, daemon=True, name="ps5-discovery").start()

    def start_y2jb_backup(self, variant_key: str) -> None:
        if (
            self.busy
            or self.backup_busy
            or self.payload_busy
            or self.youtube_update_busy
            or self.pkg_busy
            or self.host_psm_busy
        ):
            return

        self._container.y2jb_backup_controller.get_variant(variant_key)
        self.backup_busy = True
        self.backup_status_color = get_color_from_hex("#B8BDC5")
        self.backup_status_text = "Preparando backup..."

        def on_progress(progress: Y2JBBackupProgress) -> None:
            Clock.schedule_once(lambda _dt: self._apply_backup_progress(progress), 0)

        def worker() -> None:
            try:
                result = self._container.y2jb_backup_controller.run(
                    variant_key,
                    is_android=platform == "android",
                    progress=on_progress,
                )
            except RemovableUsbNotFoundError as exc:
                message = str(exc).strip() or "Dispositivo USB removível não encontrado."
                Clock.schedule_once(
                    lambda _dt, error_message=message: self._finish_backup_error(
                        error_message
                    ),
                    0,
                )
                return
            except Exception as exc:
                message = str(exc).strip() or "Falha ao preparar o backup Y2JB."
                Clock.schedule_once(
                    lambda _dt, error_message=message: self._finish_backup_error(
                        error_message
                    ),
                    0,
                )
                return
            Clock.schedule_once(lambda _dt: self._finish_y2jb_backup(result), 0)

        threading.Thread(target=worker, daemon=True, name="y2jb-backup").start()

    def _apply_backup_progress(self, progress: Y2JBBackupProgress) -> None:
        if not self.backup_busy:
            return

        message = progress.message.strip().rstrip(".")
        self.backup_status_color = get_color_from_hex("#B8BDC5")

        if progress.percent is None:
            self.backup_status_text = message
            return

        percent = max(0, min(100, int(progress.percent)))
        self.backup_status_text = f"{message} • {percent}%"

    def _finish_y2jb_backup(self, result) -> None:
        self.backup_busy = False
        self.backup_status_color = get_color_from_hex("#79C98D")
        self.backup_status_text = f"Concluído • {result.copied_files} arquivo(s)"
        if result.variant.release_version:
            self.backup_version_text = result.variant.release_version
        toast("Y2JB Backup/Gezine concluído.")

    def _finish_backup_error(self, message: str) -> None:
        self.backup_busy = False
        self.backup_status_color = get_color_from_hex("#E47C73")
        self.backup_status_text = f"Falha • {message}"
        toast(message)

    def _finish_discovery(self, result) -> None:
        self.busy = False
        if not result.found:
            self.status_color = get_color_from_hex("#D5A45C")
            self.status_text = f"Nenhum PS5 encontrado em {result.network_cidr}."
            toast("Nenhum PS5 encontrado.")
            return

        self.host_text = result.found_ip
        self.port_text = str(result.port)
        self.status_color = get_color_from_hex("#79C98D")
        self.status_text = f"PS5 encontrado em {result.found_ip}:{result.port}"
        toast(f"PS5 encontrado: {result.found_ip}")

    def _finish_error(self, message: str) -> None:
        self.busy = False
        self._set_error(message)

    def _set_error(self, message: str) -> None:
        self.status_color = get_color_from_hex("#E47C73")
        self.status_text = message
        toast(message)

    # ---- Trainers (CheatRunner) -----------------------------------------------------
    def open_trainer_browser(self, caller) -> None:
        if (
            self.busy
            or self.backup_busy
            or self.payload_busy
            or self.youtube_update_busy
            or self.pkg_busy
            or self.host_psm_busy
        ):
            return

        try:
            if self._trainer_browser_modal is not None:
                self._trainer_browser_modal.dismiss()
        except Exception:
            pass

        self._trainer_browser_modal = TrainerBrowserModal(
            catalog=self._container.trainer_catalog,
            cover_service=self._container.cover_art_service,
            cheatrunner_client=self._container.cheatrunner_client,
            host_provider=lambda: self.host_text,
            port_provider=lambda: self.port_text,
            on_send_cheatrunner=self.start_trainer_send_cheatrunner,
        )
        self._trainer_browser_modal.open()

    def start_trainer_send_cheatrunner(self, on_update=None) -> None:
        """Downloads the current CheatRunner.elf and pushes it to the PS5 loader port.

        ``on_update(text, color)`` is an optional callback (used by the open Trainer
        detail modal to mirror progress inline) in addition to the usual card-level
        status text/colour.
        """
        if (
            self.busy
            or self.backup_busy
            or self.payload_busy
            or self.youtube_update_busy
            or self.pkg_busy
            or self.host_psm_busy
            or self.trainer_busy
        ):
            if on_update:
                on_update("Aguarde a operação atual terminar.", get_color_from_hex("#D5A45C"))
            return

        host = (self.host_text or "").strip()
        if not host:
            message = "Informe o IP do PS5."
            self._set_trainer_error(message)
            if on_update:
                on_update(message, get_color_from_hex("#E47C73"))
            return

        try:
            port = self._container.discovery_controller.parse_port(self.port_text)
        except InvalidPortError as exc:
            message = (
                "Porta fora do intervalo 1–65535."
                if str(exc) == "out_of_range"
                else "Porta inválida. Use somente números."
            )
            self._set_trainer_error(message)
            if on_update:
                on_update(message, get_color_from_hex("#E47C73"))
            return

        self.trainer_busy = True
        self.trainer_status_color = get_color_from_hex("#B8BDC5")
        self.trainer_status_text = "Preparando • CheatRunner"
        if on_update:
            on_update("Preparando • CheatRunner", get_color_from_hex("#B8BDC5"))

        def on_progress(progress) -> None:
            message = str(getattr(progress, "message", "")).strip().rstrip(".")
            percent = getattr(progress, "percent", None)
            text = (
                message
                if percent is None
                else f"{message} • {max(0, min(100, int(percent)))}%"
            )
            Clock.schedule_once(
                lambda _dt, resolved_text=text: self._apply_trainer_progress(
                    resolved_text, on_update
                ),
                0,
            )

        def worker() -> None:
            try:
                self._container.cheatrunner_release_service.send(
                    host=host,
                    port=port,
                    is_android=platform == "android",
                    progress=on_progress,
                )
            except Exception as exc:
                message = str(exc).strip() or "Falha ao enviar o CheatRunner."
                Clock.schedule_once(
                    lambda _dt, error_message=message: self._finish_trainer_error(
                        error_message, on_update
                    ),
                    0,
                )
                return
            Clock.schedule_once(lambda _dt: self._finish_trainer_send(on_update), 0)

        threading.Thread(target=worker, daemon=True, name="trainer-cheatrunner-send").start()

    def _apply_trainer_progress(self, text: str, on_update) -> None:
        if self.trainer_busy:
            self.trainer_status_color = get_color_from_hex("#B8BDC5")
            self.trainer_status_text = text
        if on_update:
            on_update(text, get_color_from_hex("#B8BDC5"))

    def _finish_trainer_send(self, on_update) -> None:
        self.trainer_busy = False
        self.trainer_status_color = get_color_from_hex("#79C98D")
        self.trainer_status_text = "CheatRunner enviado."
        toast("CheatRunner enviado para o PS5.")
        if on_update:
            on_update("CheatRunner enviado para o PS5.", get_color_from_hex("#79C98D"))

    def _finish_trainer_error(self, message: str, on_update) -> None:
        self.trainer_busy = False
        self._set_trainer_error(message)
        if on_update:
            on_update(message, get_color_from_hex("#E47C73"))

    def _set_trainer_error(self, message: str) -> None:
        self.trainer_status_color = get_color_from_hex("#E47C73")
        self.trainer_status_text = f"Falha • {message}"

    def start_trainer_auto_load(self) -> None:
        """Sends kstuff then CheatRunner in sequence, with the delay each one's catalog
        entry recommends between it and the next step (see ``auto_loader_service.py``)."""
        if (
            self.busy
            or self.backup_busy
            or self.payload_busy
            or self.youtube_update_busy
            or self.pkg_busy
            or self.host_psm_busy
            or self.trainer_busy
        ):
            return

        host = (self.host_text or "").strip()
        if not host:
            self._set_trainer_error("Informe o IP do PS5.")
            return

        try:
            port = self._container.discovery_controller.parse_port(self.port_text)
        except InvalidPortError as exc:
            message = (
                "Porta fora do intervalo 1–65535."
                if str(exc) == "out_of_range"
                else "Porta inválida. Use somente números."
            )
            self._set_trainer_error(message)
            return

        self.trainer_busy = True
        self.trainer_status_color = get_color_from_hex("#B8BDC5")
        self.trainer_status_text = "Preparando • sequência automática"

        def on_step(label: str, index: int, total: int) -> None:
            Clock.schedule_once(
                lambda _dt: self._apply_trainer_progress(
                    f"Carregando • {label} ({index}/{total})", None
                ),
                0,
            )

        def on_progress(progress) -> None:
            message = str(getattr(progress, "message", "")).strip().rstrip(".")
            percent = getattr(progress, "percent", None)
            text = message if percent is None else f"{message} • {max(0, min(100, int(percent)))}%"
            Clock.schedule_once(
                lambda _dt, resolved_text=text: self._apply_trainer_progress(resolved_text, None), 0
            )

        def worker() -> None:
            try:
                self._container.auto_loader_service.run(
                    host=host,
                    port=port,
                    is_android=platform == "android",
                    on_step=on_step,
                    progress=on_progress,
                )
            except Exception as exc:
                message = str(exc).strip() or "Falha na sequência automática."
                Clock.schedule_once(
                    lambda _dt, error_message=message: self._finish_trainer_error(
                        error_message, None
                    ),
                    0,
                )
                return
            Clock.schedule_once(lambda _dt: self._finish_trainer_auto_load(), 0)

        threading.Thread(target=worker, daemon=True, name="trainer-auto-load").start()

    def _finish_trainer_auto_load(self) -> None:
        self.trainer_busy = False
        self.trainer_status_color = get_color_from_hex("#79C98D")
        self.trainer_status_text = "Sequência automática concluída."
        toast("kstuff + CheatRunner enviados ao PS5.")
        toast(message)
