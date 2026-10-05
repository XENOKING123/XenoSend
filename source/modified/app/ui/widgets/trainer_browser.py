"""Trainer browser: search the PS5 cheat-trainer catalog and, when reachable, toggle
cheats live through CheatRunner running on the console.

Structural pattern copied from ``payload_selector.py`` (an ``MDCard`` + ``ScrollView`` +
``MDList`` inside a centered ``ModalView``, with the same ``_surface_color()`` theme
helper). Unlike that file, every widget here is built entirely in Python — no new rules
are added to ``main.kv`` — so this module cannot collide with concurrent edits to that
file's header/card sections.

The live CheatRunner connection (Connect / toggle / disable-all) is a faithful port of
the protocol documented in the user's own XENOKING project (see
``app.services.xeno.cheatrunner_client``) and has **not** been exercised against a real
PS5 this session. Every network call already fails soft inside the client; this module
additionally never lets a live-connection failure block the static, read-only cheat list
that always comes from the bundled catalog.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional, Sequence

from kivy.clock import Clock
from kivy.core.audio import SoundLoader
from kivy.graphics import Color, Ellipse, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.image import Image
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import get_color_from_hex
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.list import MDList
from kivymd.uix.selectioncontrol import MDSwitch

from app.catalogs.xeno_trainer_catalog import TrainerGame
from app.i18n import get_translator, tr
from app.ui.widgets.premium_button import PremiumIconButton, PremiumRaisedButton

_SFX_DIR = Path(__file__).resolve().parents[2] / "assets" / "xeno" / "sfx"
_sfx_cache: dict = {}


def _toggle_sound(on: bool):
    """Lazily loads and caches on.wav/off.wav. Returns None (and never raises) if the
    audio backend or the asset file isn't available — a missing sound must never block
    a toggle."""
    key = "on" if on else "off"
    if key not in _sfx_cache:
        path = _SFX_DIR / f"{key}.wav"
        try:
            _sfx_cache[key] = SoundLoader.load(str(path)) if path.is_file() else None
        except Exception:
            _sfx_cache[key] = None
    return _sfx_cache[key]


def _play_toggle_sound(on: bool) -> None:
    sound = _toggle_sound(on)
    if sound is not None:
        try:
            sound.stop()
            sound.play()
        except Exception:
            pass

# No virtualization backs this list (same as payload_selector.py's MDList), so the number
# of rows actually built is capped to keep the UI thread responsive against a 2,436-entry
# catalog. Narrowing the search shows the rest.
MAX_VISIBLE_ROWS = 60

CREDITS_TEXT = (
    "CheatRunner by maj0r (Discord: callmemaj0r) — github.com/notmaj0r/CheatRunner. "
    "Base de cheats de etaHEN PS5 Cheats e HEN Cheats Collection, via as comunidades do "
    "Discord etaHEN e GoldHEN. Obrigado a LM (lightningmods), Buzzer (buzzer-re), Super "
    "Death, GoldHEN Team, Yharnam, PS4Trainer e todos os criadores de cheats da cena. "
    "Este app não cria cheats — ele reúne e aplica o trabalho da comunidade. Problemas "
    "específicos de um cheat devem ser reportados aos autores originais."
)

_PLACEHOLDER_COLOR = get_color_from_hex("#2A2F38")


def _theme():
    app = MDApp.get_running_app()
    return getattr(app, "theme", None)


def _surface_color():
    theme = _theme()
    return list(theme.surface) if theme is not None else get_color_from_hex("#191C21")


def _input_color():
    theme = _theme()
    return list(theme.input) if theme is not None else get_color_from_hex("#0F1630")


def _accent_color():
    theme = _theme()
    return list(theme.accent) if theme is not None else get_color_from_hex("#F38B1A")


def _text_primary_color():
    theme = _theme()
    return list(theme.text_primary) if theme is not None else get_color_from_hex("#F2F5FF")


def _text_muted_color():
    theme = _theme()
    return list(theme.text_muted) if theme is not None else get_color_from_hex("#8E9AC0")


def _success_color():
    theme = _theme()
    return list(theme.success) if theme is not None else get_color_from_hex("#79C98D")


def _danger_color():
    theme = _theme()
    return list(theme.danger) if theme is not None else get_color_from_hex("#E47C73")


def _cheats_badge_text(count: int) -> str:
    translator = get_translator()
    noun = "cheat" if count == 1 else "cheats"
    return translator.shape(f"{count} {translator.translate(noun)}")


def _ellipsized(label: MDLabel) -> MDLabel:
    """Labels built in Python (no KV rule) need an explicit text_size binding for
    ``shorten``/wrapping to have any effect — in KV this is normally just
    ``text_size: self.size``."""
    label.text_size = label.size
    label.bind(size=lambda instance, value: setattr(instance, "text_size", value))
    return label


class _ThumbnailBox(MDBoxLayout):
    """Fixed-size cover slot: a flat placeholder until (if ever) a real image lands."""

    def __init__(self, *, box_size=None, **kwargs):
        size = box_size or (dp(40), dp(40))
        super().__init__(size_hint=(None, None), size=size, **kwargs)
        with self.canvas.before:
            self._color_instr = Color(*_PLACEHOLDER_COLOR)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(6)])
        self.bind(pos=self._sync_rect, size=self._sync_rect)

    def _sync_rect(self, *_args) -> None:
        self._rect.pos = self.pos
        self._rect.size = self.size

    def set_image(self, path: str) -> None:
        self.clear_widgets()
        self.add_widget(Image(source=path, size_hint=(1, 1), allow_stretch=True, keep_ratio=False))


class TrainerGameRow(ButtonBehavior, MDBoxLayout):
    """One row in the browser list: cover thumbnail, title, cheats-count badge."""

    def __init__(self, *, game: TrainerGame, on_press_game: Callable[[TrainerGame], None], **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(52),
            spacing=dp(10),
            padding=(dp(8), dp(4), dp(8), dp(4)),
            **kwargs,
        )
        self.game = game
        self._on_press_game = on_press_game
        self._thumb = _ThumbnailBox()
        self.add_widget(self._thumb)

        info = MDBoxLayout(orientation="vertical", spacing=dp(2))
        info.add_widget(
            _ellipsized(
                MDLabel(
                    text=game.title or game.id,
                    font_size="13sp",
                    bold=True,
                    theme_text_color="Custom",
                    text_color=_text_primary_color(),
                    shorten=True,
                    shorten_from="right",
                    size_hint_y=None,
                    height=dp(20),
                )
            )
        )
        info.add_widget(
            MDLabel(
                text=_cheats_badge_text(game.cheats_total),
                font_size="11sp",
                theme_text_color="Custom",
                text_color=_text_muted_color(),
                size_hint_y=None,
                height=dp(16),
            )
        )
        self.add_widget(info)
        self.bind(on_release=lambda *_args: self._on_press_game(self.game))

    def set_thumbnail(self, path: str) -> None:
        self._thumb.set_image(path)


class _StatusDot(Widget):
    """A small filled circle: green when a cheat is ON, red/danger when it's OFF. Drawn
    with canvas primitives (same technique as ``_ThumbnailBox``) rather than relying on
    KivyMD switch internals, which vary by version."""

    def __init__(self, *, on: bool, **kwargs):
        super().__init__(size_hint=(None, None), size=(dp(10), dp(10)), **kwargs)
        with self.canvas:
            self._color_instr = Color(*self._color_for(on))
            self._dot = Ellipse(pos=self.pos, size=self.size)
        self.bind(pos=self._sync, size=self._sync)

    @staticmethod
    def _color_for(on: bool):
        return _success_color() if on else _danger_color()

    def _sync(self, *_args) -> None:
        self._dot.pos = self.pos
        self._dot.size = self.size

    def set_on(self, on: bool) -> None:
        self._color_instr.rgba = self._color_for(on)


class TrainerCheatRow(MDBoxLayout):
    """One live cheat row: a green/red status dot, name, and a real KivyMD switch wired
    to toggle_cheat(). Flipping the switch plays the same on.wav/off.wav cue XENO TOOL
    uses, immediately (optimistic — not gated on the network round-trip confirming)."""

    def __init__(self, *, cheat, on_toggle: Callable[[object, bool], None], **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(34),
            spacing=dp(8),
            padding=(dp(4), 0, dp(4), 0),
            **kwargs,
        )
        self.cheat = cheat
        self._dot = _StatusDot(on=bool(cheat.enabled))
        self._dot.pos_hint = {"center_y": 0.5}
        self.add_widget(self._dot)
        self.add_widget(
            _ellipsized(
                MDLabel(
                    text=cheat.name or f"#{cheat.index}",
                    font_size="12sp",
                    theme_text_color="Custom",
                    text_color=_text_primary_color(),
                    shorten=True,
                    shorten_from="right",
                )
            )
        )
        switch = MDSwitch(active=bool(cheat.enabled), size_hint=(None, None), size=(dp(44), dp(24)))
        switch.pos_hint = {"center_y": 0.5}
        switch.bind(active=self._on_switch_changed)
        self._on_toggle = on_toggle
        self.add_widget(switch)

    def _on_switch_changed(self, _instance, value: bool) -> None:
        self._dot.set_on(value)
        _play_toggle_sound(value)
        self._on_toggle(self.cheat, value)


def _make_note_label(text: str) -> MDLabel:
    label = MDLabel(
        text=text,
        font_size="11sp",
        theme_text_color="Custom",
        text_color=_text_muted_color(),
        size_hint_y=None,
        height=dp(34),
        valign="middle",
    )
    label.bind(width=lambda inst, value: setattr(inst, "text_size", (value, None)))
    return label


def _make_static_cheat_label(name: str) -> MDLabel:
    return _ellipsized(
        MDLabel(
            text=f"• {name}",
            font_size="12sp",
            theme_text_color="Custom",
            text_color=_text_primary_color(),
            size_hint_y=None,
            height=dp(24),
            shorten=True,
            shorten_from="right",
        )
    )


class TrainerBrowserModal(ModalView):
    """Search + list modal; tapping a row opens a :class:`TrainerDetailModal` on top."""

    WIDTH_RATIO = 0.94
    HEIGHT_RATIO = 0.88

    def __init__(
        self,
        *,
        catalog,
        cover_service,
        cheatrunner_client,
        host_provider: Callable[[], str],
        port_provider: Callable[[], str],
        on_send_cheatrunner: Callable[[Optional[Callable[[str, Sequence[float]], None]]], None],
        **kwargs,
    ) -> None:
        super().__init__(
            size_hint=(self.WIDTH_RATIO, self.HEIGHT_RATIO),
            auto_dismiss=True,
            background_color=(0, 0, 0, 0),
            **kwargs,
        )
        self._catalog = catalog
        self._cover_service = cover_service
        self._cheatrunner_client = cheatrunner_client
        self._host_provider = host_provider
        self._port_provider = port_provider
        self._on_send_cheatrunner = on_send_cheatrunner
        self._detail_modal: Optional["TrainerDetailModal"] = None

        surface = MDCard(
            orientation="vertical",
            size_hint=(1, 1),
            padding=dp(10),
            spacing=dp(8),
            radius=[dp(10), dp(10), dp(10), dp(10)],
            md_bg_color=_surface_color(),
            elevation=8,
        )

        surface.add_widget(
            MDLabel(
                text=tr("Trainers"),
                bold=True,
                font_size="16sp",
                theme_text_color="Custom",
                text_color=_accent_color(),
                size_hint_y=None,
                height=dp(24),
            )
        )

        search_wrap = MDCard(
            radius=[dp(10), dp(10), dp(10), dp(10)],
            md_bg_color=_input_color(),
            elevation=0,
            size_hint_y=None,
            height=dp(36),
            padding=(dp(10), 0),
        )
        self._search_input = TextInput(
            hint_text=tr("Buscar jogo..."),
            multiline=False,
            background_color=(0, 0, 0, 0),
            foreground_color=_text_primary_color(),
            hint_text_color=_text_muted_color(),
            cursor_color=_accent_color(),
            font_size="14sp",
            padding=[0, dp(8), 0, 0],
        )
        self._search_input.bind(text=lambda _instance, value: self._refresh_rows(value))
        search_wrap.add_widget(self._search_input)
        surface.add_widget(search_wrap)

        scroll = ScrollView(
            do_scroll_x=False,
            do_scroll_y=True,
            bar_width=dp(2),
            bar_color=_accent_color(),
            bar_inactive_color=get_color_from_hex("#3A404A"),
        )
        self._item_list = MDList(size_hint_y=None, spacing=dp(2))
        self._item_list.bind(minimum_height=self._item_list.setter("height"))
        scroll.add_widget(self._item_list)
        surface.add_widget(scroll)

        self._hint_label = MDLabel(
            text="",
            font_size="10sp",
            theme_text_color="Custom",
            text_color=_text_muted_color(),
            size_hint_y=None,
            height=dp(16),
            opacity=0,
        )
        surface.add_widget(self._hint_label)

        self.add_widget(surface)
        self._refresh_rows("")

    def _refresh_rows(self, query: str) -> None:
        self._item_list.clear_widgets()
        games = self._catalog.search(query) if str(query or "").strip() else self._catalog.all_games()
        visible = games[:MAX_VISIBLE_ROWS]
        for game in visible:
            row = TrainerGameRow(game=game, on_press_game=self._open_detail)
            self._item_list.add_widget(row)
            threading.Thread(
                target=self._load_cover_worker, args=(row, game.title), daemon=True
            ).start()

        if not games:
            self._hint_label.text = tr("Nenhum jogo encontrado.")
            self._hint_label.opacity = 1
        elif len(games) > len(visible):
            self._hint_label.text = tr(
                "Mostrando {shown} de {total} — refine a busca.",
                shown=len(visible),
                total=len(games),
            )
            self._hint_label.opacity = 1
        else:
            self._hint_label.opacity = 0

    def _load_cover_worker(self, row: TrainerGameRow, title: str) -> None:
        try:
            path = self._cover_service.fetch(title)
        except Exception:
            path = None
        if path is None:
            return
        Clock.schedule_once(lambda _dt: self._apply_cover(row, path), 0)

    @staticmethod
    def _apply_cover(row: TrainerGameRow, path) -> None:
        if row.parent is None:
            return
        row.set_thumbnail(str(path))

    def _open_detail(self, game: TrainerGame) -> None:
        try:
            if self._detail_modal is not None:
                self._detail_modal.dismiss()
        except Exception:
            pass
        self._detail_modal = TrainerDetailModal(
            game=game,
            cheatrunner_client=self._cheatrunner_client,
            cover_service=self._cover_service,
            host_provider=self._host_provider,
            port_provider=self._port_provider,
            on_send_cheatrunner=self._on_send_cheatrunner,
        )
        self._detail_modal.open()


class TrainerDetailModal(ModalView):
    """Per-game detail view: live toggles when CheatRunner is reachable, else a
    read-only static cheat list from the catalog — plus the CheatRunner.elf sender and
    the required credits footer.
    """

    WIDTH_RATIO = 0.94
    HEIGHT_RATIO = 0.88

    def __init__(
        self,
        *,
        game: TrainerGame,
        cheatrunner_client,
        cover_service,
        host_provider: Callable[[], str],
        port_provider: Callable[[], str],
        on_send_cheatrunner: Callable[[Optional[Callable[[str, Sequence[float]], None]]], None],
        **kwargs,
    ) -> None:
        super().__init__(
            size_hint=(self.WIDTH_RATIO, self.HEIGHT_RATIO),
            auto_dismiss=True,
            background_color=(0, 0, 0, 0),
            **kwargs,
        )
        self.game = game
        self._client = cheatrunner_client
        self._cover_service = cover_service
        self._host_provider = host_provider
        self._port_provider = port_provider
        self._on_send_cheatrunner = on_send_cheatrunner
        self._connecting = False
        self._live_cheats_available = False

        surface = MDCard(
            orientation="vertical",
            size_hint=(1, 1),
            padding=dp(10),
            spacing=dp(6),
            radius=[dp(10), dp(10), dp(10), dp(10)],
            md_bg_color=_surface_color(),
            elevation=8,
        )

        header = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(10))
        self._thumb = _ThumbnailBox(box_size=(dp(44), dp(44)))
        header.add_widget(self._thumb)
        title_box = MDBoxLayout(orientation="vertical")
        title_box.add_widget(
            _ellipsized(
                MDLabel(
                    text=game.title or game.id,
                    bold=True,
                    font_size="14sp",
                    theme_text_color="Custom",
                    text_color=_text_primary_color(),
                    shorten=True,
                    shorten_from="right",
                )
            )
        )
        title_box.add_widget(
            MDLabel(
                text=game.id,
                font_size="10sp",
                theme_text_color="Custom",
                text_color=_text_muted_color(),
            )
        )
        header.add_widget(title_box)
        close_btn = PremiumIconButton(icon="close")
        close_btn.bind(on_release=lambda *_args: self.dismiss())
        header.add_widget(close_btn)
        surface.add_widget(header)
        threading.Thread(target=self._load_cover_worker, daemon=True).start()

        conn_row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(32), spacing=dp(8))
        host = (host_provider() or "").strip()
        port = (port_provider() or "").strip()
        conn_text = f"{host}:{port}" if host else tr("IP do PS5 não configurado")
        self._conn_label = MDLabel(
            text=conn_text,
            font_size="12sp",
            theme_text_color="Custom",
            text_color=_text_muted_color(),
        )
        conn_row.add_widget(self._conn_label)
        self._attach_dot = _StatusDot(on=False)
        self._attach_dot.pos_hint = {"center_y": 0.5}
        conn_row.add_widget(self._attach_dot)
        self._connect_btn = PremiumRaisedButton(
            text=tr("Anexar"), size_hint=(None, None), size=(dp(90), dp(32))
        )
        self._connect_btn.bind(on_release=lambda *_args: self._start_connect())
        conn_row.add_widget(self._connect_btn)
        self._detach_btn = PremiumRaisedButton(
            text=tr("Desanexar"),
            size_hint=(None, None),
            size=(dp(90), dp(32)),
            disabled=True,
        )
        self._detach_btn.bind(on_release=lambda *_args: self._detach())
        conn_row.add_widget(self._detach_btn)
        surface.add_widget(conn_row)

        self._status_label = _ellipsized(
            MDLabel(
                text=tr("Toque em Anexar para ler o estado em tempo real."),
                font_size="11sp",
                theme_text_color="Custom",
                text_color=_text_muted_color(),
                size_hint_y=None,
                height=dp(16),
                shorten=True,
                shorten_from="right",
            )
        )
        surface.add_widget(self._status_label)

        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True)
        self._cheat_list = MDList(size_hint_y=None, spacing=dp(2))
        self._cheat_list.bind(minimum_height=self._cheat_list.setter("height"))
        scroll.add_widget(self._cheat_list)
        surface.add_widget(scroll)

        self._disable_all_btn = PremiumRaisedButton(
            text=tr("Desativar todos"),
            size_hint=(1, None),
            height=dp(32),
            disabled=True,
        )
        self._disable_all_btn.bind(on_release=lambda *_args: self._start_disable_all())
        surface.add_widget(self._disable_all_btn)

        send_btn = PremiumRaisedButton(
            text=tr("Enviar CheatRunner.elf para o PS5"),
            size_hint=(1, None),
            height=dp(32),
        )
        send_btn.bind(on_release=lambda *_args: self._start_send_cheatrunner())
        surface.add_widget(send_btn)

        credits_label = MDLabel(
            text=tr(CREDITS_TEXT),
            font_size="9sp",
            theme_text_color="Custom",
            text_color=_text_muted_color(),
            size_hint_y=None,
            valign="top",
        )
        credits_label.bind(
            width=lambda inst, value: setattr(inst, "text_size", (value, None)),
            texture_size=lambda inst, value: setattr(inst, "height", value[1]),
        )
        surface.add_widget(credits_label)

        self.add_widget(surface)
        self._show_static_cheats()

    # -- cover art --------------------------------------------------------------------
    def _load_cover_worker(self) -> None:
        try:
            path = self._cover_service.fetch(self.game.title)
        except Exception:
            path = None
        if path is None:
            return
        Clock.schedule_once(lambda _dt: self._thumb.set_image(str(path)), 0)

    # -- static (catalog) cheat list ---------------------------------------------------
    def _show_static_cheats(self) -> None:
        self._cheat_list.clear_widgets()
        fmt = self.game.best_format()
        if fmt is None:
            self._cheat_list.add_widget(
                _make_note_label(tr("Nenhum cheat estático disponível para este jogo."))
            )
            return
        self._cheat_list.add_widget(
            _make_note_label(
                tr(
                    "Lista estática do catálogo. Anexe ao CheatRunner para alternar "
                    "cheats em tempo real."
                )
            )
        )
        for name in fmt.cheats:
            self._cheat_list.add_widget(_make_static_cheat_label(name))

    # -- live connection ----------------------------------------------------------------
    def _set_status(self, text: str, color) -> None:
        self._status_label.text = text
        self._status_label.text_color = color

    def _start_connect(self) -> None:
        if self._connecting:
            return
        host = (self._host_provider() or "").strip()
        if not host:
            self._set_status(tr("Informe o IP do PS5 na tela principal."), _danger_color())
            return

        self._connecting = True
        self._connect_btn.disabled = True
        self._set_status(tr("Anexando ao CheatRunner..."), _text_muted_color())

        def worker() -> None:
            try:
                if not self._client.is_up(host):
                    message = tr(
                        "CheatRunner não está acessível em {host} (porta 9999).", host=host
                    )
                    Clock.schedule_once(
                        lambda _dt, m=message: self._finish_connect_error(m), 0
                    )
                    return
                # attach() launches the game first if it isn't already running, then polls
                # until CheatRunner actually has cheats loaded for it — a real "attach",
                # not just a one-shot state read.
                result = self._client.attach(host, self.game.id)
                cheats = self._client.cheat_state(host, self.game.id) if result.ok else ()
            except Exception as exc:
                message = str(exc).strip() or tr("Falha ao anexar ao CheatRunner.")
                Clock.schedule_once(lambda _dt, m=message: self._finish_connect_error(m), 0)
                return
            Clock.schedule_once(
                lambda _dt, c=cheats, launched=result.launched: self._finish_connect(c, launched), 0
            )

        threading.Thread(target=worker, daemon=True, name="trainer-connect").start()

    def _finish_connect(self, cheats, launched: bool) -> None:
        self._connecting = False
        self._connect_btn.disabled = False
        if not cheats:
            self._live_cheats_available = False
            self._disable_all_btn.disabled = True
            self._attach_dot.set_on(False)
            self._set_status(
                tr(
                    "Anexado, mas nenhum cheat foi retornado. Mostrando lista estática."
                ),
                _text_muted_color(),
            )
            self._show_static_cheats()
            return
        self._live_cheats_available = True
        self._disable_all_btn.disabled = False
        self._detach_btn.disabled = False
        self._attach_dot.set_on(True)
        status = (
            tr("Jogo iniciado e anexado • {count} cheat(s).", count=len(cheats))
            if launched
            else tr("Anexado • {count} cheat(s).", count=len(cheats))
        )
        self._set_status(status, _success_color())
        self._render_live_cheats(cheats)

    def _finish_connect_error(self, message: str) -> None:
        self._connecting = False
        self._connect_btn.disabled = False
        self._live_cheats_available = False
        self._disable_all_btn.disabled = True
        self._attach_dot.set_on(False)
        self._set_status(message, _danger_color())
        self._show_static_cheats()

    def _detach(self) -> None:
        """Client-side only: CheatRunner has no real session to tear down server-side
        (see the module docstring / ``cheatrunner_client.attach()``). Detach just stops
        treating this view as live and goes back to the static catalog list."""
        self._live_cheats_available = False
        self._disable_all_btn.disabled = True
        self._detach_btn.disabled = True
        self._attach_dot.set_on(False)
        self._set_status(tr("Desanexado."), _text_muted_color())
        self._show_static_cheats()

    def _render_live_cheats(self, cheats) -> None:
        self._cheat_list.clear_widgets()
        for cheat in cheats:
            self._cheat_list.add_widget(TrainerCheatRow(cheat=cheat, on_toggle=self._start_toggle))

    def _start_toggle(self, cheat, new_value: bool) -> None:
        host = (self._host_provider() or "").strip()
        if not host:
            return

        def worker() -> None:
            try:
                self._client.toggle_cheat(host, self.game.id, cheat.index, new_value)
                cheats = self._client.cheat_state(host, self.game.id)
            except Exception as exc:
                message = str(exc).strip() or tr("Falha ao alternar cheat.")
                Clock.schedule_once(lambda _dt, m=message: self._set_status(m, _danger_color()), 0)
                return
            Clock.schedule_once(lambda _dt, c=cheats: self._render_live_cheats(c), 0)

        threading.Thread(target=worker, daemon=True, name="trainer-toggle").start()

    def _start_disable_all(self) -> None:
        host = (self._host_provider() or "").strip()
        if not host:
            return
        self._disable_all_btn.disabled = True

        def worker() -> None:
            try:
                self._client.disable_all(host, self.game.id)
                cheats = self._client.cheat_state(host, self.game.id)
            except Exception as exc:
                message = str(exc).strip() or tr("Falha ao desativar todos os cheats.")
                Clock.schedule_once(
                    lambda _dt, m=message: self._finish_disable_all_error(m), 0
                )
                return
            Clock.schedule_once(lambda _dt, c=cheats: self._finish_disable_all(c), 0)

        threading.Thread(target=worker, daemon=True, name="trainer-disable-all").start()

    def _finish_disable_all(self, cheats) -> None:
        self._disable_all_btn.disabled = not self._live_cheats_available
        self._render_live_cheats(cheats)

    def _finish_disable_all_error(self, message: str) -> None:
        self._disable_all_btn.disabled = not self._live_cheats_available
        self._set_status(message, _danger_color())

    # -- CheatRunner.elf sender ----------------------------------------------------------
    def _start_send_cheatrunner(self) -> None:
        self._on_send_cheatrunner(self._set_status)
