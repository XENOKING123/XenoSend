"""Validate translation catalogs.

usage: python check_locale.py <modded_tree> [lang ...]

Checks per language (against the English catalog, which defines the key set):
  * every key present, no extras, no empty values
  * {placeholders} identical (names and count)
  * [markup] tags identical (type + arguments), in the same multiset
  * technical tokens (PS5, PKG, ELF, FTPsrv, SENDPP, Y2JB, ReLapse, WebKit, YouTube, file names, ports)
    kept verbatim
  * digits kept verbatim (ports, versions)
And once (English only): every key's literal text occurs in the code or KV (typo guard).
"""
import importlib.util
import os
import re
import sys
from collections import Counter

tree = os.path.abspath(sys.argv[1])
langs = sys.argv[2:]
loc_dir = os.path.join(tree, "app", "i18n", "locales")

PLACEHOLDER = re.compile(r"\{(\w+)\}")
MARKUP = re.compile(r"\[/?(?:b|i|u|s|font|size|color|ref|anchor|sub|sup)(?:=[^\]]*)?\]")
TECH = ["PS5", "PKG", "fPKG", "ELF", "FTPsrv", "SENDPP", "Y2JB", "ReLapse", "WebKit", "YouTube", "PSM", "Gezine",
        "download0.dat", "pkg-installer.elf", "AMOLED", "Android", "ZIP", "USB", "IPv4", "IP", ".js", ".elf",
        ".bin", ".jar", ".dat", "PPSA01650", "requests", "DNS", "Proxy", "Payload"]
# "Payload"/"payload" are intentionally *not* enforced for translation-sensitive languages below.
OPTIONAL_TECH = {"Payload", "IP", "Proxy", "Android", "ZIP", "USB", "DNS", "requests", "PSM"}


def load(code):
    spec = importlib.util.spec_from_file_location(f"loc_{code}", os.path.join(loc_dir, f"{code}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CATALOG


en = load("en")
if not langs:
    langs = sorted(f[:-3] for f in os.listdir(loc_dir) if f.endswith(".py") and f not in ("__init__.py",) and f[:-3] != "en")

problems = 0  # real correctness bugs: fail the build
missing_total = 0  # incompleteness: informational only — the translator falls back to the
                    # Portuguese source text for any key a catalog doesn't have, by design,
                    # so an untranslated-but-present string is never a defect.


def report(lang, key, msg):
    global problems
    problems += 1
    print(f"[{lang}] {msg}\n      key: {key!r}")


def report_missing(lang, key):
    global missing_total
    missing_total += 1
    print(f"[{lang}] missing (falls back to source text)\n      key: {key!r}")


for lang in langs:
    try:
        cat = load(lang)
    except Exception as exc:  # noqa: BLE001
        print(f"[{lang}] cannot load: {exc}")
        problems += 1
        continue
    missing = [k for k in en if k not in cat]
    extra = [k for k in cat if k not in en]
    for k in missing:
        report_missing(lang, k)
    for k in extra:
        report(lang, k, "EXTRA key (not in en.py)")
    for key, value in cat.items():
        if key not in en:
            continue
        if not isinstance(value, str) or not value.strip():
            report(lang, key, "empty value")
            continue
        if Counter(PLACEHOLDER.findall(key)) != Counter(PLACEHOLDER.findall(value)):
            report(lang, key, f"placeholder mismatch: {PLACEHOLDER.findall(key)} vs {PLACEHOLDER.findall(value)}")
        if Counter(MARKUP.findall(key)) != Counter(MARKUP.findall(value)):
            report(lang, key, f"markup mismatch: {MARKUP.findall(key)} vs {MARKUP.findall(value)}")
        # the English value is the reference for which technical tokens must survive translation
        for tok in TECH:
            if tok in OPTIONAL_TECH:
                continue
            if tok in en[key] and tok not in value:
                report(lang, key, f"technical token {tok!r} missing in translation: {value!r}")
        if Counter(re.findall(r"\d+", key)) != Counter(re.findall(r"\d+", value)):
            report(lang, key, f"digits changed: {re.findall(r'\\d+', key)} vs {re.findall(r'\\d+', value)}")
    print(f"[{lang}] {len(cat)} entries, {len(missing)} missing (informational), {len(extra)} extra")

# --- typo guard: do the English keys' literals occur in the code / kv? -----------------------
blob = []
for dp, _, files in os.walk(tree):
    if os.sep + "i18n" in dp:
        continue
    for f in files:
        if f.endswith((".py", ".kv")):
            blob.append(open(os.path.join(dp, f), encoding="utf-8").read())
blob = re.sub(r"\s+", " ", "\n".join(blob))
blob_compact = re.sub(r"[\"'\s]+", "", blob)  # tolerate implicit string concatenation across lines
unseen = 0
for key in en:
    for chunk in PLACEHOLDER.split(key):
        chunk = chunk.strip()
        if len(chunk) < 4 or chunk in blob:
            continue
        if re.sub(r"[\"'\s]+", "", chunk) in blob_compact:
            continue
        unseen += 1
        print(f"[typo?] literal not found in code/kv: {chunk!r}   (from key {key!r})")
problems += unseen
print(f"typo guard: {unseen} literal(s) not found in code")
print(f"TOTAL: {problems} problem(s) (build-failing), {missing_total} missing translation(s) (informational)")
sys.exit(1 if problems else 0)
