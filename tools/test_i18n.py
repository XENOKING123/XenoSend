"""Behavioural tests for the i18n layer (run with the app venv:  venv312\\Scripts\\python tools\\test_i18n.py modded)."""
import os
import sys

os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")
tree = os.path.abspath(sys.argv[1])
sys.path.insert(0, tree)

from app.i18n import LANGUAGES, SOURCE_LANGUAGE, get_translator, rtl  # noqa: E402

t = get_translator()
failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print("FAIL:", msg)


# Rendered messages exactly as the app produces them (values filled in).
RENDERED = [
    "Pronto para buscar o PS5 na rede local.",
    "Parado • WebKit + ReLapse + Instalador",
    "Preparando • Y2JB_RELAPSE_theme.elf",
    "Executado • kstuff.elf",
    "Aplicado • Update 1.6",
    "Instalado • YouTube US",
    "Falha • Porta inválida. Use somente números.",
    "Falha • Informe o IP do PS5.",
    "Falha • Falha ao conectar em 192.168.4.41:9021: [WinError 10061] refused",
    "Baixando payload • 45%",
    "Baixando kstuff.elf • 12%",
    "Extraindo payload • 100%",
    "Enviando payload • 80%",
    "Enviando PKG • 3%",
    "Instalando PKG no PS5, aguarde  • 100%",   # real output keeps the space before the stripped dots
    "Buscando PS5 na porta 9021...",
    "PS5 encontrado em 192.168.4.41:9021",
    "Nenhum PS5 encontrado em 192.168.4.0/24.",
    "Concluído • 12 arquivo(s)",
    "Ativo • Proxy 192.168.4.20:8080 • abra o Guia do Usuário",
    "Ativo • DNS 192.168.4.20 • abra o Guia do Usuário",
    "Guia acessado • 192.168.4.41 • Proxy 192.168.4.20:8080",
    "A porta 9328 já está em uso por outro serviço no PS5.",
    "Tempo esgotado ao conectar em 192.168.4.41:9021.",
    "Extensão de update do YouTube não suportada. Use: .dat, .zip.",
    "Backup já está no cache local.",
    "kstuff.elf já está no cache local.",
    "Falha ao baixar kstuff.elf: 404 Client Error",
    "Arquivo de payload não encontrado: C:\\x\\y.elf",
    "Payload enviado: kstuff.elf",
    "PS5 encontrado: 192.168.4.41",
    "Nenhum payload disponível.",
    "Payload .js normalmente usa a porta 50000.",
    "Asset interno ausente: pkg-installer.elf",
    "Entrada inválida no ZIP: ../evil",
    "Falha ao enviar o PKG para o PS5: timeout",
]
# strings that legitimately stay identical in some languages (loanword-only content)
MAY_MATCH = {"Preparando • Y2JB_RELAPSE_theme.elf"}

for lang in LANGUAGES:
    if lang.code == SOURCE_LANGUAGE:
        t.set_language("pt")
        for s in RENDERED:
            check(t.translate(s) == s, f"[pt] source language must be identity: {s!r}")
        continue
    t.set_language(lang.code)
    def has_entry(msg):
        cat = t._catalog()
        if cat.get(msg) or cat.get(msg.strip()):
            return True
        return any(pattern.match(msg) for pattern, _target in t._template_index())

    unmatched = [s for s in RENDERED if not has_entry(s)]
    check(not unmatched, f"[{lang.code}] rendered messages with no catalog entry/template: {unmatched}")
    if lang.code not in ("es",):  # Spanish legitimately shares many strings with Portuguese
        identical = [s for s in RENDERED if t.translate(s) == s]
        check(not identical, f"[{lang.code}] untranslated rendered messages: {identical}")
    # values must survive substitution verbatim (IPs, ports, names, percents)
    out = t.translate("PS5 encontrado em 192.168.4.41:9021")
    check("192.168.4.41:9021" in out, f"[{lang.code}] value lost: {out!r}")
    out = t.translate("Baixando kstuff.elf • 12%")
    check("kstuff.elf" in out and "12%" in out, f"[{lang.code}] progress value lost: {out!r}")
    # regression: a "Baixando {name}" alias must not swallow the progress suffix into {name}
    check(out.endswith(" • 12%"), f"[{lang.code}] progress suffix misplaced: {out!r}")
    check(out.count("12%") == 1, f"[{lang.code}] progress value duplicated: {out!r}")
    out = t.translate("Enviando PKG • 47%")
    check(out.endswith(" • 47%"), f"[{lang.code}] progress suffix misplaced: {out!r}")
    out = t.translate("Falha • Porta inválida. Use somente números.")
    check("Porta inválida" not in out, f"[{lang.code}] nested message not translated: {out!r}")
    # unknown text must come back unchanged (never raise, never blank)
    check(t.translate("Texto desconhecido 123") == "Texto desconhecido 123", f"[{lang.code}] fallback broken")
    check(t.translate("") == "", f"[{lang.code}] empty string")
    # shaping is a no-op for LTR languages and reorders/joins for Arabic
    shaped = t("Conexão PS5")
    if lang.rtl:
        check(any(0xFB50 <= ord(c) <= 0xFEFF for c in shaped) or any(0x0600 <= ord(c) <= 0x06FF for c in shaped),
              f"[{lang.code}] expected Arabic text, got {shaped!r}")
        check("PS5" in shaped, f"[{lang.code}] Latin token must survive shaping: {shaped!r}")
        # markup survives shaping
        m = t("Atualizações [color=#FF0000]YouTube[/color] (PPSA01650)")
        check("[color=#FF0000]YouTube[/color]" in m, f"[{lang.code}] markup lost: {m!r}")
    else:
        check(shaped == t.translate("Conexão PS5"), f"[{lang.code}] LTR text must not be altered by shaping")

# observers: KV bindings are re-evaluated on language change
calls = []
t.set_language("en")
t.fbind("_", lambda *a: calls.append(a), "marker")
t.set_language("es")
check(len(calls) == 1 and calls[0][0] == "marker", f"observer not called correctly: {calls}")
t.set_language("es")  # unchanged language: no spurious notification
check(len(calls) == 1, "observer fired for an unchanged language")
check(t.set_language("xx") is False, "unknown language must be rejected")

# dot-stripped aliases (progress lines)
t.set_language("en")
check(t.translate("Baixando payload") == "Downloading payload", f"alias: {t.translate('Baixando payload')!r}")

# Arabic shaping vs the independent oracle (python-bidi) when it is installed
try:
    from bidi.algorithm import get_display
    import arabic_reshaper

    for s in ["اختيار الحمولة وإرسالها إلى PS5", "تم العثور على PS5 في 192.168.0.100:9021", "فشل • خطأ (10061)"]:
        shaped = arabic_reshaper.reshape(s)
        check(rtl.reorder(shaped) == get_display(shaped, base_dir="R"), f"bidi differs from oracle for {s!r}")
except ImportError:
    print("(python-bidi oracle not installed; skipped)")

print("\nRESULT:", "ALL PASSED" if not failures else f"{len(failures)} FAILURE(S)")
sys.exit(1 if failures else 0)
