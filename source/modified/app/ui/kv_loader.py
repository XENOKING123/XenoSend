from pathlib import Path

from kivy.lang import Builder

from app.ui.main_screen import MainScreen
from app.ui.widgets.premium_button import PremiumIconButton, PremiumRaisedButton


def load_all_kv() -> None:
    kv_path = Path(__file__).resolve().parent / "kv" / "main.kv"
    Builder.load_file(str(kv_path))
