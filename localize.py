"""Локальная установка русского интерфейса Google Antigravity 2.33.0 (Windows)."""
import argparse
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
STOCK = 'b33c81600e82e65593aa8430ef01b37d6b28d9d98f0faf45e25957783b71e64b'
PATCHED = 'bfd8c95eb9cdc9121af2a2248828b5650d004486b41198b1c2999eaadace42a6'
SERVER = 'eb6d986dfc5a859c6e9b1b36a0601f5c362993cc16eb8962ad554c9141defc9c'
RECIPE = 'fb1d8b59bf70b2da025266971038f4c0c4b530c4132f0b1fa9c768b1e3221569'
WEB_ZIP = 'a7a6133178bdbd5e4d4f56155aae121c8076fea0ec488f969a7cc706cd6afe3a'
WEB_OFFSET, WEB_SIZE = 178093044, 6027905
BUNDLE = 'web_bundle_ru_233'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def plain(path):
    require(not path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT,
            f'Обнаружена ссылка или точка повторной обработки: {path}')


def verify_tree(root, expected):
    plain(root)
    seen = set()
    dirs = {p for key in expected for p in Path(key).parents}
    for path in root.rglob('*'):
        plain(path)
        relative = path.relative_to(root)
        if path.is_dir():
            require(relative in dirs, f'Дополнительная папка: {relative}')
        else:
            key = relative.as_posix()
            require(key in expected and file_hash(path) == expected[key],
                    f'Неизвестный или изменённый файл: {relative}')
            seen.add(key)
    require(seen == set(expected), 'Неполный комплект веб-ресурсов')


def translate(data, rule, strings):
    require(sha(data) == rule['before'], 'Неизвестная версия переводимого ресурса')
    source = data.decode('utf-8')
    parts, cursor = [], 0
    for offset, size, index in rule['edits']:
        require(cursor <= offset <= offset + size <= len(source), 'Повреждена карта перевода')
        parts.extend((source[cursor:offset], strings[index]))
        cursor = offset + size
    parts.append(source[cursor:])
    output = ''.join(parts).encode('utf-8')
    require(sha(output) == rule['after'], 'Ошибка контрольной суммы переведённого ресурса')
    return output


def asar_parts(raw):
    length = struct.unpack_from('<I', raw, 12)[0]
    header = json.loads(raw[16:16+length])
    start = 8 + struct.unpack_from('<I', raw, 4)[0]
    return header, raw[start:]


def member(header, name):
    for part in name.split('/'):
        header = header['files'][part]
    return header


def contents(payload, entry):
    start = int(entry['offset'])
    return payload[start:start+entry['size']]


def build_asar(raw, recipe):
    header, payload = asar_parts(raw)
    payload = bytearray(payload)
    for name, rule in recipe['asar'].items():
        entry = member(header, name)
        data = translate(contents(payload, entry), rule, recipe['strings'])
        entry.update(size=len(data), offset=str(len(payload)))
        payload.extend(data)
        integrity = entry['integrity']
        block = integrity['blockSize']
        integrity.update(hash=sha(data), blocks=[sha(data[i:i+block]) for i in range(0, len(data), block)])
    encoded = json.dumps(header, ensure_ascii=False, separators=(',', ':')).encode()
    padded = (len(encoded)+3)//4*4
    return struct.pack('<4I', 4, padded+8, padded+4, len(encoded)) + encoded.ljust(padded, b'\0') + payload


def build_web(server, dest, recipe):
    with server.open('rb') as stream:
        stream.seek(WEB_OFFSET)
        data = stream.read(WEB_SIZE)
    require(sha(data) == WEB_ZIP, 'Встроенные веб-ресурсы отличаются от сборки 2.33.0')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in recipe['files']:
            content = archive.read(name)
            if name in recipe['web']:
                content = translate(content, recipe['web'][name], recipe['strings'])
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    verify_tree(dest, recipe['files'])


def closed(install):
    shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    query = """
    $ErrorActionPreference='Stop'
    $active=Get-CimInstance Win32_Process -Filter "Name='Antigravity.exe' OR Name='language_server.exe'"
    foreach ($p in $active) {
        if (!$p.ExecutablePath -or $p.ExecutablePath.StartsWith($env:AGY_CHECK_ROOT,[StringComparison]::OrdinalIgnoreCase)) { exit 2 }
    }
    """
    result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-Command', query],
                            env={**os.environ, 'AGY_CHECK_ROOT':str(install) + os.sep}, capture_output=True)
    require(result.returncode == 0, 'Полностью закройте Antigravity, включая значок у часов. Не удалось подтвердить остановку процессов.')


def operate(action, install):
    install = install.absolute()
    res = install / 'resources'
    archive, server, bundle = res/'app.asar', res/'bin/language_server.exe', res/BUNDLE
    for path in (install, res, archive, res/'bin', server):
        require(path.exists(), f'Файл или папка не найдены: {path}')
        plain(path)
    raw = archive.read_bytes()
    current = sha(raw)
    require(current in (STOCK, PATCHED), 'Несовместимая сборка или изменённый app.asar. Установка остановлена.')
    header, payload = asar_parts(raw)
    version = json.loads(contents(payload, member(header,'package.json')))['version']
    require(version == '2.33.0' and file_hash(server) == SERVER, 'Версия приложения или сервера несовместима')
    data = (HERE/'locales/ru.json').read_bytes()
    require(sha(data) == RECIPE, 'Повреждён файл перевода locales/ru.json. Распакуйте архив заново.')
    recipe = json.loads(data)
    strings = (HERE/'locales/strings.ru.json').read_bytes()
    require(sha(strings) == recipe['strings_sha256'], 'Повреждён текст перевода strings.ru.json')
    recipe['strings'] = json.loads(strings)
    backup_root = Path(os.environ['LOCALAPPDATA']) / 'AntigravityRussianLocalization'
    backup_dir = backup_root / sha(str(install).casefold().encode())[:16]
    backup = backup_dir / 'original-2.33.0.asar'
    for path in (backup_root, backup_dir, backup):
        if os.path.lexists(path):
            plain(path)
    if backup.exists():
        require(file_hash(backup) == STOCK, 'Резервная копия повреждена')
    exists = os.path.lexists(bundle)
    if exists:
        verify_tree(bundle, recipe['files'])
    if current == PATCHED:
        require(backup.is_file(), 'Для этой установки нет резервной копии публичного установщика. Восстановите оригинал прежним комплектом.')
        if action != 'restore':
            require(exists, 'Неполная установка. Сначала запустите восстановление.')
    if action == 'check':
        print('Сборка 2.33.0 проверена.', 'Русификатор установлен.' if current == PATCHED else 'Архив оригинальный.')
        return
    if action == 'apply' and current == PATCHED or action == 'restore' and current == STOCK and not exists:
        print('Это состояние уже установлено.')
        return
    closed(install)
    with tempfile.TemporaryDirectory(prefix='agy-ru-', dir=res) as tmp:
        stage = Path(tmp)
        pending = stage / 'app.asar'
        if action == 'apply':
            if not backup.is_file():
                backup_dir.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=backup_dir, delete=False) as f:
                    saved = Path(f.name)
                try:
                    shutil.copyfile(archive, saved)
                    require(file_hash(saved) == STOCK, 'Ошибка создания резервной копии')
                    saved.rename(backup)
                finally:
                    saved.unlink(missing_ok=True)
            pending.write_bytes(build_asar(raw, recipe))
            require(file_hash(pending) == PATCHED, 'Подготовленный архив отличается от проверенной редакции')
            if not exists:
                build_web(server, stage/BUNDLE, recipe)
        elif current == PATCHED:
            shutil.copyfile(backup, pending)
            require(file_hash(pending) == STOCK, 'Ошибка подготовки отката')
        closed(install)
        require(file_hash(archive) == current and file_hash(server) == SERVER, 'Приложение изменилось во время подготовки')
        if exists:
            verify_tree(bundle, recipe['files'])
        if action == 'apply':
            if not exists:
                (stage/BUNDLE).rename(bundle)
            os.replace(pending, archive)
            require(file_hash(archive) == PATCHED, 'Ошибка проверки установленного архива')
            print('Русификатор установлен. Резервная копия:', backup)
        else:
            if current == PATCHED:
                os.replace(pending, archive)
            require(file_hash(archive) == STOCK, 'Ошибка проверки восстановленного архива')
            if exists:
                bundle.rename(stage/BUNDLE)
            print('Оригинал восстановлен. Резервная копия сохранена.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('apply','check','restore'))
    parser.add_argument('--install-dir', type=Path, help='Папка с Antigravity.exe')
    args = parser.parse_args()
    require(os.name == 'nt' and sys.version_info >= (3,10), 'Требуются Windows и Python 3.10 или новее.')
    install = args.install_dir or Path(os.environ['LOCALAPPDATA'])/'Programs/antigravity'
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = kernel.CreateMutexW(None, True, 'Local\\AntigravityRu233Package')
    require(mutex and ctypes.get_last_error() != 183, 'Другая операция уже выполняется')
    try:
        operate(args.action, install)
    finally:
        kernel.CloseHandle(mutex)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, zipfile.BadZipFile, KeyError, struct.error) as error:
        raise SystemExit(f'Ошибка: {error}')
