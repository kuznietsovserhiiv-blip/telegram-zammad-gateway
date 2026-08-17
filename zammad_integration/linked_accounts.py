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
    'config:"auth_telegram",class:"telegram"}'
)
MARKER = 'telegram:{url:"/telegram-gateway/link"'
BACKUP_DIR = Path(__file__).resolve().parent / "backups"
MANIFEST_PATH = BACKUP_DIR / "manifest.json"


class IntegrationError(RuntimeError):
    pass


def run(command: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "command failed").strip()
        raise IntegrationError(f"{' '.join(command[:3])}: {detail}")
    return (result.stdout or "").strip()


def discover_container(name_fragment: str) -> str:
    output = run(
        ["docker", "ps", "--filter", f"name={name_fragment}", "--format", "{{.Names}}"],
        capture=True,
    )
    names = [line for line in output.splitlines() if line.strip()]
    if len(names) != 1:
        raise IntegrationError(
            f"Expected one running container matching {name_fragment!r}, found: {names}"
        )
    return names[0]


def find_bundle(container: str) -> str:
    script = (
        "for f in /opt/zammad/public/assets/application-*.js; do "
        "if grep -q '/auth/openid_connect' \"$f\"; then echo \"$f\"; break; fi; "
        "done"
    )
    path = run(["docker", "exec", container, "sh", "-lc", script], capture=True)
    if not path:
        raise IntegrationError(f"Zammad application bundle was not found in {container}")
    return path.splitlines()[0]


def patch_bundle_text(source: str) -> str:
    if MARKER in source:
        return source
    count = source.count(PROVIDER_ANCHOR)
    if count != 1:
        raise IntegrationError(f"Expected one provider anchor, found {count}")
    return source.replace(PROVIDER_ANCHOR, f"{PROVIDER_ANCHOR},{TELEGRAM_PROVIDER}", 1)


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


def install_setting(rails_container: str) -> None:
    ruby = r'''
setting = Setting.find_or_initialize_by(name: 'auth_telegram')
setting.title = 'Telegram Gateway'
setting.area = 'Security::ThirdPartyAuthentication'
setting.description = 'Enables linking the current Zammad profile to Telegram Gateway.'
setting.options = {
  'form' => [{
    'display' => '',
    'null' => true,
    'name' => 'auth_telegram',
    'tag' => 'boolean',
    'options' => { true => 'yes', false => 'no' }
  }]
}
setting.frontend = true
setting.preferences = {
  'controller' => 'SettingsAreaSwitch',
  'title_i18n' => ['Telegram'],
  'description_i18n' => [],
  'permission' => ['admin.security']
}
setting.save!
Setting.set('auth_telegram', true)
puts "auth_telegram=#{Setting.get('auth_telegram').inspect}"
'''
    run(["docker", "exec", rails_container, "/opt/zammad/bin/rails", "runner", ruby])


def disable_setting(rails_container: str) -> None:
    ruby = "Setting.set('auth_telegram', false) if Setting.find_by(name: 'auth_telegram')"
    run(["docker", "exec", rails_container, "/opt/zammad/bin/rails", "runner", ruby])


def install() -> None:
    if os.geteuid() != 0:
        raise IntegrationError("Run the installer as root")
    rails = discover_container("zammad-railsserver")
    nginx = discover_container("zammad-nginx")
    existing_manifest = load_manifest()
    manifest_targets = {(item["container"], item["bundle"]) for item in existing_manifest}

    for container in (rails, nginx):
        bundle = find_bundle(container)
        with tempfile.TemporaryDirectory(prefix="zammad-telegram-") as temp_dir:
            local_source = Path(temp_dir) / Path(bundle).name
            run(["docker", "cp", f"{container}:{bundle}", str(local_source)])
            source = local_source.read_text(encoding="utf-8")
            patched = patch_bundle_text(source)

            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            backup_name = f"{container}__{Path(bundle).name}.original"
            backup_path = BACKUP_DIR / backup_name
            target = (container, bundle)
            if target not in manifest_targets:
                shutil.copy2(local_source, backup_path)
                item = {
                    "container": container,
                    "bundle": bundle,
                    "backup": backup_name,
                }
                existing_manifest.append(item)
                manifest_targets.add(target)

            if patched != source:
                local_source.write_text(patched, encoding="utf-8")
                local_source.chmod(0o644)
                run(["docker", "cp", str(local_source), f"{container}:{bundle}"])
                print(f"patched: {container}:{bundle}")
            else:
                print(f"already patched: {container}:{bundle}")

    write_manifest(existing_manifest)
    install_setting(rails)
    verify()
    print("Installation complete. Sign out, sign in, and force-refresh the browser (Ctrl+F5).")


def verify() -> None:
    rails = discover_container("zammad-railsserver")
    nginx = discover_container("zammad-nginx")
    for container in (rails, nginx):
        bundle = find_bundle(container)
        check = run(
            ["docker", "exec", container, "grep", "-F", "-c", MARKER, bundle],
            capture=True,
        )
        if check != "1":
            raise IntegrationError(f"Telegram provider marker count in {container} is {check!r}")
        print(f"bundle: OK ({container})")

    ruby = "puts Setting.get('auth_telegram') == true ? 'OK' : 'NOT_OK'"
    setting = run(
        ["docker", "exec", rails, "/opt/zammad/bin/rails", "runner", ruby],
        capture=True,
    )
    if not setting.splitlines() or setting.splitlines()[-1] != "OK":
        raise IntegrationError("auth_telegram setting is not enabled")
    print("setting: OK")


def restore() -> None:
    if os.geteuid() != 0:
        raise IntegrationError("Run restore as root")
    manifest = load_manifest()
    if not manifest:
        raise IntegrationError("No backup manifest found")
    running = set(
        run(["docker", "ps", "--format", "{{.Names}}"], capture=True).splitlines()
    )
    for item in manifest:
        container = item["container"]
        backup = BACKUP_DIR / item["backup"]
        if container not in running:
            raise IntegrationError(f"Container is not running: {container}")
        if not backup.exists():
            raise IntegrationError(f"Backup is missing: {backup}")
        run(["docker", "cp", str(backup), f"{container}:{item['bundle']}"])
        print(f"restored: {container}:{item['bundle']}")
    disable_setting(discover_container("zammad-railsserver"))
    print("Restore complete. Sign out, sign in, and force-refresh the browser (Ctrl+F5).")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Telegram on Zammad Linked Accounts")
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
