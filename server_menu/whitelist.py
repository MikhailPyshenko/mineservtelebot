import sys
import subprocess

SESSION_NAME = "minecraft_fabric_server"


def is_screen_session_running(session_name=SESSION_NAME):
    try:
        result = subprocess.run(['screen', '-ls'], capture_output=True, text=True, check=True)
        return session_name in result.stdout
    except subprocess.CalledProcessError:
        return False


def run_screen_command(command: str):
    full_command = f'screen -S {SESSION_NAME} -X stuff "{command}\\n"'
    subprocess.run(full_command, shell=True, check=True)


def add_to_whitelist(nickname):
    nickname = nickname.lower()
    if not is_screen_session_running():
        print(f"Ошибка: screen-сессия '{SESSION_NAME}' не запущена.", file=sys.stderr)
        sys.exit(1)
    run_screen_command(f"whitelist add {nickname}")


def remove_from_whitelist(nickname):
    nickname = nickname.lower()
    if not is_screen_session_running():
        print(f"Ошибка: screen-сессия '{SESSION_NAME}' не запущена.", file=sys.stderr)
        sys.exit(1)
    run_screen_command(f"whitelist remove {nickname}")


def reload_whitelist():
    if not is_screen_session_running():
        print(f"Ошибка: screen-сессия '{SESSION_NAME}' не запущена.", file=sys.stderr)
        sys.exit(1)
    run_screen_command("whitelist reload")


def add_ufw_rules(ip):
    if not ip:
        return
    rules = [
        f"ufw allow from {ip} to any port 25565 proto tcp",
        f"ufw allow from {ip} to any port 25565 proto udp",
    ]
    for rule in rules:
        try:
            subprocess.run(rule, shell=True, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Ошибка при добавлении правила UFW: {e}", file=sys.stderr)
            raise


def remove_ufw_rules(ip):
    if not ip:
        return
    rules = [
        f"ufw delete allow from {ip} to any port 25565 proto tcp",
        f"ufw delete allow from {ip} to any port 25565 proto udp",
    ]
    for rule in rules:
        try:
            subprocess.run(rule, shell=True, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Ошибка при удалении правила UFW: {e}", file=sys.stderr)
            raise


def main():
    if len(sys.argv) < 2:
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "reload":
        try:
            reload_whitelist()
            print("Whitelist успешно перезагружен")
            sys.exit(0)
        except Exception as e:
            print(f"Ошибка при перезагрузке whitelist: {e}", file=sys.stderr)
            sys.exit(1)

    if command not in ("add", "remove"):
        sys.exit(1)

    if len(sys.argv) < 3:
        print("Ошибка: не указан никнейм игрока.", file=sys.stderr)
        sys.exit(1)

    nickname = sys.argv[2].lower()
    ip = sys.argv[3] if len(sys.argv) > 3 else None  # IP теперь передается без валидации

    try:
        if command == "add":
            add_to_whitelist(nickname)
            if ip:
                add_ufw_rules(ip)
                print(f"Игрок {nickname} добавлен в whitelist, правила UFW обновлены для {ip}")
            else:
                print(f"Игрок {nickname} добавлен в whitelist, IP не указан")
        elif command == "remove":
            remove_from_whitelist(nickname)
            if ip:
                remove_ufw_rules(ip)
                print(f"Игрок {nickname} удалён из whitelist, правила UFW удалены для {ip}")
            else:
                print(f"Игрок {nickname} удалён из whitelist, IP не указан - правила UFW не изменены")
    except subprocess.CalledProcessError as e:
        print(f"Ошибка при выполнении команды: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Неожиданная ошибка: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()