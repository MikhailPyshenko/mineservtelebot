import os
import subprocess
import re
from pathlib import Path


class Server:
    def __init__(self, screen_name="minecraft"):
        self.screen_name = screen_name
        self.screen_cmd = f"screen -S {self.screen_name} -p 0 -X stuff"

    def _send_screen_command(self, command):
        """Отправка команды в screen сессию"""
        full_cmd = f'{self.screen_cmd} "{command}^M"'
        try:
            subprocess.run(full_cmd, shell=True, check=True, executable='/bin/bash')
            return True
        except subprocess.CalledProcessError as e:
            print(f"Ошибка отправки команды в screen: {e}")
            return False

    def send_chat_message(self, message):
        """Отправка сообщения всем игрокам в чат"""
        cmd = f'say {message}'
        return self._send_screen_command(cmd)

    def send_private_message(self, player, message):
        """Отправка приватного сообщения игроку"""
        cmd = f'tell {player} {message}'
        return self._send_screen_command(cmd)

    def set_weather(self, weather_type):
        """Установка погоды на сервере"""
        valid_weather = ["clear", "rain", "thunder"]
        if weather_type.lower() not in valid_weather:
            return False, "Неверный тип погоды. Допустимо: clear, rain, thunder"

        cmd = f'weather {weather_type.lower()}'
        success = self._send_screen_command(cmd)
        if success:
            return True, f"Погода изменена на {weather_type}"
        return False, "Ошибка изменения погоды"

    def get_online_players(self):
        """Получение списка онлайн игроков"""
        temp_file = Path("/tmp/minecraft_players.txt")
        cmd = f"screen -S {self.screen_name} -p 0 -X stuff \"list^M\""

        try:
            # Очищаем временный файл
            if temp_file.exists():
                temp_file.unlink()

            # Отправляем команду list
            subprocess.run(cmd, shell=True, check=True, executable='/bin/bash')

            # Даем время на выполнение команды
            import time
            time.sleep(1)

            # Парсим вывод из логов
            if not temp_file.exists():
                return "Не удалось получить список игроков"

            with open(temp_file, 'r') as f:
                log_lines = f.readlines()

            for line in reversed(log_lines):  # Ищем последнее вхождение
                if "There are" in line:
                    return line.strip()

            return "Игроки не найдены"

        except Exception as e:
            return f"Ошибка: {str(e)}"