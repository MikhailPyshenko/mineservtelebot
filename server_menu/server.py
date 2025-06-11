import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Server:
    def __init__(self, bot):
        """Инициализация серверного модуля"""
        self.bot = bot
        # Загрузка конфигурации из .env
        self.screen_name = os.getenv("SCREEN_NAME")
        self.server_dir = Path(os.getenv("SERVER_DIR"))
        self.scripts_dir = Path(os.getenv("SCRIPTS_DIR"))
        # Валидация конфигурации
        if not self.screen_name:
            raise ValueError("SCREEN_NAME не указан в .env")
        if not self.server_dir.exists():
            raise ValueError(f"Директория сервера {self.server_dir} не существует")
        if not self.scripts_dir.exists():
            raise ValueError(f"Директория скриптов {self.scripts_dir} не существует")

    def _run_screen_command(self, command):
        """Универсальный метод отправки команд в screen сессию"""
        try:
            full_cmd = f'screen -S {self.screen_name} -p 0 -X stuff "{command}^M"'
            subprocess.run(full_cmd, shell=True, check=True, executable='/bin/bash')
            return True, "Команда успешно выполнена"
        except subprocess.CalledProcessError as e:
            return False, f"Ошибка выполнения команды: {str(e)}"

    def send_chat_message(self, message):
        """Отправка сообщения в глобальный чат"""
        return self._run_screen_command(f'say {message}')

    def send_private_message(self, player, message):
        """Отправка приватного сообщения игроку"""
        return self._run_screen_command(f'tell {player} {message}')

    def set_weather(self, weather_type):
        """Установка погоды на сервере"""
        weather_type = weather_type.lower()
        valid_weather = ["clear", "rain", "thunder"]
        if weather_type not in valid_weather:
            return False, "Неверный тип погоды. Допустимо: clear, rain, thunder"
        success, msg = self._run_screen_command(f'weather {weather_type}')
        if success:
            return True, f"Погода изменена на {weather_type}"
        return False, f"Ошибка изменения погоды: {msg}"

    def get_online_players(self):
        """Получение списка онлайн игроков"""
        return self._run_screen_command("list")

    def find_player(self, player):
        """Показывает координаты игрока"""
        return self._run_screen_command(f"execute {player} ~ ~ ~ tp @s")

    def set_time(self, time_of_day):
        """Позволяет изменить день/ночь на сервере"""
        valid_times = ["day", "night", "noon", "midnight"]
        if time_of_day.lower() not in valid_times:
            return False, "Неверное время суток. Допустимо: day, night, noon, midnight"
        return self._run_screen_command(f"time set {time_of_day}")

    def enable_pvp(self):
        """Включает PVP"""
        return self._run_screen_command("gamerule pvp true")

    def disable_pvp(self):
        """Выключает PVP"""
        return self._run_screen_command("gamerule pvp false")

    def set_difficulty(self, difficulty):
        """Меняет сложность игры"""
        valid_difficulties = ["peaceful", "easy", "normal", "hard"]
        if difficulty.lower() not in valid_difficulties:
            return False, "Неверная сложность. Допустимо: peaceful, easy, normal, hard"
        return self._run_screen_command(f"difficulty {difficulty}")

    def ban_player(self, player):
        """Блокировка игрока"""
        return self._run_screen_command(f"ban {player}")

    def unban_player(self, player):
        """Снятие блокировки с игрока"""
        return self._run_screen_command(f"pardon {player}")

    def get_banned_players(self):
        """Получение списка забаненных игроков"""
        success, response = self._run_screen_command("banlist")
        if not success:
            return False, response
        banned_players = []
        for line in response.split('\n'):
            line = line.strip()
            if line and not line.startswith("There are"):
                banned_players.append(line.split(' - ')[0])
        return True, banned_players

    def ban_ip(self, ip_address):
        """Блокировка IP-адреса"""
        return self._run_screen_command(f"ban-ip {ip_address}")

    def pardon_ip(self, ip_address):
        """Снятие блокировки IP-адреса"""
        return self._run_screen_command(f"pardon-ip {ip_address}")

    def get_banned_ips(self):
        """Получение списка забаненных IP"""
        success, response = self._run_screen_command("banlist ips")
        if not success:
            return False, response
        banned_ips = []
        for line in response.split('\n'):
            line = line.strip()
            if line and not line.startswith("There are"):
                banned_ips.append(line.split(' - ')[0])
        return True, banned_ips
