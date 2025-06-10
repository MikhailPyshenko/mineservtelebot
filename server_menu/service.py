import os
import subprocess
import psutil
import time
from pathlib import Path


class Service:
    def __init__(self, screen_name="minecraft", server_dir="/path/to/server"):
        self.screen_name = screen_name
        self.server_dir = Path(server_dir)
        self.scripts_dir = self.server_dir.parent / "scripts"

    def _run_script(self, script_name):
        """Запуск bash скрипта"""
        script_path = self.scripts_dir / script_name
        if not script_path.exists():
            return False, f"Скрипт {script_name} не найден"

        try:
            subprocess.run(["bash", str(script_path)], check=True)
            return True, f"Скрипт {script_name} выполнен успешно"
        except subprocess.CalledProcessError as e:
            return False, f"Ошибка выполнения скрипта {script_name}: {e}"

    def start_server(self):
        """Запуск сервера"""
        return self._run_script("start.sh")

    def stop_server(self):
        """Остановка сервера"""
        return self._run_script("stop.sh")

    def restart_server(self):
        """Перезагрузка сервера"""
        return self._run_script("restart.sh")

    def backup_world(self):
        """Создание резервной копии мира"""
        return self._run_script("backup.sh")

    def get_server_status(self):
        """Получение статуса сервера"""
        try:
            # Проверяем наличие screen сессии
            result = subprocess.run(
                ["screen", "-ls", self.screen_name],
                capture_output=True,
                text=True
            )

            if f"{self.screen_name}" in result.stdout:
                return "Сервер работает"
            return "Сервер остановлен"
        except Exception as e:
            return f"Ошибка проверки статуса: {str(e)}"

    def get_players_count(self):
        """Получение количества игроков онлайн"""
        # Эта функция должна быть реализована в server.py
        from .server import Server
        server = Server(self.screen_name)
        return server.get_online_players()

    def get_server_stats(self):
        """Получение статистики сервера (CPU, RAM, TPS)"""
        stats = {}

        # Получаем PID процесса Java (предполагаем, что сервер - это Java процесс)
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                if 'java' in proc.info['name'].lower() and 'minecraft' in ' '.join(proc.info['cmdline'] or []):
                    p = psutil.Process(proc.info['pid'])
                    stats['cpu'] = f"{p.cpu_percent()}%"
                    stats['ram'] = f"{p.memory_info().rss / 1024 / 1024:.2f} MB"
                    break
        except Exception as e:
            stats['error'] = f"Ошибка получения информации о процессе: {str(e)}"

        # Получаем TPS из логов (упрощенная версия)
        log_file = self.server_dir / "logs/latest.log"
        if log_file.exists():
            try:
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    for line in reversed(lines[-100:]):  # Проверяем последние 100 строк
                        if "Mean tick time:" in line:
                            tps = 1000 / float(line.split("Mean tick time:")[1].split(" ")[1])
                            stats['tps'] = f"{min(20.0, tps):.1f}"
                            break
            except Exception:
                pass

        return stats if stats else {"error": "Не удалось получить статистику"}

    def get_world_size(self):
        """Получение размера мира"""
        world_dir = self.server_dir / "world"
        if not world_dir.exists():
            return "Директория мира не найдена"

        total_size = 0
        for dirpath, _, filenames in os.walk(world_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                total_size += os.path.getsize(fp)

        return f"{total_size / 1024 / 1024:.2f} MB"