import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv
import psutil

load_dotenv()


class Service:
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

    def _run_script(self, script_name):
        """Запуск bash-скрипта"""
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
        from .server import Server
        server = Server(self.screen_name)
        return server.get_online_players()

    def get_server_stats(self):
        """Получение статистики сервера (CPU, RAM, TPS)"""
        stats = {}
        # Получение CPU и RAM
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                if 'java' in proc.info['name'].lower() and 'minecraft' in ' '.join(proc.info['cmdline'] or []):
                    with psutil.Process(proc.info['pid']) as p:
                        stats.update({
                            'cpu': f"{p.cpu_percent()}%",
                            'ram': f"{p.memory_info().rss / 1024 / 1024:.2f} MB"
                        })
                    break
        except Exception as e:
            stats['error'] = f"Ошибка мониторинга процесса: {str(e)}"
        # Получение TPS из логов
        log_file = self.server_dir / "logs/latest.log"
        if log_file.exists():
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in reversed(list(f)[-100:]):  # Чтение в обратном порядке
                        if "Mean tick time:" in line:
                            try:
                                tick_time = float(line.split("Mean tick time:")[1].split()[0])
                                stats['tps'] = f"{min(20.0, 1000 / tick_time):.1f}"
                            except (IndexError, ValueError):
                                pass
                            break
            except Exception as e:
                if 'error' not in stats:
                    stats['error'] = f"Ошибка чтения логов: {str(e)}"
        return stats or {'error': 'Данные недоступны'}
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