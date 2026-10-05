import os
import subprocess
import sys
from pathlib import Path


class LocalFolderOpenError(RuntimeError):
    pass


class LocalFolderOpener:
    """Open a directory with the native file manager on Windows or Android."""

    def open(self, path: Path, *, is_android: bool) -> None:
        folder = Path(path)
        folder.mkdir(parents=True, exist_ok=True)

        if is_android:
            self._open_android(folder)
            return

        try:
            if sys.platform.startswith("win"):
                os.startfile(str(folder))
                return
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
                return
            subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            raise LocalFolderOpenError(str(folder)) from exc

    @staticmethod
    def _open_android(folder: Path) -> None:
        try:
            from android.storage import primary_external_storage_path
            from jnius import autoclass

            primary_root = Path(primary_external_storage_path()).resolve()
            relative = folder.resolve().relative_to(primary_root)
            doc_id = "primary:" + relative.as_posix()

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            DocumentsContract = autoclass("android.provider.DocumentsContract")

            authority = "com.android.externalstorage.documents"
            tree_uri = DocumentsContract.buildTreeDocumentUri(authority, doc_id)
            directory_uri = DocumentsContract.buildDocumentUriUsingTree(tree_uri, doc_id)

            intent = Intent(Intent.ACTION_VIEW)
            intent.setDataAndType(directory_uri, "vnd.android.document/directory")
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            PythonActivity.mActivity.startActivity(intent)
        except Exception as exc:
            raise LocalFolderOpenError(str(folder)) from exc
