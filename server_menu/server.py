import os
import subprocess
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Server:
    def __init__(self, bot):
        """Инициализация серверного модуля"""
        self.bot = bot
        # Загрузка конфигурации из .env
        self.screen_name = os.getenv("SCREEN_NAME")  # Имя screen сессии
        self.server_dir = Path(os.getenv("SERVER_DIR"))  # Директория сервера
        self.scripts_dir = Path(os.getenv("SCRIPTS_DIR"))  # Директория скриптов
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

    def execute_command(self, command):
        """Выполнение произвольной команды на сервере"""
        return self._run_screen_command(command)