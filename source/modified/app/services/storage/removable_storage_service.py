import os
import sys
from pathlib import Path
from typing import Iterable, Optional


class RemovableStorageService:
    PROBE_NAME = ".__psmacedo_android_usb_probe__.tmp"

    def find_first_writable(self, *, is_android: bool) -> Optional[Path]:
        candidates = []
        seen = set()

        def add_candidate(raw_path) -> None:
            if not raw_path:
                return
            try:
                path = Path(str(raw_path)).resolve()
            except Exception:
                return
            if is_android and self._is_internal_storage_path(path):
                return
            key = str(path)
            if key in seen:
                return
            seen.add(key)
            candidates.append(path)

        if is_android:
            for candidate in self._android_candidates():
                add_candidate(candidate)

        if sys.platform.startswith("win"):
            for candidate in self._windows_removable_drives():
                add_candidate(candidate)

        storage_root = Path("/storage")
        if storage_root.is_dir():
            try:
                for child in storage_root.iterdir():
                    if not self._is_probably_internal_storage(child.name):
                        add_candidate(child)
            except OSError:
                pass

        media_rw_root = Path("/mnt/media_rw")
        if media_rw_root.is_dir():
            try:
                for child in media_rw_root.iterdir():
                    add_candidate(child)
            except OSError:
                pass

        if is_android:
            for candidate in self._android_mount_file_candidates():
                add_candidate(candidate)
        elif not sys.platform.startswith("win"):
            for candidate in self._desktop_mount_candidates():
                add_candidate(candidate)

        first_existing = None
        for candidate in candidates:
            if candidate.is_dir() and first_existing is None:
                first_existing = candidate
            if not self._probe_writable(candidate):
                continue
            return candidate

        return first_existing

    @staticmethod
    def _is_probably_internal_storage(name: str) -> bool:
        normalized = str(name or "").strip().lower()
        if not normalized:
            return True
        if normalized in {"self", "sdcard", "emulated", "enc_emulated"}:
            return True
        return normalized.isdigit()

    @staticmethod
    def _is_internal_storage_path(path: Path) -> bool:
        try:
            normalized = str(path.resolve()).replace("\\", "/").rstrip("/").lower()
        except Exception:
            return True
        if normalized in {
            "/sdcard",
            "/storage/self",
            "/storage/emulated",
            "/storage/emulated/0",
            "/storage/self/primary",
        }:
            return True
        return normalized.startswith("/storage/emulated/") or normalized.startswith("/storage/self/")

    def _probe_writable(self, directory: Path) -> bool:
        probe = directory / self.PROBE_NAME
        try:
            if not directory.is_dir():
                return False
            with probe.open("wb") as handle:
                handle.write(b"probe")
            try:
                probe.unlink()
            except OSError:
                pass
            return True
        except OSError:
            return False

    @classmethod
    def _windows_removable_drives(cls) -> Iterable[Path]:
        """Yield writable USB storage roots exposed as Windows drive letters.

        Windows reports classic flash drives as DRIVE_REMOVABLE, but many USB
        HDD/SSD enclosures are exposed as DRIVE_FIXED.  Fixed drives are only
        accepted when the Windows storage descriptor confirms BusTypeUsb, so
        internal disks are never selected merely because they are fixed disks.
        """
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            drive_removable = 2
            drive_fixed = 3

            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                drive = f"{letter}:\\"
                if not os.path.exists(drive):
                    continue

                drive_type = int(kernel32.GetDriveTypeW(drive))
                if drive_type == drive_removable:
                    yield Path(drive)
                    continue

                if drive_type == drive_fixed and cls._windows_volume_is_usb(drive):
                    yield Path(drive)
        except Exception:
            return

    @staticmethod
    def _windows_volume_is_usb(drive_root: str) -> bool:
        """Return True only when Windows reports the volume bus as USB."""
        try:
            import ctypes
            from ctypes import wintypes

            class STORAGE_PROPERTY_QUERY(ctypes.Structure):
                _fields_ = [
                    ("PropertyId", ctypes.c_uint32),
                    ("QueryType", ctypes.c_uint32),
                    ("AdditionalParameters", ctypes.c_ubyte * 1),
                ]

            kernel32 = ctypes.windll.kernel32
            kernel32.CreateFileW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            kernel32.CreateFileW.restype = wintypes.HANDLE
            kernel32.DeviceIoControl.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                wintypes.LPVOID,
            ]
            kernel32.DeviceIoControl.restype = wintypes.BOOL

            normalized = str(drive_root or "").strip().rstrip("\\/")
            if len(normalized) != 2 or normalized[1] != ":":
                return False

            volume_path = f"\\\\.\\{normalized}"
            file_share_read = 1
            file_share_write = 2
            open_existing = 3
            invalid_handle_value = ctypes.c_void_p(-1).value
            ioctl_storage_query_property = 0x2D1400
            storage_device_property = 0
            property_standard_query = 0
            bus_type_usb = 7

            handle = kernel32.CreateFileW(
                volume_path,
                0,
                file_share_read | file_share_write,
                None,
                open_existing,
                0,
                None,
            )
            if handle in (None, invalid_handle_value):
                return False

            try:
                query = STORAGE_PROPERTY_QUERY(
                    storage_device_property,
                    property_standard_query,
                    (ctypes.c_ubyte * 1)(0),
                )

                header = (ctypes.c_ubyte * 8)()
                returned = wintypes.DWORD(0)
                ok = kernel32.DeviceIoControl(
                    handle,
                    ioctl_storage_query_property,
                    ctypes.byref(query),
                    ctypes.sizeof(query),
                    ctypes.byref(header),
                    ctypes.sizeof(header),
                    ctypes.byref(returned),
                    None,
                )
                if not ok or returned.value < 8:
                    return False

                descriptor_size = int.from_bytes(bytes(header[4:8]), "little")
                if descriptor_size < 32 or descriptor_size > 65536:
                    return False

                descriptor = (ctypes.c_ubyte * descriptor_size)()
                returned = wintypes.DWORD(0)
                ok = kernel32.DeviceIoControl(
                    handle,
                    ioctl_storage_query_property,
                    ctypes.byref(query),
                    ctypes.sizeof(query),
                    ctypes.byref(descriptor),
                    ctypes.sizeof(descriptor),
                    ctypes.byref(returned),
                    None,
                )
                if not ok or returned.value < 32:
                    return False

                bus_type = int.from_bytes(bytes(descriptor[28:32]), "little")
                return bus_type == bus_type_usb
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False

    @staticmethod
    def _android_candidates() -> Iterable[Path]:
        try:
            from jnius import autoclass

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            activity = PythonActivity.mActivity
            if activity is None:
                return

            try:
                storage_manager = activity.getSystemService(Context.STORAGE_SERVICE)
                volumes = storage_manager.getStorageVolumes() if storage_manager is not None else None
                if volumes is not None:
                    for volume in volumes:
                        if volume is None:
                            continue
                        try:
                            if not bool(volume.isRemovable()):
                                continue
                        except Exception:
                            continue

                        try:
                            state = str(volume.getState() or "").strip().lower()
                        except Exception:
                            state = ""
                        if state and state != "mounted":
                            continue

                        try:
                            directory = volume.getDirectory()
                        except Exception:
                            directory = None
                        if directory is not None:
                            try:
                                absolute = str(directory.getAbsolutePath() or "").strip()
                            except Exception:
                                absolute = ""
                            if absolute:
                                yield Path(absolute)

                        try:
                            uuid = str(volume.getUuid() or "").strip()
                        except Exception:
                            uuid = ""
                        if uuid:
                            yield Path("/storage") / uuid
                            yield Path("/mnt/media_rw") / uuid
            except Exception:
                pass

            try:
                dirs = activity.getExternalFilesDirs(None)
                if dirs is not None:
                    for directory in dirs:
                        if directory is None:
                            continue
                        try:
                            absolute = str(directory.getAbsolutePath() or "").strip()
                        except Exception:
                            continue
                        marker = "/Android/"
                        index = absolute.find(marker)
                        if index > 0:
                            yield Path(absolute[:index])
            except Exception:
                return
        except Exception:
            return

    @staticmethod
    def _android_mount_file_candidates() -> Iterable[Path]:
        try:
            with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    mount_point = str(parts[1] or "").strip()
                    if mount_point.startswith("/storage/") or mount_point.startswith("/mnt/media_rw/"):
                        yield Path(mount_point)
        except OSError:
            return

    @staticmethod
    def _desktop_mount_candidates() -> Iterable[Path]:
        for root in (Path("/media"), Path("/mnt"), Path("/run/media")):
            if not root.is_dir():
                continue
            try:
                for child in root.iterdir():
                    if not child.is_dir():
                        continue
                    yield child
                    try:
                        for grandchild in child.iterdir():
                            if grandchild.is_dir():
                                yield grandchild
                    except OSError:
                        continue
            except OSError:
                continue
