#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PROVIDER_ANCHOR = (
    'openid_connect:{url:"/auth/openid_connect",name:__("OpenID Connect"),'
    'config:"auth_openid_connect",class:"openid-connect"}'
)
TELEGRAM_PROVIDER = (
    'telegram:{url:"/telegram-gateway/link",name:__("Telegram"),'
    'config:"auth_telegram",class:"telegram",login:!1}'
)
LEGACY_TELEGRAM_PROVIDER = (
    'telegram:{url:"/telegram-gateway/link",name:__("Telegram"),'
    'config:"auth_telegram",class:"telegram"}'
)
MARKER = 'telegram:{url:"/telegram-gateway/link"'
LOGIN_PUSH = "auth_providers.push(provider)"
LOGIN_PUSH_PATCHED = "provider.login!==!1&&auth_providers.push(provider)"
BACKUP_DIR = Path(__file__).resolve().parent / "backups"
MANIFEST_PATH = BACKUP_DIR / "manifest.json"


class IntegrationError(RuntimeError):
    pass


def run(command: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None)
    if result.returncode:
        raise IntegrationError(f"{' '.join(command[:3])}: {(result.stderr or result.stdout or 'command failed').strip()}")
    return (result.stdout or "").strip()


def discover_container(name_fragment: str) -> str:
    names = [name for name in run(["docker", "ps", "--filter", f"name={name_fragment}", "--format", "{{.Names}}"], capture=True).splitlines() if name]
    if len(names) != 1:
        raise IntegrationError(f"Expected one running container matching {name_fragment!r}, found: {names}")
    return names[0]


def find_bundle(container: str) -> str:
    script = "for f in /opt/zammad/public/assets/application-*.js; do if grep -q '/auth/openid_connect' \"$f\"; then echo \"$f\"; break; fi; done"
    path = run(["docker", "exec", container, "sh", "-lc", script], capture=True)
    if not path:
        raise IntegrationError(f"Zammad application bundle was not found in {container}")
    return path.splitlines()[0]


def patch_bundle_text(source: str) -> str:
    if LEGACY_TELEGRAM_PROVIDER in source:
        source = source.replace(LEGACY_TELEGRAM_PROVIDER, TELEGRAM_PROVIDER)
    elif MARKER not in source:
        if source.count(PROVIDER_ANCHOR) != 1:
            raise IntegrationError("Expected one provider anchor")
        source = source.replace(PROVIDER_ANCHOR, f"{PROVIDER_ANCHOR},{TELEGRAM_PROVIDER}", 1)
    elif source.count(TELEGRAM_PROVIDER) != 1:
        raise IntegrationError("Telegram provider has an unexpected format")

    if LOGIN_PUSH_PATCHED not in source:
        if source.count(LOGIN_PUSH) != 1:
            raise IntegrationError("Expected one login provider insertion point")
        source = source.replace(LOGIN_PUSH, LOGIN_PUSH_PATCHED, 1)
    return source


def load_manifest() -> list[dict[str, str]]:
    if not MANIFEST_PATH.exists():
        return []
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise IntegrationError("Invalid backup manifest")
    return data


def write_manifest(items: list[dict[str, str]]) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")


def set_enabled(rails_container: str, enabled: bool) -> None:
    ruby = f"Setting.set('auth_telegram', {str(enabled).lower()}) if Setting.find_by(name: 'auth_telegram')"
    run(["docker", "exec", rails_container, "/opt/zammad/bin/rails", "runner", ruby])


def install_setting(rails_container: str) -> None:
    ruby = r'''setting = Setting.find_or_initialize_by(name: 'auth_telegram')
setting.title = 'Telegram Gateway'
setting.area = 'Security::ThirdPartyAuthentication'
setting.description = 'Enables linking the current Zammad profile to Telegram Gateway.'
setting.options = { 'form' => [{ 'display' => '', 'null' => true, 'name' => 'auth_telegram', 'tag' => 'boolean', 'options' => { true => 'yes', false => 'no' } }] }
setting.frontend = true
setting.preferences = { 'controller' => 'SettingsAreaSwitch', 'title_i18n' => ['Telegram'], 'description_i18n' => [], 'permission' => ['admin.security'] }
setting.save!
Setting.set('auth_telegram', true)'''
    run(["docker", "exec", rails_container, "/opt/zammad/bin/rails", "runner", ruby])


def install() -> None:
    if os.geteuid() != 0:
        raise IntegrationError("Run the installer as root")
    rails, nginx = discover_container("zammad-railsserver"), discover_container("zammad-nginx")
    manifest = load_manifest()
    targets = {(item["container"], item["bundle"]) for item in manifest}
    for container in (rails, nginx):
        bundle = find_bundle(container)
        with tempfile.TemporaryDirectory(prefix="zammad-telegram-") as temp_dir:
            local = Path(temp_dir) / Path(bundle).name
            run(["docker", "cp", f"{container}:{bundle}", str(local)])
            original = local.read_text(encoding="utf-8")
            patched = patch_bundle_text(original)
            if (container, bundle) not in targets:
                BACKUP_DIR.mkdir(parents=True, exist_ok=True)
                backup = f"{container}__{Path(bundle).name}.original"
                shutil.copy2(local, BACKUP_DIR / backup)
                manifest.append({"container": container, "bundle": bundle, "backup": backup})
                targets.add((container, bundle))
            if patched != original:
                local.write_text(patched, encoding="utf-8")
                local.chmod(0o644)
                run(["docker", "cp", str(local), f"{container}:{bundle}"])
                print(f"patched: {container}:{bundle}")
            else:
                print(f"already patched: {container}:{bundle}")
    write_manifest(manifest)
    install_setting(rails)
    verify()
    print("Installation complete. Telegram is available only in Profile → Linked Accounts. Force-refresh the browser (Ctrl+F5).")


def verify() -> None:
    rails, nginx = discover_container("zammad-railsserver"), discover_container("zammad-nginx")
    for container in (rails, nginx):
        bundle = find_bundle(container)
        source = run(["docker", "exec", container, "cat", bundle], capture=True)
        if source.count(TELEGRAM_PROVIDER) != 1 or source.count(LOGIN_PUSH_PATCHED) != 1:
            raise IntegrationError(f"Linked Accounts-only patch is missing in {container}")
        print(f"bundle: OK ({container})")


def restore() -> None:
    if os.geteuid() != 0:
        raise IntegrationError("Run restore as root")
    manifest = load_manifest()
    if not manifest:
        raise IntegrationError("No backup manifest found")
    running = set(run(["docker", "ps", "--format", "{{.Names}}"], capture=True).splitlines())
    for item in manifest:
        if item["container"] not in running or not (BACKUP_DIR / item["backup"]).exists():
            raise IntegrationError(f"Cannot restore {item['container']}")
        run(["docker", "cp", str(BACKUP_DIR / item["backup"]), f"{item['container']}:{item['bundle']}"])
        print(f"restored: {item['container']}:{item['bundle']}")
    set_enabled(discover_container("zammad-railsserver"), False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Telegram in Zammad Linked Accounts")
    parser.add_argument("action", choices=("install", "verify", "restore"))
    args = parser.parse_args()
    try:
        {"install": install, "verify": verify, "restore": restore}[args.action]()
    except (IntegrationError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
