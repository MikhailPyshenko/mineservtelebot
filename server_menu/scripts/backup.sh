#!/usr/bin/bash
set -e  # Остановить скрипт при ошибке любой команды

echo "Скрипт создания копии мира запущен!"

SERVER_DIR="/root/minecraft/fabric_serv"  # Директория сервера
WORLD_DIR="$SERVER_DIR/world"  # Путь директории мира
BACKUP_DIR="$SERVER_DIR/backup"  # Путь директории копии мира
BACKUP_NAME="world_backup_$(date +%F_%H-%M-%S).tar.gz"  # Имя копии мира

# === ПРОВЕРКА ===
mkdir -p "$BACKUP_DIR"  # Создание папки с копиями если ее нет

if [ ! -d "$WORLD_DIR" ]; then  # Проверка существования мира
    echo "🛠️⚠️ ОШИБКА: директория мира не существует: $WORLD_DIR"
    exit 1
fi

echo "Путь директории мира: $WORLD_DIR"
echo "Путь директории копии мира: $BACKUP_DIR"
echo "Имя копии мира: $BACKUP_NAME"

# === СОЗДАНИЕ АРХИВА ===
echo "Создание архива копии мира"  # Имя архива копии мира актуальной даты
tar -cf - \
    --exclude='data/DistantHorizons.sqlite' \
    --exclude='data/DistantHorizons.sqlite-shm' \
    --exclude='data/DistantHorizons.sqlite-wal' \
    -C "$WORLD_DIR" . | pv -s $(du -sb "$WORLD_DIR" | awk '{print $1}') | gzip -8 > "$BACKUP_DIR/$BACKUP_NAME"

# Графическое отображение прогресса
if [ $? -eq 0 ]; then
    echo "Создание архива копии мира завершено"
else
    echo "Ошибка при создании архива"
    exit 1
fi

# === УДАЛЕНИЕ СТАРЫХ АРХИВОВ ===
echo "Удаление старых копий мира"
find "$BACKUP_DIR" -name 'world_backup_*.tar.gz' | sort -r | tail -n +6 | xargs rm -f  # Удаление старых копий мира, оставить последние 5
# find "$BACKUP_DIR" -type f -name "world_backup_*.tar.gz" -mtime +30 -exec rm {} \;  # Удаление старых копий мира, старше 30 дней

# === ОТЧЁТ ===
echo "Новая копия мира: $BACKUP_DIR/$BACKUP_NAME"

# === РУЧНОЙ ЗАПУСК ===
# ДАТЬ ПРАВА СКРИПТУ:
# chmod +x /root/minecraft/fabric_serv/help/backup.sh
# ЗАПУСТИТЬ
# /root/minecraft/fabric_serv/help/backup.sh