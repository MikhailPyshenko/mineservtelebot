import os
import re
import sqlite3
import logging
import ipaddress
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, \
    MessageHandler, filters, BaseHandler
from server_menu.service import Service as ServerService
from server_menu.server import Server as MinecraftServer
from server_menu.whitelist import add_to_whitelist, remove_from_whitelist, reload_whitelist, add_ufw_rules, \
    remove_ufw_rules


# ==================== УТИЛИТЫ ====================
async def reply_to_update(update: Update, text: str, reply_markup=None, show_alert=False, parse_mode="HTML"):
    """Безопасная отправка сообщений с автоматическим экранированием"""
    try:
        if not update:
            logger.error("Пустой update объект")
            return
        # Автоматическое экранирование специальных символов
        safe_text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        if update.message:
            await update.message.reply_text(
                text=safe_text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=True
            )
        elif update.callback_query:
            if show_alert:
                await update.callback_query.answer(safe_text, show_alert=show_alert)
            else:
                try:
                    await update.callback_query.edit_message_text(
                        text=safe_text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                        disable_web_page_preview=True
                    )
                    await update.callback_query.answer()
                except Exception as e:
                    logger.warning(f"Не удалось изменить сообщение: {e}")
                    await update.effective_message.reply_text(
                        text=safe_text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode
                    )
        else:
            logger.error("Неподдерживаемый тип update")
    except Exception as e:
        logger.error(f"Ошибка в reply_to_update: {e}")


def create_keyboard(buttons, inline=True):
    """Универсальный метод создания клавиатуры"""
    if inline:
        return InlineKeyboardMarkup([[b] if not isinstance(b, list) else b for b in buttons])
    return ReplyKeyboardMarkup([[b] if not isinstance(b, list) else b for b in buttons], resize_keyboard=True)


# ==================== КОНФИГУРАЦИЯ ====================
# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Создаем папку temp если ее нет
TEMP_DIR = Path(__file__).parent / 'temp'
TEMP_DIR.mkdir(exist_ok=True)

# Импорт констант
load_dotenv()


class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_IDS = set(map(int, os.getenv("ADMIN_IDS", "").split(",")))
    DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")
    SCREEN_NAME = os.getenv("SCREEN_NAME")
    SERVER_DIR = Path(os.getenv("SERVER_DIR"))
    SCRIPTS_DIR = Path(os.getenv("SCRIPTS_DIR"))

    # Состояния ConversationHandler
    (REG_NICK, REG_IP, REG_CONFIRM, REG_RESTART, EDIT_NICK, EDIT_IP, ADMIN_SENDMSG, ADMIN_USER_SELECT, SERVER_MSG_INPUT,
     BROADCAST_MSG_INPUT) = range(10)

    TEXTS = {
        "welcome": "Добро пожаловать в основной бот меню!",
        "hello": "Привет!\nЭто бот для управления сервером Minecraft.\nПроект бота на [GitHub](https://github.com/MikhailPyshenko/mineservtelebot)",
        "readme": "Информация о сервере:\n- Версия - 1.21.4\n- Загрузчик - Fabric 0.16\n- Доступ к серверу по IP устройства\n- На сервере аутентификация по нику\n",
        "help": "--- Команды бота ---\n/start - Главное меню\n/help - Инструкция\n/reg - Регистрация\n/unreg - Отмена регистрации\n/user - Меню пользователя\n \n--- Инструкция по регистрации ---\n1. Зарегистрируйтесь, команда /reg\n1.1. Выберите ник, он будет использоваться в игре\n1.2. Введите IP ([Узнать свой IP](https://2ip.ru/)) устройства с которого будете играть\n2. Дождитесь одобрения заявки на регистрацию\n3. После регистрации вы получите доступ к профилю где сможете изменить ник, IP и узнать состояние сервера",
        "not_registered": "Вы не зарегистрированы. Пожалуйста, зарегистрируйтесь.",
        "pending_approval": "Ваша заявка на регистрацию ожидает одобрения.",
        "already_approved": "Вы уже зарегистрированы и одобрены.",
        "reg_cancelled": "Регистрация отменена.",
        "nick_empty": "Ник не может быть пустым.",
        "ip_empty": "IP не может быть пустым.",
        "admin_only": "Команда доступна только администраторам.",
        "no_pending": "Нет новых заявок.",
        "user_not_found": "Пользователь не найден.",
        "operation_cancelled": "Операция отменена.",
    }


# ==================== БАЗА ДАННЫХ ====================
class Database:
    """Класс для работы с базой данных пользователей"""

    @staticmethod
    def init():
        """Инициализация базы данных"""
        with sqlite3.connect(Config.DB_PATH) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS users(
                tg_id INTEGER PRIMARY KEY,
                tg_username TEXT,
                ingame_nick TEXT,
                ip TEXT,
                approved INTEGER DEFAULT 0
            )""")

    @staticmethod
    def user_exists(tg_id):
        """Проверка существования пользователя"""
        with sqlite3.connect(Config.DB_PATH) as con:
            return con.execute("SELECT 1 FROM users WHERE tg_id=?", (tg_id,)).fetchone() is not None

    @staticmethod
    def get_user(tg_id):
        """Получение данных пользователя"""
        with sqlite3.connect(Config.DB_PATH) as con:
            row = con.execute("SELECT tg_id, tg_username, ingame_nick, ip, approved FROM users WHERE tg_id=?",
                              (tg_id,)).fetchone()
            return dict(zip(['tg_id', 'tg_username', 'ingame_nick', 'ip', 'approved'], row)) if row else None

    @staticmethod
    def add_user(tg_id, tg_username, ingame_nick, ip):
        """Добавление нового пользователя"""
        with sqlite3.connect(Config.DB_PATH) as con:
            con.execute(
                "INSERT OR REPLACE INTO users (tg_id, tg_username, ingame_nick, ip, approved) VALUES (?, ?, ?, ?, 0)",
                (tg_id, tg_username, ingame_nick, ip))

    @staticmethod
    def update_user(tg_id, **fields):
        """Обновление данных пользователя"""
        if not fields:
            return
        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [tg_id]
        with sqlite3.connect(Config.DB_PATH) as con:
            con.execute(f"UPDATE users SET {set_clause} WHERE tg_id=?", values)

    @staticmethod
    def delete_user(tg_id):
        """Удаление пользователя"""
        with sqlite3.connect(Config.DB_PATH) as con:
            con.execute("DELETE FROM users WHERE tg_id=?", (tg_id,))

    @staticmethod
    def list_users(approved=None):
        """Список пользователей с фильтром по approved"""
        query = "SELECT tg_id, tg_username, ingame_nick, ip, approved FROM users"
        params = ()
        if approved is not None:
            query += " WHERE approved=?"
            params = (1 if approved else 0,)
        query += " ORDER BY tg_username"
        with sqlite3.connect(Config.DB_PATH) as con:
            return con.execute(query, params).fetchall()


# ==================== БОТ ====================
class MinecraftBot:
    """Основной класс бота"""

    def __init__(self):
        self.pid_file = TEMP_DIR / 'bot.pid'
        self._write_pid_file()
        self.application = ApplicationBuilder().token(Config.BOT_TOKEN).build()
        self.whitelist_manager = WhitelistManager()
        # Инициализация серверных модулей
        self.server_service = ServerService(self)
        self.minecraft_server = MinecraftServer(self)
        # Инициализация компонентов бота
        self.service = Service(self)  # Сервисные функции
        self.server = Server(self)  # Серверные функции
        self.admin = Admin(self)
        self.registration = Registration(self)
        self.user = User(self)
        self.setup_handlers()
        Database.init()

    def _write_pid_file(self):
        """Запись PID файла для управления процессом"""
        try:
            with open(self.pid_file, 'w') as f:
                f.write(str(os.getpid()))
        except Exception as e:
            logger.error(f"Ошибка записи PID файла: {e}")

    def setup_error_handler(self):
        """Настройка обработчика ошибок"""

        async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
            error_msg = f"Произошла ошибка: {context.error}"
            logger.error(error_msg)
            if isinstance(update, Update):
                await reply_to_update(update, "⚠️ Произошла ошибка при обработке запроса")

        self.application.add_error_handler(error_handler)

    def setup_handlers(self):
        """Настройка обработчиков"""
        handlers = [
            # Базовые команды
            CommandHandler("start", self.start),
            CommandHandler("help", self.help_command),
            CommandHandler("user", self.send_user_menu),
            CommandHandler("unreg", self._handle_unreg_command),
            CallbackQueryHandler(lambda u, c: reply_to_update(u, Config.TEXTS["hello"]), pattern="^hello$"),
            CallbackQueryHandler(lambda u, c: reply_to_update(u, Config.TEXTS["readme"]), pattern="^readme$"),
            CallbackQueryHandler(self.start, pattern="^start$"),
            CallbackQueryHandler(self.help_command, pattern="^help$"),
            CallbackQueryHandler(self._handle_unreg_command, pattern="^unreg$"),
            CallbackQueryHandler(self.exit, pattern="^exit$"),
            # Обработчик регистрации
            self._create_registration_handler(),
            # Пользовательские обработчики
            *self._create_user_handlers(),
            # Обработчик администрирования
            *self._create_admin_handlers(),
            # Серверные обработчики
            CallbackQueryHandler(self.server.server_menu, pattern="^admin_server$"),
            CallbackQueryHandler(self.server.get_players_count, pattern="^server_players$"),
            CallbackQueryHandler(self.server.get_weather_menu, pattern="^server_weather$"),
            CallbackQueryHandler(self.server.set_weather, pattern="^weather_"),
            CallbackQueryHandler(self.server.reload_whitelist, pattern="^server_reload_whitelist$"),
            CallbackQueryHandler(self.server.start_ban_menu, pattern="^ban_menu$"),
            CallbackQueryHandler(self.server.start_ban_player, pattern="^server_ban$"),
            CallbackQueryHandler(self.server.start_unban_player, pattern="^server_unban$"),
            CallbackQueryHandler(self.server.ban_player, pattern="^ban_"),
            CallbackQueryHandler(self.server.unban_player, pattern="^unban_"),
            self._create_chat_message_handler(),
            # Сервисные обработчики
            CallbackQueryHandler(self.service.service_menu, pattern="^admin_service$"),
            CallbackQueryHandler(self.service.backup_world, pattern="^service_backup$"),
            CallbackQueryHandler(self.service.start_server, pattern="^service_start$"),
            CallbackQueryHandler(self.service.restart_server, pattern="^service_restart$"),
            CallbackQueryHandler(self.service.stop_server, pattern="^service_stop$"),
            CallbackQueryHandler(self.service.execute_command, pattern="^service_exec_cmd$"),
            CallbackQueryHandler(self.service.logging_on, pattern="^service_logging_on$"),
            CallbackQueryHandler(self.service.logging_off, pattern="^service_logging_off$"),
            self.service._create_command_handler(),
        ]
        self.application.add_handlers(handlers)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Главное меню бота"""
        user_id = update.effective_user.id
        is_admin = user_id in Config.ADMIN_IDS
        user = Database.get_user(user_id)
        buttons = [
            [InlineKeyboardButton("🚪 Выйти", callback_data="exit")],
            [InlineKeyboardButton("👋 Приветствие", callback_data="hello")],
            [InlineKeyboardButton("🖥 О сервере", callback_data="readme")],
            [InlineKeyboardButton("📜 Инструкция", callback_data="help")],
        ]
        if not user:
            buttons.append([InlineKeyboardButton("📝 Регистрация", callback_data="reg_start")])
        else:
            buttons.append([InlineKeyboardButton("👤 Мой профиль", callback_data="user_menu")])
        if is_admin:
            buttons.append([InlineKeyboardButton("🔐 Админ-панель", callback_data="admin_menu")])
        await reply_to_update(update, "🏠 Главное меню", create_keyboard(buttons))
        return ConversationHandler.END

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды помощи"""
        await reply_to_update(update, Config.TEXTS["help"])

    async def send_user_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню пользователя"""
        user = Database.get_user(update.effective_user.id)
        if not user:
            await reply_to_update(update, Config.TEXTS["not_registered"])
            return
        buttons = []
        if user['approved']:
            text = "✅ Ваш аккаунт одобрен\nМеню пользователя:"
            buttons.append([InlineKeyboardButton("✏️ Редактировать ник", callback_data="user_edit_nick")])
            buttons.append([InlineKeyboardButton("🌐 Редактировать IP", callback_data="user_edit_ip")])
        else:
            text = "⏳ Ваша заявка на рассмотрении\nДоступные действия:"
            buttons.append([InlineKeyboardButton("🔄 Обновить статус", callback_data="user_check")])
        buttons.append([InlineKeyboardButton("❌ Удалить регистрацию", callback_data="user_unreg")])
        buttons.append([InlineKeyboardButton("🏠 В основное меню", callback_data="start")])  # Добавлено
        await reply_to_update(update, text, create_keyboard(buttons))

    async def exit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Закрывает меню (удаляет сообщение)"""
        try:
            query = update.callback_query
            await query.answer()
            await query.delete_message()
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения: {e}")

    def _create_registration_handler(self):
        """Создаем надежный обработчик регистрации"""
        registration = Registration(self)

        return ConversationHandler(
            entry_points=[
                CommandHandler("reg", registration.start),
                CallbackQueryHandler(registration.start, pattern="^reg_new$"),
                CallbackQueryHandler(registration.start, pattern="^reg_start$")
            ],
            states={
                Config.REG_RESTART: [
                    CallbackQueryHandler(registration.start, pattern="^reg_new$"),
                    CallbackQueryHandler(registration.cancel, pattern="^reg_cancel$")
                ],
                Config.REG_NICK: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, registration.process_nick)
                ],
                Config.REG_IP: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, registration.process_ip)
                ],
                Config.REG_CONFIRM: [
                    CallbackQueryHandler(registration.confirm, pattern="^reg_confirm$"),
                    CallbackQueryHandler(registration.cancel, pattern="^reg_cancel$")
                ]
            },
            fallbacks=[
                CommandHandler("cancel", registration.cancel),
                CallbackQueryHandler(registration.cancel, pattern="^cancel$"),
                MessageHandler(filters.ALL, registration.cancel)
            ],
            per_message=False,
            allow_reentry=True
        )

    async def _handle_unreg_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /unreg"""
        user = User(self)
        await user.unreg_start(update, context)

    def _create_user_handlers(self):
        """Обработчики пользователя"""
        user = User(self)
        return [
            CallbackQueryHandler(user.unreg_start, pattern="^user_unreg$"),
            CallbackQueryHandler(user.unreg_confirm, pattern="^user_unreg_confirm$"),
            CallbackQueryHandler(user.cancel_unreg, pattern="^user_cancel_unreg$"),
            CallbackQueryHandler(user.check_status, pattern="^user_check$"),
            CallbackQueryHandler(self.send_user_menu, pattern="^user_menu$"),
            self._create_edit_nick_handler(),
            self._create_edit_ip_handler()
        ]

    def _create_edit_nick_handler(self):
        """Обработчик для изменения ника"""
        user = User(self)
        return ConversationHandler(
            entry_points=[CallbackQueryHandler(user.edit_nick_start, pattern="^user_edit_nick$")],
            states={Config.EDIT_NICK: [MessageHandler(filters.TEXT & ~filters.COMMAND, user.edit_nick_save)]},
            fallbacks=[
                CommandHandler("cancel", user.cancel_edit),
                CallbackQueryHandler(user.cancel_edit, pattern="^cancel$")
            ],
            per_message=False
        )

    def _create_edit_ip_handler(self):
        """Обработчик для изменения IP"""
        user = User(self)
        return ConversationHandler(
            entry_points=[CallbackQueryHandler(user.edit_ip_start, pattern="^user_edit_ip$")],
            states={Config.EDIT_IP: [MessageHandler(filters.TEXT & ~filters.COMMAND, user.edit_ip_save)]},
            fallbacks=[
                CommandHandler("cancel", user.cancel_edit),
                CallbackQueryHandler(user.cancel_edit, pattern="^cancel$")
            ],
            per_message=False
        )

    def _create_admin_handlers(self):
        """Создание обработчиков для админских команд"""
        admin = Admin(self)
        return [
            CommandHandler("admin", admin.send_admin_menu),
            CallbackQueryHandler(admin.send_admin_menu, pattern="^admin_menu$"),
            CallbackQueryHandler(admin.list_pending_requests, pattern="^admin_list_pending$"),
            CallbackQueryHandler(admin.list_users, pattern="^admin_list_users$"),
            CallbackQueryHandler(admin.start_broadcast, pattern="^admin_broadcast$"),
            CallbackQueryHandler(admin.user_management_menu, pattern="^admin_user_"),
            CallbackQueryHandler(admin.handle_delete_user, pattern=r'^admin_delete_\d+$'),
            CallbackQueryHandler(admin.start_send_message, pattern=r'^admin_msg_\d+$'),
            CallbackQueryHandler(admin.handle_whitelist_action, pattern="^(wl|ufw)_"),
            CallbackQueryHandler(admin.reload_whitelist, pattern="^admin_reload_wl$"),
            CallbackQueryHandler(admin.handle_back, pattern="^(admin_back|admin_users)$"),
            CallbackQueryHandler(admin.handle_approve_reject, pattern="^admin_(approve|reject)_"),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(admin.start_edit_nick, pattern="^admin_edit_")],
                states={
                    "edit_nick": [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.edit_user_nick)]
                },
                fallbacks=[]
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(admin.start_edit_ip, pattern="^admin_editip_")],
                states={
                    "edit_ip": [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.edit_user_ip)]
                },
                fallbacks=[]
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(admin.start_send_message, pattern=r'^admin_msg_\d+$')],
                states={
                    "admin_message_input": [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.process_user_message)]
                },
                fallbacks=[
                    CommandHandler("cancel", lambda u, c: reply_to_update(u, "Отправка сообщения отменена")),
                    CallbackQueryHandler(lambda u, c: reply_to_update(u, "Отправка сообщения отменена"),
                                         pattern="^cancel$")
                ]
            ),
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin.process_broadcast),
        ]

    def _create_server_handlers(self):
        """Создание обработчиков для серверных команд"""
        return [
            CallbackQueryHandler(self.server.server_menu, pattern="^admin_server$"),
            CallbackQueryHandler(self.server.get_players_count, pattern="^server_players$"),
            CallbackQueryHandler(self.server.get_weather_menu, pattern="^server_weather$"),
            CallbackQueryHandler(self.server.set_weather, pattern="^weather_"),
            CallbackQueryHandler(self.server.reload_whitelist, pattern="^server_reload_whitelist$"),
            self._create_chat_message_handler()
        ]

    def _create_chat_message_handler(self):
        """Создание обработчика сообщений чата"""
        return ConversationHandler(
            entry_points=[CallbackQueryHandler(self.server.send_chat_message, pattern="^server_send_chat$")],
            states={"server_chat_msg_input": [
                MessageHandler(filters.TEXT & ~filters.COMMAND, self.server.process_chat_message)]},
            fallbacks=[
                CommandHandler("cancel", lambda u, c: reply_to_update(u, "Отправка сообщения отменена")),
                CallbackQueryHandler(lambda u, c: reply_to_update(u, "Отправка сообщения отменена"), pattern="^cancel$")
            ],
            per_message=False
        )

    def _create_service_handlers(self):
        """Создание обработчиков для сервисных команд"""
        service = Service(self)
        return [
            CallbackQueryHandler(service.service_menu, pattern="^admin_service$"),
            CallbackQueryHandler(service.backup_world, pattern="^service_backup$"),
            CallbackQueryHandler(service.start_server, pattern="^service_start$"),
            CallbackQueryHandler(service.restart_server, pattern="^service_restart$"),
            CallbackQueryHandler(service.stop_server, pattern="^service_stop$")
        ]

    async def check_active_sessions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Проверяет и завершает активные сессии перед началом нового диалога"""
        user_id = update.effective_user.id
        active_session = context.user_data.get('active_session')
        if active_session:
            try:
                # Завершаем предыдущий диалог
                if active_session == 'registration':
                    await self.registration.cancel_registration(update, context)
                elif active_session == 'edit_nick':
                    await self.user.cancel_edit(update, context)
                elif active_session == 'edit_ip':
                    await self.user.cancel_edit(update, context)

                # Удаляем предыдущее сообщение с кнопками
                if update.callback_query:
                    await update.callback_query.message.delete()
            except Exception as e:
                logger.error(f"Ошибка при завершении сессии: {e}")

        context.user_data['active_session'] = None
        return True


# ==================== РЕГИСТРАЦИЯ ====================
class Registration:
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Начало процесса регистрации с проверкой существующей заявки"""
        try:
            user_id = update.effective_user.id
            self.logger.info(f"Попытка регистрации пользователя {user_id}")
            # Проверяем текущий статус пользователя
            user = Database.get_user(user_id)
            if user:
                if user['approved']:
                    msg = (
                        "✅ Вы уже зарегистрированы и одобрены!\n"
                        "Используйте /user для управления профилем"
                    )
                else:
                    msg = (
                        "⏳ У вас уже есть заявка на рассмотрении.\n"
                        "Ожидайте одобрения администратора."
                    )
                await reply_to_update(update, msg)
                return ConversationHandler.END
            # Если пользователь не зарегистрирован - начинаем новую регистрацию
            context.user_data.clear()
            context.user_data['reg_user_id'] = user_id
            context.user_data['reg_username'] = update.effective_user.username or ""
            await reply_to_update(update,
                                  "🎮 Регистрация нового игрока\n\n"
                                  "Введите ваш внутриигровой ник:\n"
                                  "• Только латиница, цифры и _\n"
                                  "• От 3 до 16 символов\n"
                                  "• Будет преобразован в нижний регистр")
            return Config.REG_NICK
        except Exception as e:
            self.logger.error(f"Ошибка начала регистрации: {str(e)}")
            await reply_to_update(update, "⚠️ Произошла ошибка при старте регистрации")
            return ConversationHandler.END

    async def process_nick(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Обработка введенного ника с использованием валидации"""
        try:
            nick = update.message.text.strip()
            self.logger.info(f"Пользователь {update.effective_user.id} ввел ник: {nick}")
            # Используем метод валидации
            is_valid, message = self.validate_nickname(nick)
            if not is_valid:
                await reply_to_update(update, message)
                return Config.REG_NICK
            # Сохраняем валидный ник
            context.user_data['reg_nick'] = nick.lower()
            # Запрашиваем IP
            await reply_to_update(update,
                                  "🌐 Теперь введите ваш IP-адрес:\n"
                                  "• Можно узнать на сайтах типа 2ip.ru\n"
                                  "• Формат: 123.45.67.89 или IPv6\n\n"
                                  "⚠️ Этот IP будет использоваться для доступа к серверу")
            return Config.REG_IP
        except Exception as e:
            self.logger.error(f"Ошибка обработки ника: {str(e)}")
            await reply_to_update(update, "⚠️ Ошибка обработки ника. Попробуйте еще раз.")
            return Config.REG_NICK

    async def process_ip(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Обработка введенного IP-адреса с использованием валидации"""
        try:
            ip = update.message.text.strip()
            self.logger.info(f"Пользователь {update.effective_user.id} ввел IP: {ip}")
            # Используем метод валидации IP
            is_valid, message = self.validate_ip(ip)
            if not is_valid:
                await reply_to_update(update, message)
                return Config.REG_IP
            context.user_data['reg_ip'] = ip
            # Подтверждение данных
            kb = [
                [InlineKeyboardButton("✅ Подтвердить", callback_data="reg_confirm")],
                [InlineKeyboardButton("❌ Отменить", callback_data="reg_cancel")]
            ]
            await reply_to_update(update,
                                  f"🔹 Проверьте введенные данные:\n\n"
                                  f"👤 Ник: {context.user_data['reg_nick']}\n"
                                  f"🌐 IP: {context.user_data['reg_ip']}\n\n"
                                  "Всё верно?",
                                  reply_markup=InlineKeyboardMarkup(kb))
            return Config.REG_CONFIRM
        except Exception as e:
            self.logger.error(f"Ошибка обработки IP: {str(e)}")
            await reply_to_update(update, "⚠️ Ошибка обработки IP. Попробуйте еще раз.")
            return Config.REG_IP

    async def confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Подтверждение регистрации с безопасным форматированием"""
        query = update.callback_query
        await query.answer()
        if query.data == "reg_confirm":
            data = context.user_data
            user_id = data['reg_user_id']
            self.logger.info(f"Подтверждение регистрации пользователя {user_id}")
            # Проверка существующей регистрации
            if Database.get_user(user_id):
                self.logger.warning(f"Попытка повторной регистрации пользователя {user_id}")
                await reply_to_update(update, "⚠️ Вы уже зарегистрированы!")
                return ConversationHandler.END
            # Сохраняем пользователя
            Database.add_user(
                user_id,
                data['reg_username'],
                data['reg_nick'],
                data['reg_ip']
            )
            self.logger.info(
                f"Пользователь {user_id} добавлен в базу данных (ник: {data['reg_nick']}, IP: {data['reg_ip']})")
            # Формируем сообщение для админов
            admin_msg = (
                "🆕 Новая заявка на регистрацию\n\n"
                f"👤 Пользователь: {data['reg_username'] or 'нет username'}\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"🎮 Ник: <code>{data['reg_nick']}</code>\n"
                f"🌐 IP: <code>{data['reg_ip']}</code>"
            )
            # Уведомляем админов
            self.logger.info(f"Отправка уведомления админам о новой заявке от пользователя {user_id}")
            await self.bot.admin.notify_admins(admin_msg, user_id)
            # Ответ пользователю
            await reply_to_update(update,
                                  "✅ Заявка на регистрацию отправлена!\n"
                                  "Ожидайте одобрения администратора.")
            return ConversationHandler.END
        else:
            await self.cancel(update, context)
            return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Отмена регистрации (новый метод)"""
        try:
            query = update.callback_query
            if query:
                await query.answer()
            context.user_data.clear()
            await reply_to_update(update, "🔹 Регистрация отменена")
            return ConversationHandler.END
        except Exception as e:
            self.logger.error(f"Ошибка отмены регистрации: {str(e)}")
            return ConversationHandler.END

    @staticmethod
    def validate_nickname(nick: str) -> tuple[bool, str]:
        """Валидация ника пользователя"""
        nick = nick.strip().lower()
        if not nick:
            return False, "Ник не может быть пустым. Попробуйте еще раз:"
        if len(nick) < 3 or len(nick) > 16:
            return False, "Ник должен быть от 3 до 16 символов. Попробуйте еще раз:"
        if not re.match(r'^[a-z0-9_]+$', nick):
            return False, "Ник может содержать только латинские буквы, цифры и подчеркивания. Попробуйте еще раз:"
        if not Registration.is_nick_unique(nick):
            return False, "Этот ник уже занят. Пожалуйста, выберите другой:"
        return True, nick

    @staticmethod
    def validate_ip(ip: str) -> tuple[bool, str]:
        """Валидация IP-адреса (IPv4 и IPv6) с проверкой на спец. адреса"""
        ip = ip.strip()
        if not ip:
            return False, "IP-адрес не может быть пустым. Пожалуйста, введите ваш IP:"
        if not Registration.is_ip_unique(ip):
            return False, "Этот IP уже используется. Введите другой."
        try:
            ip_obj = ipaddress.ip_address(ip)
        except ValueError:
            return False, "Неверный формат IP. Должен быть IPv4 (например 123.45.67.89) или IPv6."
        # Проверка на спец. IP (локальные, зарезервированные и др.)
        if ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_multicast or ip_obj.is_reserved:
            return False, "Нельзя использовать специальные/зарезервированные IP-адреса."
        # Дополнительная строгая проверка IPv6
        if isinstance(ip_obj, ipaddress.IPv6Address):
            segments = ip.split(':')
            if len(segments) < 3:  # IPv6 должен иметь минимум 3 сегмента
                return False, "Неверный формат IPv6. Пример: 2001:0db8:85a3::8a2e:0370:7334"
        return True, ip

    @staticmethod
    def is_nick_unique(nick: str) -> bool:
        """Проверка уникальности ника"""
        with sqlite3.connect(Config.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM users WHERE ingame_nick = ?", (nick.lower(),))
            return cursor.fetchone() is None

    @staticmethod
    def is_ip_unique(ip: str) -> bool:
        """Проверка уникальности IP"""
        with sqlite3.connect(Config.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM users WHERE ip = ?", (ip,))
            return cursor.fetchone() is None


# ==================== ПОЛЬЗОВАТЕЛЬ ====================
class User:
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)

    async def edit_nick_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало редактирования ника с улучшенной обработкой"""
        query = update.callback_query
        await query.answer()
        help_text = (
            "Введите новый внутриигровой ник:\n"
            "⚠️ Ник должен быть таким же, как в игре!\n"
            "⚠️ Будет автоматически преобразован в нижний регистр\n"
            "⚠️ Должен быть от 3 до 16 символов, только латинские буквы, цифры и _")
        await reply_to_update(update, help_text)
        return Config.EDIT_NICK

    async def edit_nick_save(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Сохранение нового ника с очисткой старых данных и приведением к нижнему регистру"""
        user_id = update.effective_user.id
        user_data = Database.get_user(user_id)
        if not user_data:
            await reply_to_update(update, "⚠️ Пользователь не найден")
            return ConversationHandler.END

        old_nick = user_data['ingame_nick']
        raw_nick = update.message.text.strip()
        new_nick = raw_nick.lower()  # Принудительное приведение к нижнему регистру

        # Проверка, изменился ли ник (учитывая регистр)
        if new_nick == old_nick.lower():
            await reply_to_update(update, "⚠️ Новый ник не отличается от текущего")
            return Config.EDIT_NICK

        # Валидация нового ника (уже в нижнем регистре)
        is_valid, message = Registration.validate_nickname(new_nick)
        if not is_valid:
            await reply_to_update(update, message)
            return Config.EDIT_NICK

        # Очищаем старые данные
        WhitelistManager.remove_from_whitelist(old_nick)

        # Обновляем данные (сохраняем в нижнем регистре)
        Database.update_user(user_id, ingame_nick=new_nick)

        # Если пользователь одобрен - добавляем новые данные
        if user_data['approved']:
            # WhitelistManager.add_to_whitelist(new_nick)

            # Уведомляем админов (показываем оригинальный ввод)
            admin_msg = (f"ℹ️ Пользователь {user_data['tg_username']} (ID: {user_id}) изменил ник:\n"
                         f"Старый: {old_nick}\n"
                         f"Новый: {raw_nick} (сохранён как: {new_nick})")
            await self.bot.admin._notify_admins_simple(context, admin_msg)

        await reply_to_update(
            update,
            f"✅ Ник успешно изменён:\n"
            f"Старый: {old_nick}\n"
            f"Новый: {raw_nick} (будет отображаться как {new_nick})"
        )
        return ConversationHandler.END

    async def edit_ip_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало редактирования IP с улучшенной инструкцией"""
        query = update.callback_query
        await query.answer()
        ip_help = (
            "Введите новый IP-адрес:\n"
            "🔍 Узнать свой IP можно здесь: https://2ip.ru/\n"
            "Формат: 123.45.67.89 (IPv4) или 2001:0db8:85a3:0000:0000:8a2e:0370:7334 (IPv6)")
        await reply_to_update(update, ip_help)
        return Config.EDIT_IP

    async def edit_ip_save(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Сохранение нового IP с очисткой старых правил"""
        user_id = update.effective_user.id
        user_data = Database.get_user(user_id)
        if not user_data:
            await reply_to_update(update, "⚠️ Пользователь не найден")
            return ConversationHandler.END

        old_ip = user_data['ip']
        new_ip = update.message.text.strip()

        # Валидация нового IP
        is_valid, message = Registration.validate_ip(new_ip)
        if not is_valid:
            await reply_to_update(update, message)
            return Config.EDIT_IP

        # Очищаем старые правила
        WhitelistManager.manage_ufw_rules(old_ip, 'remove')

        # Обновляем данные
        Database.update_user(user_id, ip=new_ip)

        # Если пользователь одобрен - добавляем новые правила
        if user_data['approved']:
            # WhitelistManager.manage_ufw_rules(new_ip, 'add')

            # Уведомляем админов
            admin_msg = (f"ℹ️ Пользователь {user_data['tg_username']} (ID: {user_id}) изменил IP:\n"
                         f"Старый: {old_ip}\nНовый: {new_ip}")
            await self.bot.admin._notify_admins_simple(context, admin_msg)

        await reply_to_update(update, f"✅ IP успешно изменён на: {new_ip}")
        return ConversationHandler.END

    async def cancel_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена редактирования информации о пользователе"""
        await reply_to_update(update, "Редактирование пользовательской информации отменено.")
        return ConversationHandler.END

    async def unreg_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало удаления регистрации"""
        user = Database.get_user(update.effective_user.id)
        if not user:
            await reply_to_update(update, "Вы не зарегистрированы!")
            return

        await reply_to_update(update,
                              "Вы уверены, что хотите удалить свою регистрацию?\n"
                              "⚠️ Это действие нельзя отменить!",
                              reply_markup=create_keyboard([
                                  [InlineKeyboardButton("✅ Да, удалить", callback_data="user_unreg_confirm")],
                                  [InlineKeyboardButton("❌ Нет, отменить", callback_data="user_cancel_unreg")]
                              ]))

    async def cancel_unreg(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена удаления регистрации"""
        query = update.callback_query
        await query.answer()
        await reply_to_update(update, "❌ Удаление регистрации отменено")

    async def unreg_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подтверждение удаления регистрации"""
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        user_data = Database.get_user(user_id)
        if not user_data:
            self.logger.warning(f"Попытка удаления несуществующего пользователя {user_id}")
            await reply_to_update(update, "⚠️ Ваш аккаунт не найден!")
            return
        # Полная очистка данных пользователя
        nick = user_data['ingame_nick']
        ip = user_data['ip']
        self.logger.info(f"Удаление регистрации пользователя {user_id} ({nick})")
        Database.delete_user(user_id)
        WhitelistManager.remove_from_whitelist(nick)
        WhitelistManager.manage_ufw_rules(ip, 'remove')
        # Уведомление админов
        admin_message = f"❌ Пользователь {nick} удалил свою регистрацию"
        self.logger.info(f"Отправка уведомления админам об удалении пользователя {nick}")
        try:
            for admin_id in Config.ADMIN_IDS:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_message
                )
        except Exception as e:
            self.logger.error(f"Ошибка уведомления админов: {e}")

        await reply_to_update(update,
                              "✅ Ваша регистрация полностью удалена.\n"
                              "Вы можете зарегистрироваться снова командой /reg")

    async def check_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверка статуса регистрации"""
        query = update.callback_query
        await query.answer()
        user = Database.get_user(update.effective_user.id)
        if not user:
            text = "Вы не зарегистрированы. Используйте /reg для регистрации."
        elif user['approved']:
            text = "✅ Ваш аккаунт одобрен и активен."
        else:
            text = "⏳ Ваша заявка на регистрацию ожидает одобрения администратора."
        await reply_to_update(update, text)


# ==================== АДМИН ====================
class Admin:
    def __init__(self, bot):
        self.bot = bot
        self.server = Server(bot)
        self.service = Service(bot)
        self.logger = logging.getLogger(__name__)

    async def _validate_admin(self, update: Update) -> bool:
        """Проверка прав администратора"""
        if not update or not update.effective_user:
            logger.error("Невалидный update или отсутствует effective_user")
            if update.callback_query:
                await update.callback_query.answer("Ошибка доступа", show_alert=True)
            return False
        if update.effective_user.id not in Config.ADMIN_IDS:
            logger.warning(f"Попытка доступа не-админа: {update.effective_user.id}")
            await reply_to_update(update, "⛔ Доступ запрещён.", show_alert=True)
            return False
        return True

    async def send_admin_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню администратора"""
        if not await self._validate_admin(update):
            return
        buttons = [
            [InlineKeyboardButton("🔄 Список заявок", callback_data="admin_list_pending")],
            [InlineKeyboardButton("👥 Список игроков", callback_data="admin_list_users")],
            [InlineKeyboardButton("⚙️ Серверные функции", callback_data="admin_server")],
            [InlineKeyboardButton("🔧 Сервисные функции", callback_data="admin_service")],
            [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton("❌ Выход в основное меню", callback_data="start")]
        ]
        await reply_to_update(update, "🔐 Админ-панель:", create_keyboard(buttons))

    async def notify_admins(self, message: str, user_id: int):
        """Уведомление админов с кнопками одобрения/отклонения"""
        buttons = [
            [InlineKeyboardButton("✅ Одобрить", callback_data=f"admin_approve_{user_id}")],
            [InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_reject_{user_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)

        for admin_id in Config.ADMIN_IDS:
            try:
                await self.bot.application.bot.send_message(
                    chat_id=admin_id,
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления админа {admin_id}: {e}")

    async def _notify_admins_simple(self, context: ContextTypes.DEFAULT_TYPE, message: str):
        """Уведомление админов без кнопок"""
        for admin_id in Config.ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=message,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления админа {admin_id}: {e}")

    async def list_pending_requests(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Список заявок на регистрацию"""
        if not await self._validate_admin(update):
            return
        query = update.callback_query
        await query.answer()
        pending_users = Database.list_users(approved=False)
        if not pending_users:
            await reply_to_update(update, "❌ Нет заявок на одобрение")
            return
        buttons = []
        for user in pending_users:
            buttons.append(
                [InlineKeyboardButton(f"👤 {user[2]} (ID: {user[0]})", callback_data=f"admin_user_{user[0]}")])
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_back")])
        buttons.append([InlineKeyboardButton("🏠 В основное меню", callback_data="start")])
        await reply_to_update(update, "📝 Заявки на одобрение:", create_keyboard(buttons))

    async def handle_approve_reject(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка кнопок одобрения/отклонения"""
        query = update.callback_query
        await query.answer()

        try:
            # Разбираем callback_data формата "admin_approve_123" или "admin_reject_123"
            if not query.data or '_' not in query.data:
                logger.error(f"Неверный формат callback_data: {query.data}")
                return

            action, user_id = query.data.split('_')[1], query.data.split('_')[2]
            user_id = int(user_id)

            user_data = Database.get_user(user_id)
            if not user_data:
                await query.edit_message_text("⚠️ Пользователь не найден")
                return

            if action == "approve":
                # Процесс одобрения
                Database.update_user(user_id, approved=1)
                WhitelistManager.add_to_whitelist(user_data['ingame_nick'])
                WhitelistManager.manage_ufw_rules(user_data['ip'], 'add')

                await query.edit_message_text(f"✅ Пользователь {user_data['ingame_nick']} одобрен")

                # Уведомляем пользователя
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="🎉 Ваша заявка одобрена! Теперь вы можете играть на сервере."
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить пользователя: {e}")

            elif action == "reject":
                # Процесс отклонения
                nick = user_data['ingame_nick']
                ip = user_data['ip']

                Database.delete_user(user_id)
                WhitelistManager.remove_from_whitelist(nick)
                WhitelistManager.manage_ufw_rules(ip, 'remove')

                await query.edit_message_text(f"❌ Заявка {nick} отклонена")

                # Уведомляем пользователя
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="⚠️ Ваша заявка на регистрацию была отклонена администратором."
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить пользователя: {e}")

        except Exception as e:
            logger.error(f"Ошибка обработки заявки: {e}", exc_info=True)
            try:
                await query.edit_message_text("⚠️ Произошла ошибка при обработке заявки")
            except:
                pass

    async def list_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Список всех пользователей"""
        if not await self._validate_admin(update):
            return
        query = update.callback_query
        await query.answer()
        users = Database.list_users(approved=True)
        if not users:
            await reply_to_update(update, "Нет зарегистрированных пользователей")
            return
        buttons = []
        for user in users:
            buttons.append([
                InlineKeyboardButton(f"{user[1]} (ID: {user[0]})", callback_data=f"admin_user_{user[0]}")])
        buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_back")])
        buttons.append([InlineKeyboardButton("🏠 В основное меню", callback_data="start")])
        kb = create_keyboard(buttons)
        await reply_to_update(update, "Зарегистрированные пользователи:", kb)

    async def start_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начинаем процесс рассылки"""
        if not await self._validate_admin(update):
            return
        context.user_data['is_broadcasting'] = True
        await reply_to_update(update, "✍️ Введите сообщение для рассылки:")

    async def process_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатываем сообщение для рассылки"""
        if not context.user_data.get('is_broadcasting'):
            return
        context.user_data['is_broadcasting'] = False
        message = update.message.text
        users = Database.list_users(approved=True)
        success_count = 0
        for user in users:
            try:
                await context.bot.send_message(user[0], f"🔔 Сообщение от администратора:\n{message}")
                success_count += 1
            except Exception as e:
                logger.error(f"Не удалось отправить сообщение пользователю {user[0]}: {e}")
        await reply_to_update(update, f"✅ Сообщение отправлено {success_count} из {len(users)} пользователей")

    async def user_management_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None):
        """Меню управления конкретным пользователем"""
        if not await self._validate_admin(update):
            return

        if not user_id:
            query = update.callback_query
            await query.answer()
            user_id = int(query.data.split('_')[-1])

        user = Database.get_user(user_id)
        if not user:
            await reply_to_update(update, "Пользователь не найден")
            return

        buttons = []
        status = "✅ Одобрен" if user['approved'] else "⏳ Ожидает"
        text = (f"Управление пользователем:\n"
                f"ID: {user['tg_id']}\n"
                f"Ник: {user['ingame_nick']}\n"
                f"IP: {user['ip']}\n"
                f"Статус: {status}")

        # Кнопки для всех пользователей
        buttons.extend([
            [InlineKeyboardButton("✏️ Изменить ник", callback_data=f"admin_edit_{user_id}")],
            [InlineKeyboardButton("🌐 Изменить IP", callback_data=f"admin_editip_{user_id}")],
            [InlineKeyboardButton("🗑 Удалить запись", callback_data=f"admin_delete_{user_id}")],
            [InlineKeyboardButton("📨 Отправить сообщение", callback_data=f"admin_msg_{user_id}")]
        ])

        # Дополнительные кнопки для одобренных пользователей
        if user['approved']:
            buttons.extend([
                [InlineKeyboardButton("➕ Добавить в WL", callback_data=f"wl_add_{user_id}"),
                 InlineKeyboardButton("➖ Удалить из WL", callback_data=f"wl_remove_{user_id}")],
                [InlineKeyboardButton("➕ Добавить UFW", callback_data=f"ufw_add_{user_id}"),
                 InlineKeyboardButton("➖ Удалить UFW", callback_data=f"ufw_remove_{user_id}")]
            ])
        else:
            buttons.extend([
                [InlineKeyboardButton("✅ Одобрить", callback_data=f"admin_approve_{user_id}")],
                [InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_reject_{user_id}")]
            ])

        buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_list_users")])
        kb = create_keyboard(buttons)
        await reply_to_update(update, text, kb)

    async def handle_delete_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка удаления пользователя"""
        if not await self._validate_admin(update):
            return

        query = update.callback_query
        await query.answer()

        user_id = int(query.data.split('_')[-1])
        user_data = Database.get_user(user_id)

        if not user_data:
            await reply_to_update(update, "⚠️ Пользователь не найден")
            return

        # Полное удаление пользователя
        Database.delete_user(user_id)
        WhitelistManager.remove_from_whitelist(user_data['ingame_nick'])
        WhitelistManager.manage_ufw_rules(user_data['ip'], 'remove')

        await reply_to_update(update, f"✅ Пользователь {user_data['ingame_nick']} полностью удалён")
        await self.list_users(update, context)

    async def start_send_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса отправки сообщения пользователю"""
        if not await self._validate_admin(update):
            return

        query = update.callback_query
        await query.answer()

        user_id = int(query.data.split('_')[-1])
        user_data = Database.get_user(user_id)

        if not user_data:
            await reply_to_update(update, "⚠️ Пользователь не найден")
            return

        context.user_data['message_user_id'] = user_id
        context.user_data['message_user_nick'] = user_data['ingame_nick']

        await reply_to_update(update, f"✉️ Введите сообщение для пользователя {user_data['ingame_nick']}:")
        return "admin_message_input"

    async def process_user_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка введённого сообщения для пользователя"""
        user_id = context.user_data.get('message_user_id')
        user_nick = context.user_data.get('message_user_nick')
        message = update.message.text

        if not user_id or not message:
            await reply_to_update(update, "⚠️ Ошибка: не хватает данных")
            return ConversationHandler.END

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📨 Сообщение от администратора:\n{message}"
            )
            await reply_to_update(update, f"✅ Сообщение отправлено пользователю {user_nick}")
        except Exception as e:
            await reply_to_update(update, f"⚠️ Не удалось отправить сообщение: {str(e)}")

        return ConversationHandler.END

    async def handle_whitelist_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка действий с whitelist"""
        if not await self._validate_admin(update):
            return
        query = update.callback_query
        await query.answer()
        action, user_id = query.data.split('_')[0], int(query.data.split('_')[-1])
        user = Database.get_user(user_id)
        if not user:
            await reply_to_update(update, "Пользователь не найден")
            return
        nickname = user['ingame_nick']
        ip = user['ip']
        if action == 'wl':
            # Обработка whitelist действий
            sub_action = query.data.split('_')[1]
            if sub_action == 'add':
                success, message = WhitelistManager.add_to_whitelist(nickname)
            elif sub_action == 'remove':
                success, message = WhitelistManager.remove_from_whitelist(nickname)
            await reply_to_update(update, message)
            await self.user_management_menu(update, context, user_id)
        elif action == 'ufw':
            # Обработка UFW действий
            if not ip:
                await reply_to_update(update, "IP адрес не указан для этого пользователя")
                return
            sub_action = query.data.split('_')[1]
            success, message = WhitelistManager.manage_ufw_rules(ip, sub_action)
            await reply_to_update(update, message)
            await self.user_management_menu(update, context, user_id)

    async def start_edit_nick(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса редактирования ника пользователя"""
        if not await self._validate_admin(update):
            return

        query = update.callback_query
        await query.answer()

        user_id = int(query.data.split('_')[-1])
        user_data = Database.get_user(user_id)

        if not user_data:
            await reply_to_update(update, "⚠️ Пользователь не найден")
            return ConversationHandler.END

        context.user_data['edit_user_id'] = user_id
        context.user_data['edit_type'] = 'nick'

        await reply_to_update(
            update,
            f"✏️ Введите новый ник для пользователя {user_data['ingame_nick']}:\n"
            "• Только латиница, цифры и _\n"
            "• От 3 до 16 символов\n"
            "• Будет преобразован в нижний регистр"
        )
        return "edit_nick"

    async def edit_user_nick(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Сохранение нового ника пользователя с приведением к нижнему регистру"""
        user_id = context.user_data.get('edit_user_id')
        if not user_id:
            await reply_to_update(update, "⚠️ Ошибка: не найден ID пользователя")
            return ConversationHandler.END

        user_data = Database.get_user(user_id)
        if not user_data:
            await reply_to_update(update, "⚠️ Пользователь не найден")
            return ConversationHandler.END

        raw_nick = update.message.text.strip()
        new_nick = raw_nick.lower()  # Приводим к нижнему регистру
        old_nick = user_data['ingame_nick']

        # Валидация ника (уже в нижнем регистре)
        is_valid, message = Registration.validate_nickname(new_nick)
        if not is_valid:
            await reply_to_update(update, message)
            return "edit_nick"

        # Проверяем, изменился ли ник
        if new_nick == old_nick.lower():
            await reply_to_update(update, "⚠️ Новый ник не отличается от текущего")
            return "edit_nick"

        # Очищаем старые данные
        if user_data['approved']:
            WhitelistManager.remove_from_whitelist(old_nick)

        # Обновляем данные (сохраняем в нижнем регистре)
        Database.update_user(user_id, ingame_nick=new_nick)

        # Если пользователь одобрен - добавляем новые данные
        if user_data['approved']:
            # WhitelistManager.add_to_whitelist(new_nick)

            # Уведомляем самого пользователя
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🔄 Администратор изменил ваш игровой ник:\n"
                         f"Старый: {old_nick}\n"
                         f"Новый: {new_nick}\n\n"
                         f"Если это ошибка, обратитесь к администрации."
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")

        await reply_to_update(
            update,
            f"✅ Ник пользователя успешно изменён:\n"
            f"Старый: {old_nick}\nНовый: {new_nick}\n\n"
            f"Пользователь получил уведомление об изменении."
        )
        return ConversationHandler.END

    async def start_edit_ip(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса редактирования IP пользователя"""
        if not await self._validate_admin(update):
            return

        query = update.callback_query
        await query.answer()

        user_id = int(query.data.split('_')[-1])
        user_data = Database.get_user(user_id)

        if not user_data:
            await reply_to_update(update, "⚠️ Пользователь не найден")
            return ConversationHandler.END

        context.user_data['edit_user_id'] = user_id
        context.user_data['edit_type'] = 'ip'

        await reply_to_update(
            update,
            f"🌐 Введите новый IP для пользователя {user_data['ingame_nick']}:\n"
            "• Формат: 123.45.67.89 (IPv4) или 2001:0db8:85a3:0000:0000:8a2e:0370:7334 (IPv6)\n"
            "• Можно узнать на сайтах типа 2ip.ru"
        )
        return "edit_ip"

    async def edit_user_ip(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Сохранение нового IP пользователя с уведомлением самого игрока"""
        user_id = context.user_data.get('edit_user_id')
        if not user_id:
            await reply_to_update(update, "⚠️ Ошибка: не найден ID пользователя")
            return ConversationHandler.END

        user_data = Database.get_user(user_id)
        if not user_data:
            await reply_to_update(update, "⚠️ Пользователь не найден")
            return ConversationHandler.END

        new_ip = update.message.text.strip()
        old_ip = user_data['ip']

        # Валидация IP
        is_valid, message = Registration.validate_ip(new_ip)
        if not is_valid:
            await reply_to_update(update, message)
            return "edit_ip"

        # Очищаем старые правила
        if user_data['approved']:
            WhitelistManager.manage_ufw_rules(old_ip, 'remove')

        # Обновляем данные
        Database.update_user(user_id, ip=new_ip)

        # Если пользователь одобрен - добавляем новые правила
        if user_data['approved']:
            # WhitelistManager.manage_ufw_rules(new_ip, 'add')

            # Уведомляем самого пользователя
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🔄 Администратор изменил ваш IP-адрес для доступа:\n"
                         f"Старый: {old_ip}\n"
                         f"Новый: {new_ip}\n\n"
                         f"Если вы не запрашивали это изменение, немедленно обратитесь к администрации!"
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")

        await reply_to_update(
            update,
            f"✅ IP пользователя успешно изменён:\n"
            f"Старый: {old_ip}\nНовый: {new_ip}\n\n"
            f"Пользователь получил уведомление об изменении."
        )
        return ConversationHandler.END

    async def reload_whitelist(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Перезагрузка whitelist"""
        if not await self._validate_admin(update):
            return
        query = update.callback_query
        await query.answer()
        success, message = WhitelistManager.reload_whitelist()
        await reply_to_update(update, message)

    async def delete_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """Полное удаление пользователя администратором"""
        user_data = Database.get_user(user_id)
        if not user_data:
            await reply_to_update(update, "⚠️ Пользователь не найден!")
            return
        # Полная очистка
        WhitelistManager.remove_from_whitelist(user_data['ingame_nick'])
        WhitelistManager.manage_ufw_rules(user_data['ip'], 'remove')
        Database.delete_user(user_id)
        await reply_to_update(update, f"✅ Пользователь {user_data['ingame_nick']} полностью удалён")
        await self.list_users(update, context)

    async def handle_back(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка кнопки Назад"""
        query = update.callback_query
        await query.answer()
        if query.data == "admin_back":
            await self.send_admin_menu(update, context)
        elif query.data == "admin_users":
            await self.list_users(update, context)


# ==================== СЕРВЕР ====================
class Server:
    def __init__(self, bot):
        """Класс для управления сервером Minecraft"""
        self.bot = bot
        self.server_module = MinecraftServer(bot)
        self.players_list = []  # Список игроков онлайн

    async def server_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Главное меню серверных функций"""
        menu_text = "🎮 Управление сервером Minecraft\nВыберите действие:"
        buttons = [
            [InlineKeyboardButton("👥 Игроки онлайн", callback_data="server_players")],
            [InlineKeyboardButton("💬 Глобальный чат", callback_data="server_send_chat")],
            [InlineKeyboardButton("📨 Приватное сообщение", callback_data="server_private_msg")],
            [InlineKeyboardButton("☀️ Управление погодой", callback_data="server_weather")],
            [InlineKeyboardButton("⏱ Управление временем", callback_data="server_time")],
            [InlineKeyboardButton("⚔️ Настройки PVP", callback_data="server_pvp")],
            [InlineKeyboardButton("🎚 Сложность игры", callback_data="server_difficulty")],
            [InlineKeyboardButton("🔨 Блокировка игрока", callback_data="server_ban")],
            [InlineKeyboardButton("🔄 Обновить whitelist", callback_data="server_reload_whitelist")],
            [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")],
            [InlineKeyboardButton("🏠 В главное меню", callback_data="start")]
        ]
        await reply_to_update(update, menu_text, create_keyboard(buttons))

    # ===== ОСНОВНЫЕ МЕТОДЫ =====
    async def get_players_count(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение списка игроков онлайн"""
        success, response = self.server_module.get_online_players()
        if success:
            self.players_list = response.split(', ') if ', ' in response else [response]
            await reply_to_update(update, f"Игроки онлайн: {response}")
        else:
            await reply_to_update(update, f"Ошибка: {response}")

    async def send_chat_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос сообщения для глобального чата"""
        await reply_to_update(update, "Введите сообщение для отправки в глобальный чат:")
        return "server_chat_msg_input"

    async def process_chat_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка сообщения для чата"""
        message = update.message.text.strip()
        if not message:
            await reply_to_update(update, "Сообщение не может быть пустым!")
            return "server_chat_msg_input"

        success, response = self.server_module.send_chat_message(message)
        await reply_to_update(update, response if success else f"Ошибка: {response}")
        return ConversationHandler.END

    # ===== МЕНЮ ПОГОДЫ =====
    async def get_weather_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню управления погодой"""
        buttons = [
            [InlineKeyboardButton("☀️ Ясно", callback_data="weather_clear")],
            [InlineKeyboardButton("🌧 Дождь", callback_data="weather_rain")],
            [InlineKeyboardButton("⛈ Гроза", callback_data="weather_thunder")],
            [InlineKeyboardButton("◀️ Назад", callback_data="admin_server")]
        ]
        await reply_to_update(update, "Выберите тип погоды:", create_keyboard(buttons))

    async def set_weather(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Установка погоды"""
        query = update.callback_query
        weather_type = query.data.split('_')[1]
        success, message = self.server_module.set_weather(weather_type)
        await reply_to_update(update, message)
        await self.server_menu(update, context)

    # ===== МЕНЮ ВРЕМЕНИ СУТОК =====
    async def get_time_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню управления временем"""
        buttons = [
            [InlineKeyboardButton("🌅 Утро", callback_data="time_day")],
            [InlineKeyboardButton("🌃 Ночь", callback_data="time_night")],
            [InlineKeyboardButton("☀️ Полдень", callback_data="time_noon")],
            [InlineKeyboardButton("🌙 Полночь", callback_data="time_midnight")],
            [InlineKeyboardButton("◀️ Назад", callback_data="admin_server")]
        ]
        await reply_to_update(update, "Установить время суток:", create_keyboard(buttons))

    async def set_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Установка времени"""
        query = update.callback_query
        time_type = query.data.split('_')[1]
        success, message = self.server_module.set_time(time_type)
        await reply_to_update(update, message)
        await self.server_menu(update, context)

    # ===== МЕНЮ PVP =====
    async def get_pvp_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню управления PVP"""
        buttons = [
            [InlineKeyboardButton("✅ Включить PVP", callback_data="pvp_enable")],
            [InlineKeyboardButton("❌ Выключить PVP", callback_data="pvp_disable")],
            [InlineKeyboardButton("◀️ Назад", callback_data="admin_server")]
        ]
        await reply_to_update(update, "Настройки PVP:", create_keyboard(buttons))

    async def toggle_pvp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Включение/выключение PVP"""
        query = update.callback_query
        action = query.data.split('_')[1]
        if action == "enable":
            success, message = self.server_module.enable_pvp()
        else:
            success, message = self.server_module.disable_pvp()
        await reply_to_update(update, message)
        await self.server_menu(update, context)

    # ===== МЕНЮ СЛОЖНОСТИ =====
    async def get_difficulty_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню выбора сложности"""
        buttons = [
            [InlineKeyboardButton("😊 Мирная", callback_data="difficulty_peaceful")],
            [InlineKeyboardButton("😃 Легкая", callback_data="difficulty_easy")],
            [InlineKeyboardButton("😐 Нормальная", callback_data="difficulty_normal")],
            [InlineKeyboardButton("😈 Сложная", callback_data="difficulty_hard")],
            [InlineKeyboardButton("◀️ Назад", callback_data="admin_server")]
        ]
        await reply_to_update(update, "Выберите сложность:", create_keyboard(buttons))

    async def set_difficulty(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Установка сложности"""
        query = update.callback_query
        difficulty = query.data.split('_')[1]
        success, message = self.server_module.set_difficulty(difficulty)
        await reply_to_update(update, message)
        await self.server_menu(update, context)

    # ===== МЕНЮ ПРИВАТНЫХ СООБЩЕНИЙ =====
    async def start_private_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса отправки приватного сообщения"""
        success, players = self.server_module.get_online_players()
        if not success or not players:
            await reply_to_update(update, "Нет игроков онлайн для отправки сообщения")
            return
        self.players_list = players.split(', ')
        buttons = [[InlineKeyboardButton(player, callback_data=f"privmsg_{player}")]
                   for player in self.players_list]
        buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_server")])
        await reply_to_update(update, "Выберите игрока:", create_keyboard(buttons))
        return "privmsg_select_player"

    async def select_player_for_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора игрока"""
        query = update.callback_query
        player = query.data.split('_')[1]
        context.user_data['selected_player'] = player
        await reply_to_update(update, f"Введите сообщение для игрока {player}:")
        return "privmsg_enter_text"

    async def send_private_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправка приватного сообщения"""
        message = update.message.text
        player = context.user_data['selected_player']
        success, response = self.server_module.send_private_message(player, message)
        await reply_to_update(update, response if success else f"Ошибка: {response}")
        return ConversationHandler.END

    # ===== МЕНЮ БЛОКИРОВКИ ИГРОКОВ =====
    async def start_ban_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню управления блокировками"""
        buttons = [
            [InlineKeyboardButton("⛔ Заблокировать игрока", callback_data="server_ban")],
            [InlineKeyboardButton("✅ Разблокировать игрока", callback_data="server_unban")],
            [InlineKeyboardButton("◀️ Назад", callback_data="admin_server")]
        ]
        await reply_to_update(update, "Управление блокировками игроков:", create_keyboard(buttons))

    async def start_ban_player(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса блокировки игрока"""
        registered_users = Database.list_users(approved=True)
        if not registered_users:
            await reply_to_update(update, "Нет зарегистрированных игроков")
            return
        buttons = [[InlineKeyboardButton(f"{user[2]} (ID: {user[0]})", callback_data=f"ban_{user[0]}")]
                   for user in registered_users]
        buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="ban_menu")])
        await reply_to_update(update, "Выберите игрока для блокировки:", create_keyboard(buttons))

    async def start_unban_player(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса разблокировки игрока"""
        # Здесь нужно получить список забаненных игроков с сервера
        success, banned_players = self.server_module.get_banned_players()
        if not success:
            await reply_to_update(update, f"Ошибка получения списка забаненных: {banned_players}")
            return
        if not banned_players:
            await reply_to_update(update, "Нет забаненных игроков")
            return
        buttons = [[InlineKeyboardButton(player, callback_data=f"unban_{player}")]
                   for player in banned_players]
        buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="ban_menu")])
        await reply_to_update(update, "Выберите игрока для разблокировки:", create_keyboard(buttons))

    async def ban_player(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Блокировка выбранного игрока"""
        query = update.callback_query
        user_id = int(query.data.split('_')[1])
        user = Database.get_user(user_id)
        if not user:
            await reply_to_update(update, "Игрок не найден в базе данных!")
            return
        success, response = self.server_module.ban_player(user['ingame_nick'])
        await reply_to_update(update, response)
        await self.start_ban_menu(update, context)

    async def unban_player(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Разблокировка выбранного игрока"""
        query = update.callback_query
        player_name = query.data.split('_')[1]
        success, response = self.server_module.unban_player(player_name)
        await reply_to_update(update, response)
        await self.start_ban_menu(update, context)

    # ===== ДРУГИЕ МЕТОДЫ =====
    async def reload_whitelist(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Перезагрузка whitelist"""
        success, message = WhitelistManager.reload_whitelist()
        await reply_to_update(update, message)


# ==================== СЕРВИС ====================
class Service:
    def __init__(self, bot):
        self.bot = bot
        self.server_service = ServerService(bot)
        self.logging_enabled = True

    async def service_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню сервисных функций"""
        try:
            stats = self.bot.server_service.get_server_stats()
            uptime = self.get_server_uptime()
            world_size = self.bot.server_service.get_world_size()
        except Exception as e:
            stats = {"status": "Ошибка получения данных", "cpu": "N/A", "ram": "N/A", "tps": "N/A"}
            uptime = f"⚠️ Ошибка: {str(e)}"
            world_size = "N/A"
        status_text = (
            f"🛠 Сервисные функции\n\n"
            f"🔹 Статус: {stats.get('status', 'N/A')}\n"
            f"🔹 Время работы: {uptime}\n"
            f"🔹 CPU: {stats.get('cpu', 'N/A')}\n"
            f"🔹 RAM: {stats.get('ram', 'N/A')}\n"
            f"🔹 TPS: {stats.get('tps', 'N/A')}\n"
            f"🔹 Размер мира: {world_size}\n"
            f"🔹 Логирование: {'ВКЛ' if self.logging_enabled else 'ВЫКЛ'}"
        )
        kb = create_keyboard([
            [InlineKeyboardButton("🔄 Копия мира", callback_data="service_backup")],
            [InlineKeyboardButton("🟢 Включение сервера", callback_data="service_start")],
            [InlineKeyboardButton("🟠 Перезагрузка сервера", callback_data="service_restart")],
            [InlineKeyboardButton("🔴 Выключение сервера", callback_data="service_stop")],
            [InlineKeyboardButton("📝 Ввод команды", callback_data="service_exec_cmd")],
            [
                InlineKeyboardButton("📋 Логи ВКЛ", callback_data="service_logging_on"),
                InlineKeyboardButton("📴 Логи ВЫКЛ", callback_data="service_logging_off")
            ],
            [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")],
            [InlineKeyboardButton("🏠 В основное меню", callback_data="start")]
        ])
        await reply_to_update(update, status_text, kb)

    async def execute_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на ввод команды для сервера"""
        await reply_to_update(update, "Введите команду для выполнения на сервере:")
        context.user_data["waiting_for_command"] = True  # Устанавливаем флаг ожидания команды
        return "service_cmd_input"

    async def process_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка введенной команды"""
        command = update.message.text.strip()
        if not command:
            await reply_to_update(update, "⚠️ Команда не может быть пустой")
            return "service_cmd_input"
        success, message = self.server_service.execute_command(command)
        if success:
            await reply_to_update(update, f"✅ Команда выполнена:\n{message}")
        else:
            await reply_to_update(update, f"⚠️ Ошибка выполнения:\n{message}")
        context.user_data["waiting_for_command"] = False  # Сбрасываем флаг после выполнения
        return ConversationHandler.END

    async def backup_world(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Создание копии мира"""
        success, message = self.bot.server_service.backup_world()
        await reply_to_update(update, message)

    async def start_server(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запуск сервера"""
        success, message = self.bot.server_service.start_server()
        await reply_to_update(update, message)

    async def restart_server(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Перезагрузка сервера"""
        success, message = self.bot.server_service.restart_server()
        await reply_to_update(update, message)

    async def stop_server(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Остановка сервера"""
        success, message = self.bot.server_service.stop_server()
        await reply_to_update(update, message)

    async def toggle_logging(self, update: Update, context: ContextTypes.DEFAULT_TYPE, enable: bool):
        """Включение/выключение логирования через screen"""
        query = update.callback_query
        await query.answer()
        if enable:
            success, message = self.bot.server_service.enable_logging()
        else:
            success, message = self.bot.server_service.disable_logging()
        if success:
            status = "включено" if enable else "выключено"
            await reply_to_update(update, f"✅ Логирование {status}")
        else:
            await reply_to_update(update, f"⚠️ Ошибка: {message}")

    async def logging_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Включение логирования"""
        await self.toggle_logging(update, context, True)

    async def logging_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Выключение логирования"""
        await self.toggle_logging(update, context, False)

    def get_server_uptime(self):
        """Получение времени работы сервера"""
        try:
            return self.bot.server_service.get_uptime()
        except Exception as e:
            return f"⚠️ Ошибка получения времени работы: {str(e)}"

    def _create_command_handler(self):
        """Создает обработчик для ввода команд"""
        return ConversationHandler(
            entry_points=[CallbackQueryHandler(self.execute_command, pattern="^service_exec_cmd$")],
            states={"service_cmd_input": [MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_command)]},
            fallbacks=[
                CommandHandler("cancel", lambda u, c: reply_to_update(u, "Отмена ввода команды")),
                CallbackQueryHandler(lambda u, c: reply_to_update(u, "Отмена ввода команды"), pattern="^cancel$")
            ]
        )


# ==================== WHITELIST ====================
class WhitelistManager:
    @staticmethod
    def add_to_whitelist(nickname):
        """Добавление игрока в whitelist"""
        try:
            add_to_whitelist(nickname)
            return True, f"Игрок {nickname} добавлен в whitelist"
        except Exception as e:
            return False, f"Ошибка при добавлении в whitelist: {str(e)}"

    @staticmethod
    def remove_from_whitelist(nickname):
        """Удаление игрока из whitelist"""
        try:
            remove_from_whitelist(nickname)
            return True, f"Игрок {nickname} удалён из whitelist"
        except Exception as e:
            return False, f"Ошибка при удалении из whitelist: {str(e)}"

    @staticmethod
    def reload_whitelist():
        """Перезагрузка whitelist"""
        try:
            reload_whitelist()
            return True, "Whitelist перезагружен"
        except Exception as e:
            return False, f"Ошибка при перезагрузке whitelist: {str(e)}"

    @staticmethod
    def manage_ufw_rules(ip: str, action: str):
        """Безопасное управление UFW правилами"""
        try:
            if not ip:
                return False, "IP не указан"
            if action == 'add':
                return add_ufw_rules(ip)
            elif action == 'remove':
                return remove_ufw_rules(ip)
            else:
                return False, "Неизвестное действие"
        except Exception as e:
            logger.error(f"Ошибка UFW для IP {ip}: {e}")
            return False, f"Ошибка: {str(e)}"

    @staticmethod
    def full_cleanup(nickname: str, ip: str):
        """Полная очистка всех следов пользователя"""
        try:
            # Удаление из whitelist
            remove_from_whitelist(nickname)
            # Удаление правил UFW
            remove_ufw_rules(ip)
            # Перезагрузка whitelist
            reload_whitelist()
            return True, "Полная очистка выполнена"
        except Exception as e:
            return False, f"Ошибка очистки: {str(e)}"


# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    try:
        Database.init()
        bot = MinecraftBot()
        logger.info("Бот запущен")
        bot.application.run_polling()
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}")
        raise
