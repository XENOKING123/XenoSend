from __future__ import annotations

import threading
from typing import Callable, Optional


PermissionResultCallback = Optional[Callable[[bool], None]]


class AndroidHostSessionGuard:
    """Notificação foreground + WakeLock/WifiLock da sessão do Host Local Android."""

    CHANNEL_ID = "sendpp.host_psm.network"
    NOTIFICATION_ID = 53
    NOTIFICATION_PERMISSION = "android.permission.POST_NOTIFICATIONS"
    BATTERY_OPTIMIZATION_PERMISSION = "android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS"

    def __init__(self, platform_name: str) -> None:
        self._platform_name = str(platform_name or "").lower()
        self._lock = threading.RLock()
        self._notification_manager = None
        self._foreground_context = None
        self._wake_lock = None
        self._wifi_lock = None
        self._active = False

    @property
    def is_android(self) -> bool:
        return self._platform_name == "android"

    def has_notification_permission(self) -> bool:
        if not self.is_android:
            return True
        try:
            from jnius import autoclass

            BuildVersion = autoclass("android.os.Build$VERSION")
            if int(BuildVersion.SDK_INT) < 33:
                return True
            context, _Context, _is_service = self._android_context()
            PackageManager = autoclass("android.content.pm.PackageManager")
            return int(context.checkSelfPermission(self.NOTIFICATION_PERMISSION)) == int(
                PackageManager.PERMISSION_GRANTED
            )
        except Exception:
            return False

    def ensure_notification_permission(
        self,
        on_result: PermissionResultCallback = None,
    ) -> bool:
        if not self.is_android or self.has_notification_permission():
            return True

        try:
            context, Context, _is_service = self._android_context()
            self._create_notification_channel(context, Context)
            from android.permissions import request_permissions

            def _after(_permissions, _grants) -> None:
                granted = self.has_notification_permission()
                self._schedule_result(on_result, granted)

            request_permissions(
                [self.NOTIFICATION_PERMISSION],
                _after,
            )
        except Exception:
            self._schedule_result(on_result, False)
        return False

    def ensure_long_session_ready(
        self,
        on_result: PermissionResultCallback = None,
    ) -> bool:
        if not self.is_android:
            return True
        if not self.has_notification_permission():
            def _after_notification(granted: bool) -> None:
                if not granted:
                    self._schedule_result(on_result, False)
                    return
                ready = self.ensure_long_session_ready(None)
                self._schedule_result(on_result, ready)

            self.ensure_notification_permission(_after_notification)
            return False
        if not self.is_ignoring_battery_optimizations():
            self.request_ignore_battery_optimizations()
            return False
        return True

    def is_ignoring_battery_optimizations(self) -> bool:
        if not self.is_android:
            return True
        try:
            from jnius import autoclass

            context, Context, _is_service = self._android_context()
            power = context.getSystemService(Context.POWER_SERVICE)
            if power is None:
                return False
            return bool(power.isIgnoringBatteryOptimizations(context.getPackageName()))
        except Exception:
            return False

    def request_ignore_battery_optimizations(self) -> None:
        if not self.is_android:
            return
        try:
            from jnius import autoclass

            context, _Context, _is_service = self._android_context()
            package_name = str(context.getPackageName())
            Intent = autoclass("android.content.Intent")
            Settings = autoclass("android.provider.Settings")
            Uri = autoclass("android.net.Uri")
            intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
            intent.setData(Uri.parse("package:" + package_name))
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
        except Exception:
            try:
                from jnius import autoclass

                context, _Context, _is_service = self._android_context()
                package_name = str(context.getPackageName())
                Intent = autoclass("android.content.Intent")
                Settings = autoclass("android.provider.Settings")
                Uri = autoclass("android.net.Uri")
                intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                intent.setData(Uri.parse("package:" + package_name))
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(intent)
            except Exception:
                return

    def activate(self, local_ip: str) -> None:
        if not self.is_android:
            return
        if not self.has_notification_permission():
            raise RuntimeError(
                "Autorize as notificações do SENDPP para iniciar o Host local."
            )
        if not self.is_ignoring_battery_optimizations():
            raise RuntimeError(
                "Autorize o Android a manter o SENDPP sem economia de bateria para iniciar o Host local."
            )

        with self._lock:
            if self._active:
                return

        try:
            context, Context, is_service = self._android_context()
            manager = self._create_notification_channel(context, Context)
            notification = self._build_notification(context, str(local_ip or "").strip())
            if is_service:
                context.startForeground(self.NOTIFICATION_ID, notification)
                foreground_context = context
            else:
                manager.notify(self.NOTIFICATION_ID, notification)
                foreground_context = None
            wake_lock, wifi_lock = self._acquire_network_locks(context, Context)
        except Exception as exc:
            self.deactivate()
            detail = str(exc).strip()
            message = "Não foi possível ativar a sessão Android do Host local."
            if detail:
                message = f"{message} {detail}"
            raise RuntimeError(message) from exc

        with self._lock:
            self._notification_manager = manager
            self._foreground_context = foreground_context
            self._wake_lock = wake_lock
            self._wifi_lock = wifi_lock
            self._active = True

    def deactivate(self) -> None:
        with self._lock:
            manager = self._notification_manager
            foreground_context = self._foreground_context
            wake_lock = self._wake_lock
            wifi_lock = self._wifi_lock
            self._notification_manager = None
            self._foreground_context = None
            self._wake_lock = None
            self._wifi_lock = None
            self._active = False

        if foreground_context is not None:
            try:
                foreground_context.stopForeground(True)
            except Exception:
                pass
        elif manager is not None:
            try:
                manager.cancel(self.NOTIFICATION_ID)
            except Exception:
                pass

        for lock in (wifi_lock, wake_lock):
            self._release_lock(lock)

    @staticmethod
    def _android_context():
        from jnius import autoclass

        Context = autoclass("android.content.Context")
        try:
            PythonService = autoclass("org.kivy.android.PythonService")
            service = PythonService.mService
            if service is not None:
                return service, Context, True
        except Exception:
            pass

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        if activity is None:
            raise RuntimeError("Contexto Android indisponível.")
        return activity, Context, False

    def _create_notification_channel(self, context=None, Context=None):
        from jnius import autoclass

        if context is None or Context is None:
            context, Context, _is_service = self._android_context()
        BuildVersion = autoclass("android.os.Build$VERSION")
        NotificationManager = autoclass("android.app.NotificationManager")
        manager = context.getSystemService(Context.NOTIFICATION_SERVICE)
        if manager is None:
            raise RuntimeError("Gerenciador de notificações indisponível.")
        if int(BuildVersion.SDK_INT) >= 26:
            NotificationChannel = autoclass("android.app.NotificationChannel")
            channel = NotificationChannel(
                self.CHANNEL_ID,
                "SENDPP • Host Local",
                NotificationManager.IMPORTANCE_LOW,
            )
            channel.setDescription(
                "Mantém o Host Local disponível durante o processo no PS5."
            )
            manager.createNotificationChannel(channel)
        return manager

    def _build_notification(self, context, local_ip: str):
        from jnius import autoclass

        BuildVersion = autoclass("android.os.Build$VERSION")
        Notification = autoclass("android.app.Notification")
        NotificationBuilder = autoclass("android.app.Notification$Builder")
        PendingIntent = autoclass("android.app.PendingIntent")

        package_manager = context.getPackageManager()
        open_intent = package_manager.getLaunchIntentForPackage(context.getPackageName())
        if open_intent is None:
            raise RuntimeError("Intent de abertura do SENDPP indisponível.")

        pending_flags = int(PendingIntent.FLAG_UPDATE_CURRENT)
        if int(BuildVersion.SDK_INT) >= 23:
            pending_flags |= int(PendingIntent.FLAG_IMMUTABLE)
        pending = PendingIntent.getActivity(context, 0, open_intent, pending_flags)

        if int(BuildVersion.SDK_INT) >= 26:
            builder = NotificationBuilder(context, self.CHANNEL_ID)
        else:
            builder = NotificationBuilder(context)
            builder.setPriority(Notification.PRIORITY_LOW)

        endpoint = f"{local_ip}:8080" if local_ip else "Proxy 8080"
        icon_id = int(context.getApplicationInfo().icon)

        return (
            builder.setSmallIcon(icon_id)
            .setContentTitle("SENDPP • Host Local ativo")
            .setContentText(f"{endpoint} • Host local em execução")
            .setContentIntent(pending)
            .setOnlyAlertOnce(True)
            .setOngoing(True)
            .setCategory(Notification.CATEGORY_SERVICE)
            .build()
        )

    @classmethod
    def _acquire_network_locks(cls, context, Context):
        from jnius import autoclass

        PowerManager = autoclass("android.os.PowerManager")
        WifiManager = autoclass("android.net.wifi.WifiManager")

        wake_lock = None
        wifi_lock = None
        errors = []
        try:
            power = context.getSystemService(Context.POWER_SERVICE)
            if power is None:
                errors.append("PowerManager indisponível")
            else:
                wake_lock = power.newWakeLock(
                    PowerManager.PARTIAL_WAKE_LOCK,
                    "SENDPP::HostLocalNetwork",
                )

                wake_lock.setReferenceCounted(False)
                wake_lock.acquire()
                if not cls._lock_is_held(wake_lock):
                    errors.append("WakeLock não foi confirmado")
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            errors.append(f"WakeLock falhou: {detail}")
            cls._release_lock(wake_lock)
            wake_lock = None

        try:
            app_context = context.getApplicationContext()
            wifi = app_context.getSystemService(Context.WIFI_SERVICE)
            if wifi is None:
                errors.append("WifiManager indisponível")
            else:
                wifi_lock = wifi.createWifiLock(
                    WifiManager.WIFI_MODE_FULL_HIGH_PERF,
                    "SENDPP::HostLocalWifi",
                )

                wifi_lock.setReferenceCounted(False)
                wifi_lock.acquire()
                if not cls._lock_is_held(wifi_lock):
                    errors.append("WifiLock não foi confirmado")
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            errors.append(f"WifiLock falhou: {detail}")
            cls._release_lock(wifi_lock)
            wifi_lock = None

        if errors:
            for lock in (wifi_lock, wake_lock):
                cls._release_lock(lock)
            raise RuntimeError(
                "Não foi possível manter CPU/Wi-Fi ativos para o Host Local Android: "
                + "; ".join(errors)
            )

        return wake_lock, wifi_lock

    @staticmethod
    def _lock_is_held(lock) -> bool:
        if lock is None:
            return False
        try:
            return bool(lock.isHeld())
        except Exception:
            return False

    @staticmethod
    def _release_lock(lock) -> None:
        if lock is None:
            return
        try:
            if lock.isHeld():
                lock.release()
        except Exception:
            return

    @staticmethod
    def _schedule_result(callback: PermissionResultCallback, granted: bool) -> None:
        if callback is None:
            return
        try:
            from kivy.clock import Clock

            Clock.schedule_once(lambda _dt: callback(bool(granted)), 0)
        except Exception:
            callback(bool(granted))
