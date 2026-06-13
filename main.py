# -*- coding: utf-8 -*-
import asyncio
import sqlite3
import os
import glob
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.functions.contacts import BlockRequest, UnblockRequest
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.types import InputPhoto
from telethon.errors import FloodWaitError
import aiohttp

# =====================================================================
# ⚙️ قسم الإعدادات (تُقرأ من متغيرات البيئة لأمان أكثر)
# =====================================================================

API_ID = int(os.environ.get('API_ID', 0))
API_HASH = os.environ.get('API_HASH', '')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
SESSION_STRING = os.environ.get('SESSION_STRING', '')

DB_NAME = 'userbot_master.db'
BACKUP_FOLDER = 'backup_photos_acc'

# =====================================================================

# التحقق من وجود المتغيرات الضرورية
if not API_ID or not API_HASH or not SESSION_STRING:
    print("❌ خطأ: تأكد من ضبط متغيرات البيئة: API_ID, API_HASH, SESSION_STRING")
    exit(1)

if not os.path.exists(BACKUP_FOLDER):
    os.makedirs(BACKUP_FOLDER)

# Cache للحساب
_me_cache = None

async def get_me_cached(client):
    global _me_cache
    if _me_cache is None:
        _me_cache = await client.get_me()
    return _me_cache

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def get_reply_media():
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.mp4', '*.gif']:
        files = glob.glob(f'reply_media{ext}')
        if files:
            return files[0]
    return None

def init_db():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS profile_backup
                     (id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, bio TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS auto_reply
                     (id INTEGER PRIMARY KEY, enabled INTEGER, message TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS smart_replies
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, trigger TEXT UNIQUE, response TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS muted_users
                     (user_id INTEGER PRIMARY KEY)''')
        # جدول الاستثناءات من الرد التلقائي
        c.execute('''CREATE TABLE IF NOT EXISTS auto_reply_exceptions
                     (user_id INTEGER PRIMARY KEY)''')
        # جدول تتبع من وصله الرد التلقائي (لمنع التكرار)
        c.execute('''CREATE TABLE IF NOT EXISTS replied_users
                     (user_id INTEGER PRIMARY KEY, last_reply REAL)''')
        # جدول الملاحظات
        c.execute('''CREATE TABLE IF NOT EXISTS notes
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, created_at TEXT)''')
        # جدول الإعدادات العامة (وضع الشبح، الذكاء الاصطناعي)
        c.execute('''CREATE TABLE IF NOT EXISTS settings
                     (key TEXT PRIMARY KEY, value TEXT)''')

        default_caption = (
            "╭━━━▬▭▬  ⚡️  ▬▭▬━━━╮\n"
            "    مـرحـبـاً بـك عـزيـزي 🧑‍💻\n"
            "╰━━━▬▭▬  ⚜️  ▬▭▬━━━╯\n\n"
            "⚠️ **الـرد الـتـلـقـائـي للـحـسـاب الـمـطـوّر**\n"
            "« صـاحـب الـحـسـاب غـيـر مـتـواجـد حـالـيـاً »\n\n"
            "💬 أترك رسالتك بوضوح ولُطف، وسأقوم بالرد عليك فور تواجدي. 🖤\n\n"
            "⏳ __يُرجى عدم تكرار الاتصال أو السبام المزعج.__"
        )
        c.execute('INSERT OR IGNORE INTO auto_reply (id, enabled, message) VALUES (1, 1, ?)', (default_caption,))
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('ghost_mode', '0')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('ai_reply', '0')")
        conn.commit()

def get_setting(key):
    with get_db() as conn:
        row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        return row['value'] if row else '0'

def set_setting(key, value):
    with get_db() as conn:
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
        conn.commit()

def estimate_creation_date(telegram_id):
    id_milestones = [
        (0,          datetime(2013, 8, 1).timestamp()),
        (50000000,   datetime(2014, 8, 1).timestamp()),
        (120000000,  datetime(2015, 8, 1).timestamp()),
        (230000000,  datetime(2016, 8, 1).timestamp()),
        (400000000,  datetime(2017, 8, 1).timestamp()),
        (650000000,  datetime(2018, 8, 1).timestamp()),
        (950000000,  datetime(2019, 8, 1).timestamp()),
        (1250000000, datetime(2020, 8, 1).timestamp()),
        (1850000000, datetime(2021, 8, 1).timestamp()),
        (5000000000, datetime(2022, 8, 1).timestamp()),
        (6200000000, datetime(2023, 8, 1).timestamp()),
        (7000000000, datetime(2024, 8, 1).timestamp()),
        (7800000000, datetime(2025, 1, 1).timestamp()),
        (8500000000, datetime(2026, 1, 1).timestamp()),
    ]
    if telegram_id < 0:
        return "غير معروف (مجموعة قديمة أو حساب خارجي)"
    closest_milestone = id_milestones[0]
    next_milestone = id_milestones[-1]
    for i in range(len(id_milestones) - 1):
        if id_milestones[i][0] <= telegram_id <= id_milestones[i + 1][0]:
            closest_milestone = id_milestones[i]
            next_milestone = id_milestones[i + 1]
            break
    id_diff = next_milestone[0] - closest_milestone[0]
    time_diff = next_milestone[1] - closest_milestone[1]
    if id_diff == 0:
        estimated_timestamp = closest_milestone[1]
    else:
        ratio = (telegram_id - closest_milestone[0]) / id_diff
        estimated_timestamp = closest_milestone[1] + (ratio * time_diff)
    return datetime.fromtimestamp(estimated_timestamp).strftime('%Y / %m (%B)')


# =====================================================================
# مهمة تحديث الوقت بالاسم الأخير كل دقيقة
# =====================================================================
# إعدادات الوقت
time_settings = {
    'enabled': True,
    'pattern': 1,
    'font': 1,
    'format': 12
}

def format_time_digits(hour, minute, font):
    """تحويل الأرقام حسب الخط المختار"""
    normal = f"{hour}:{minute:02d}"
    if font == 1:
        return normal
    elif font == 2:
        # ياباني
        japanese = {'0':'０','1':'１','2':'２','3':'３','4':'４','5':'５','6':'６','7':'７','8':'８','9':'９',':':'：'}
        return ''.join(japanese.get(c, c) for c in normal)
    elif font == 3:
        # بولد
        bold = {'0':'𝟎','1':'𝟏','2':'𝟐','3':'𝟑','4':'𝟒','5':'𝟓','6':'𝟔','7':'𝟕','8':'𝟖','9':'𝟗',':':':'}
        return ''.join(bold.get(c, c) for c in normal)
    elif font == 4:
        # إيطالي بولد
        italic = {'0':'𝟬','1':'𝟭','2':'𝟮','3':'𝟯','4':'𝟰','5':'𝟱','6':'𝟲','7':'𝟳','8':'𝟴','9':'𝟵',':':':'}
        return ''.join(italic.get(c, c) for c in normal)
    return normal

def apply_pattern(time_str, pattern):
    """تطبيق النمط على الوقت"""
    patterns = {
        1: time_str,
        2: f"〔{time_str}〕",
        3: f"⏰{time_str}⏰",
        4: f"❮{time_str}❯",
        5: f"『{time_str}』",
    }
    return patterns.get(pattern, time_str)

async def update_name_with_time(client):
    from datetime import timezone, timedelta
    iraq_tz = timezone(timedelta(hours=3))
    while True:
        try:
            if time_settings['enabled']:
                now = datetime.now(iraq_tz)
                if time_settings['format'] == 12:
                    hour = now.hour % 12 or 12
                else:
                    hour = now.hour
                time_str = format_time_digits(hour, now.minute, time_settings['font'])
                time_str = apply_pattern(time_str, time_settings['pattern'])
                await client(UpdateProfileRequest(last_name=time_str))
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
        except Exception:
            pass
        await asyncio.sleep(60)


# =====================================================================
# تسجيل كل الميزات
# =====================================================================
async def register_features(client):
    db_id = 1

    # =========================================================
    # 1. قائمة الأوامر
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.(الاوامر|أوامر|اوامر)'))
    async def show_commands(event):
        commands_text = (
            "✦ ────『قـائـمـة الأوامـر』──── ✦\n\n"
            "• .الاوامر ➪ عرض هذه القائمة\n\n"

            "🎭 **م1 - الانتحال:**\n"
            "▫️ `.انتحال` 👈 بالرد أو اليوزر لنسخ الهوية.\n"
            "▫️ `.رجوع` 👈 استعادة حسابك الأصلي.\n"
            "▫️ `.حفظ_بروفايل` 👈 حفظ بروفايلك الحالي.\n"
            "▫️ `.تاريخ_الانتحال` 👈 آخر شخص انتحلته.\n\n"

            "🛡️ **م2 - الكتم والحظر:**\n"
            "▫️ `.كتم` 👈 بالرد لمنع الشخص من مراسلتك.\n"
            "▫️ `.الغاء_كتم` / `.إلغاء_كتم` 👈 فك الكتم.\n"
            "▫️ `.قائمة_المكتومين` 👈 عرض المكتومين.\n"
            "▫️ `.بلوك` / `.حظر` 👈 حظر الشخص.\n"
            "▫️ `.الغاء_بلوك` / `.إلغاء_بلوك` 👈 فك الحظر.\n"
            "▫️ `.تاريخ` 👈 تاريخ إنشاء الحساب.\n"
            "▫️ `.غادر` 👈 الخروج من المجموعة.\n\n"

            "🤖 **م3 - الرد التلقائي والذكاء الاصطناعي:**\n"
            "▫️ `.تفعيل` / `.تعطيل` 👈 تشغيل/إيقاف الرد.\n"
            "▫️ `.ضبط_الرد [نص]` 👈 تعديل نص الرد.\n"
            "▫️ `.إضافة_رد [كلمة] [رد]` 👈 رد ذكي.\n"
            "▫️ `.حذف_رد [كلمة]` 👈 حذف رد ذكي.\n"
            "▫️ `.استثناء` / `.حذف_استثناء` 👈 استثناء شخص.\n"
            "▫️ `.قائمة_الاستثناءات` 👈 عرض المستثنين.\n"
            "▫️ `.ذكاء تفعيل` / `.ذكاء تعطيل` 👈 الرد بالذكاء الاصطناعي.\n"
            "▫️ `.سؤال [نص]` 👈 سؤال الذكاء الاصطناعي.\n"
            "▫️ `.تلخيص` 👈 بالرد يلخص النص.\n"
            "▫️ `.ترجمة [لغة]` 👈 بالرد يترجم.\n\n"

            "🕐 **م4 - الوقتي:**\n"
            "▫️ `.وقت تفعيل` / `.وقت تعطيل` 👈 تشغيل/إيقاف الوقت.\n"
            "▫️ `.وقت 12ساعة` / `.وقت 24ساعة` 👈 صيغة الوقت.\n"
            "▫️ `.وقت نمط [1-5]` 👈 تغيير النمط.\n"
            "▫️ `.وقت خط [1-4]` 👈 تغيير الخط.\n"
            "▫️ `.وقت مساعدة` 👈 شرح الأنماط والخطوط.\n\n"

            "👥 **م5 - المجموعة:**\n"
            "▫️ `.كتم_عضو` / `.فك_كتم` 👈 كتم/فك كتم عضو.\n"
            "▫️ `.طرد` 👈 طرد عضو.\n"
            "▫️ `.تاك_الكل` / `.تاك_عشوائي` 👈 تاك الأعضاء.\n"
            "▫️ `.تثبيت` / `.فك_تثبيت` 👈 تثبيت رسالة.\n"
            "▫️ `.عدد` 👈 عدد الأعضاء.\n"
            "▫️ `.ادمنية` 👈 قائمة الادمنز.\n"
            "▫️ `.دوري [دقائق] [نص]` 👈 تاك دوري للأعضاء.\n"
            "▫️ `.وقف_دوري` 👈 إيقاف الدوري.\n"
            "▫️ `.ترحيب تفعيل` / `.ترحيب_نص [نص]` 👈 رسالة ترحيب.\n"
            "▫️ `.وداع تفعيل` / `.وداع_نص [نص]` 👈 رسالة وداع.\n"
            "▫️ `.تنظيف_مجموعة [عدد]` 👈 مسح رسائلك.\n\n"

            "💬 **م6 - الخاص:**\n"
            "▫️ `.حالة [نص]` 👈 تغيير البايو.\n"
            "▫️ `.حالة_مسح` 👈 مسح البايو.\n"
            "▫️ `.رسالة_مجدولة [دقائق] [نص]` 👈 إرسال رسالة بعد وقت.\n\n"

            "🎬 **م7 - يوتيوب:**\n"
            "▫️ `.يوتيوب [بحث]` 👈 بحث يوتيوب.\n"
            "▫️ `.فيديو [رقم]` 👈 رابط الفيديو.\n"
            "▫️ `.صوت [رقم]` 👈 تحميل الصوت.\n\n"

            "👻 **م8 - وضع الشبح:**\n"
            "▫️ `.شبح تفعيل` / `.شبح تعطيل` 👈 قراءة بدون علامة.\n\n"

            "📝 **م9 - الملاحظات:**\n"
            "▫️ `.ملاحظة [نص]` 👈 حفظ ملاحظة.\n"
            "▫️ `.ملاحظاتي` 👈 عرض الملاحظات.\n"
            "▫️ `.حذف_ملاحظة [رقم]` 👈 حذف ملاحظة.\n\n"

            "⚡ **م10 - أوامر سريعة:**\n"
            "▫️ `.نسخ_رد` 👈 نسخ نص للمحفوظات.\n"
            "▫️ `.تحويل [يوزر]` 👈 تحويل رسالة.\n"
            "▫️ `.فحص` 👈 بيانات الحساب.\n"
            "▫️ `.حفظ` 👈 حفظ الوسائط.\n"
            "▫️ `.تنظيف [عدد]` 👈 مسح رسائلك.\n"
            "▫️ `.ضبط_صورة` / `.حذف_صورة` 👈 صورة الرد.\n\n"

            "✦ ────『V4 Alpha UserBot』──── ✦"
        )
        await event.edit(commands_text)

    # =========================================================
    # 2. وضع الشبح (قراءة بدون علامة قراءة)
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.شبح\s+(تفعيل|تعطيل)'))
    async def ghost_mode(event):
        cmd = event.pattern_match.group(1)
        if cmd == 'تفعيل':
            set_setting('ghost_mode', '1')
            await event.edit("👻 **تم تفعيل وضع الشبح.** ستقرأ الرسائل بدون علامة قراءة.")
        else:
            set_setting('ghost_mode', '0')
            await event.edit("👁️ **تم تعطيل وضع الشبح.** الوضع الطبيعي مفعل.")

    # مراقبة الرسائل الواردة لوضع الشبح
    @client.on(events.NewMessage(incoming=True))
    async def ghost_handler(event):
        if get_setting('ghost_mode') == '1':
            try:
                await client.send_read_acknowledge(event.chat_id, max_id=event.id, clear_mentions=False)
            except Exception:
                pass

    # =========================================================
    # 3. جدار حماية الكتم
    # =========================================================
    @client.on(events.NewMessage(incoming=True))
    async def mute_enforcer(event):
        if not event.is_private:
            return
        with get_db() as conn:
            if conn.execute('SELECT user_id FROM muted_users WHERE user_id = ?', (event.sender_id,)).fetchone():
                try:
                    await event.delete()
                except Exception:
                    pass

    # =========================================================
    # 4. أوامر الكتم وإلغاء الكتم
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.كتم'))
    async def mute_user(event):
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على الشخص الذي تريد كتمه.")
        reply_msg = await event.get_reply_message()
        target_id = reply_msg.sender_id
        me = await get_me_cached(client)
        if target_id == me.id:
            return await event.edit("❌ لا يمكنك كتم نفسك!")
        with get_db() as conn:
            try:
                conn.execute('INSERT INTO muted_users (user_id) VALUES (?)', (target_id,))
                conn.commit()
                await event.edit("🔇 **تم كتم المستخدم بنجاح.**")
            except sqlite3.IntegrityError:
                await event.edit("⚠️ هذا المستخدم مكتوم بالفعل.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.(الغاء_كتم|إلغاء_كتم)'))
    async def unmute_user(event):
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على الشخص لإلغاء كتمه.")
        reply_msg = await event.get_reply_message()
        target_id = reply_msg.sender_id
        with get_db() as conn:
            conn.execute('DELETE FROM muted_users WHERE user_id = ?', (target_id,))
            conn.commit()
        await event.edit("🔊 **تم إلغاء كتم المستخدم بنجاح.**")

    # =========================================================
    # 5. أوامر الحظر وفك الحظر
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.(بلوك|حظر)'))
    async def block_user(event):
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على الحساب المراد حظره.")
        reply = await event.get_reply_message()
        try:
            await client(BlockRequest(id=reply.sender_id))
            await event.edit("🚫 **تم حظر الحساب بنجاح.**")
        except Exception as e:
            await event.edit(f"❌ فشل الحظر: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.(الغاء_بلوك|إلغاء_بلوك)'))
    async def unblock_user(event):
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على الحساب لفك حظره.")
        reply = await event.get_reply_message()
        try:
            await client(UnblockRequest(id=reply.sender_id))
            await event.edit("✅ **تم فك حظر الحساب بنجاح.**")
        except Exception as e:
            await event.edit(f"❌ فشل فك الحظر: {e}")

    # =========================================================
    # 6. تاريخ إنشاء الحساب
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.تاريخ'))
    async def get_creation_time(event):
        target_id = event.chat_id
        target_name = "المحادثة الحالية"
        if event.is_reply:
            reply = await event.get_reply_message()
            target_id = reply.sender_id
            user_obj = await client.get_entity(target_id)
            target_name = user_obj.first_name
        await event.edit("⏳ `جاري تحليل الهوية الرقمية...`")
        date_string = estimate_creation_date(target_id)
        result_text = (
            f"📅 **تقرير المنشأ:**\n"
            f"━▬▭▬▭▬▭▬▭▬━\n"
            f"👤 **الهدف:** {target_name}\n"
            f"🆔 **ID:** `{target_id}`\n"
            f"📅 **تاريخ التأسيس التقديري:** {date_string}\n"
            f"━▬▭▬▭▬▭▬▭▬━\n"
            f"🕵️‍♂️ *دقة 95% عبر التدرج الرقمي.*"
        )
        await event.edit(result_text)

    # =========================================================
    # 7. مغادرة المجموعة
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.غادر'))
    async def leave_group(event):
        if event.is_private:
            return await event.edit("⚠️ هذا الأمر للمجموعات والقنوات فقط.")
        await event.edit("🏃‍♂️ `جاري المغادرة...`")
        await asyncio.sleep(1)
        try:
            await client(LeaveChannelRequest(event.chat_id))
        except Exception:
            pass

    # =========================================================
    # 8. استثناءات الرد التلقائي
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.استثناء'))
    async def add_exception(event):
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على الشخص لاستثنائه.")
        reply = await event.get_reply_message()
        target_id = reply.sender_id
        try:
            target = await client.get_entity(target_id)
            target_name = target.first_name
        except Exception:
            target_name = str(target_id)
        with get_db() as conn:
            try:
                conn.execute('INSERT INTO auto_reply_exceptions (user_id) VALUES (?)', (target_id,))
                conn.commit()
                await event.edit(f"✅ تم استثناء **{target_name}** من الرد التلقائي.")
            except sqlite3.IntegrityError:
                await event.edit(f"⚠️ **{target_name}** مستثنى بالفعل.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.حذف_استثناء'))
    async def remove_exception(event):
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على الشخص لحذف استثنائه.")
        reply = await event.get_reply_message()
        target_id = reply.sender_id
        with get_db() as conn:
            conn.execute('DELETE FROM auto_reply_exceptions WHERE user_id = ?', (target_id,))
            conn.commit()
        await event.edit("✅ تم حذف الاستثناء بنجاح.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.قائمة_الاستثناءات'))
    async def list_exceptions(event):
        with get_db() as conn:
            rows = conn.execute('SELECT user_id FROM auto_reply_exceptions').fetchall()
        if not rows:
            return await event.edit("📋 لا يوجد أشخاص مستثنون حالياً.")
        text = "📋 **قائمة المستثنين من الرد التلقائي:**\n\n"
        for i, row in enumerate(rows, 1):
            try:
                user = await client.get_entity(row['user_id'])
                name = f"{user.first_name} (@{user.username})" if user.username else user.first_name
            except Exception:
                name = str(row['user_id'])
            text += f"{i}. {name}\n"
        await event.edit(text)

    # =========================================================
    # 9. نظام الرد التلقائي المطور (مع منع التكرار + استثناءات)
    # =========================================================
    @client.on(events.NewMessage(incoming=True))
    async def responder_handler(event):
        if not event.is_private:
            return
        try:
            me = await get_me_cached(client)
            sender = await event.get_sender()
            if sender is None or event.sender_id == me.id:
                return
            if hasattr(sender, 'bot') and sender.bot:
                return
        except Exception:
            return

        msg_text = event.raw_text.lower() if event.raw_text else ""

        with get_db() as conn:
            # تحقق من الكتم أولاً
            if conn.execute('SELECT user_id FROM muted_users WHERE user_id = ?', (event.sender_id,)).fetchone():
                return

            # تحقق من الاستثناء
            if conn.execute('SELECT user_id FROM auto_reply_exceptions WHERE user_id = ?', (event.sender_id,)).fetchone():
                return

            # الردود الذكية
            if msg_text:
                smart = conn.execute(
                    'SELECT response FROM smart_replies WHERE ? LIKE "%" || trigger || "%"',
                    (msg_text,)
                ).fetchone()
                if smart:
                    await asyncio.sleep(0.5)
                    return await event.reply(smart[0])

            # الذكاء الاصطناعي يرد على كل رسالة (بدون قيد التكرار)
            if get_setting('ai_reply') == '1' and msg_text:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            url="https://openrouter.ai/api/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                                "Content-Type": "application/json"
                            },
                            json={
                                "model": "meta-llama/llama-3-8b-instruct:free",
                                "messages": [
                                    {"role": "system", "content": "أنت مساعد شخصي. رد بشكل طبيعي وقصير باللغة العربية. لا تذكر أنك ذكاء اصطناعي."},
                                    {"role": "user", "content": msg_text}
                                ]
                            },
                            timeout=aiohttp.ClientTimeout(total=15)
                        ) as resp:
                            data = await resp.json()
                            ai_text = data['choices'][0]['message']['content']
                            await asyncio.sleep(0.8)
                            await event.reply(ai_text)
                            return
                except Exception:
                    pass

            # تحقق من الرد التلقائي العام
            row = conn.execute('SELECT enabled, message FROM auto_reply WHERE id = 1').fetchone()
            if not row or row['enabled'] != 1:
                return

            # تحقق من التكرار (منع إرسال الرد لنفس الشخص أكثر من مرة)
            already_replied = conn.execute(
                'SELECT user_id FROM replied_users WHERE user_id = ?', (event.sender_id,)
            ).fetchone()
            if already_replied:
                return

            # إرسال الرد التلقائي وتسجيل الشخص
            await asyncio.sleep(0.8)
            media_file = get_reply_media()
            try:
                if media_file:
                    await client.send_file(event.chat_id, media_file, caption=row['message'], reply_to=event.id)
                else:
                    await event.reply(row['message'])
                conn.execute(
                    'INSERT OR REPLACE INTO replied_users (user_id, last_reply) VALUES (?, ?)',
                    (event.sender_id, datetime.now().timestamp())
                )
                conn.commit()
            except Exception:
                pass

    # =========================================================
    # 10. تفعيل/تعطيل الذكاء الاصطناعي
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.ذكاء\s+(تفعيل|تعطيل)'))
    async def toggle_ai(event):
        cmd = event.pattern_match.group(1)
        if cmd == 'تفعيل':
            set_setting('ai_reply', '1')
            await event.edit("🤖 **تم تفعيل الرد بالذكاء الاصطناعي.**")
        else:
            set_setting('ai_reply', '0')
            await event.edit("🤖 **تم تعطيل الرد بالذكاء الاصطناعي.**")

    # =========================================================
    # 11. ضبط وحذف صورة الرد
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.ضبط_صورة'))
    async def set_reply_image(event):
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على الصورة.")
        reply_msg = await event.get_reply_message()
        if not reply_msg.media:
            return await event.edit("⚠️ الرسالة لا تحتوي على ميديا.")
        await event.edit("🔄 `جاري الحفظ...`")
        for ext in ['*.jpg', '*.jpeg', '*.png', '*.mp4', '*.gif']:
            for f in glob.glob(f'reply_media{ext}'):
                os.remove(f)
        try:
            if await reply_msg.download_media(file='reply_media'):
                await event.edit("✅ تم الحفظ بنجاح!")
            else:
                await event.edit("❌ فشل التحميل.")
        except Exception as e:
            await event.edit(f"❌ خطأ: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.حذف_صورة'))
    async def delete_reply_image(event):
        deleted = False
        for ext in ['*.jpg', '*.jpeg', '*.png', '*.mp4', '*.gif']:
            for f in glob.glob(f'reply_media{ext}'):
                os.remove(f)
                deleted = True
        await event.edit("🗑️ تم الحذف." if deleted else "⚠️ لا توجد ميديا مخصصة.")

    # =========================================================
    # 12. انتحال الهوية (محسّن)
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.انتحال(?:\s+@?([\w_]+))?'))
    async def clone_profile(event):
        target = None
        if event.is_reply:
            target = await client.get_entity((await event.get_reply_message()).sender_id)
        elif event.pattern_match.group(1):
            target = await client.get_entity(event.pattern_match.group(1))
        else:
            return await event.edit("⚠️ حدد الشخص بالرد أو اليوزر.")

        await event.edit("🚀 `جاري سحب الهوية والميديا...`")
        try:
            full_target = await client(GetFullUserRequest(target))
            my_user_obj = await get_me_cached(client)
            full_me = await client(GetFullUserRequest('me'))

            # حفظ البيانات الأصلية
            with get_db() as conn:
                conn.execute(
                    'INSERT OR REPLACE INTO profile_backup (id, first_name, last_name, bio) VALUES (?, ?, ?, ?)',
                    (db_id, my_user_obj.first_name, my_user_obj.last_name or "", full_me.full_user.about or "")
                )
                conn.commit()

            # حذف باك أب قديم
            for f in glob.glob(f'{BACKUP_FOLDER}/*'):
                try:
                    os.remove(f)
                except Exception:
                    pass

            # حفظ الصور الأصلية
            my_photos = await client.get_profile_photos('me')
            for i, photo in enumerate(my_photos):
                await client.download_media(photo, f'{BACKUP_FOLDER}/orig_{i}.jpg')

            # تحديث الاسم والبايو
            await client(UpdateProfileRequest(
                first_name=target.first_name,
                last_name=target.last_name or "",
                about=full_target.full_user.about or ""
            ))

            # تحميل صورة الهدف
            downloaded_profile_media = await client.download_profile_photo(target, file="target_current_avatar")

            # حذف الصور الحالية
            if my_photos:
                try:
                    await client(DeletePhotosRequest(id=[
                        InputPhoto(id=p.id, access_hash=p.access_hash, file_reference=p.file_reference)
                        for p in my_photos
                    ]))
                    await asyncio.sleep(2)  # انتظار تأكيد الحذف
                except Exception:
                    pass

            # رفع صورة الهدف
            if downloaded_profile_media:
                try:
                    uploaded_file = await client.upload_file(downloaded_profile_media)
                    if downloaded_profile_media.lower().endswith(('.mp4', '.gif', '.mov')):
                        await client(UploadProfilePhotoRequest(video=uploaded_file, video_start_ts=0.0))
                    else:
                        await client(UploadProfilePhotoRequest(file=uploaded_file))
                    await event.edit(f"✅ تم انتحال **{target.first_name}** بنجاح.")
                    # حفظ تاريخ الانتحال
                    with get_db() as conn:
                        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_cloned', ?)", (target.first_name,))
                        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_cloned_at', ?)", (datetime.now().strftime('%Y-%m-%d %H:%M'),))
                        conn.commit()
                except FloodWaitError as e:
                    await event.edit(f"⚠️ تم نسخ الاسم والبايو، تعديل الصور معلق: انتظر {e.seconds} ثانية.")
                finally:
                    if os.path.exists(downloaded_profile_media):
                        os.remove(downloaded_profile_media)
            else:
                await event.edit(f"✅ تم انتحال البيانات (الهدف لا يملك صورة).")

        except Exception as e:
            await event.edit(f"❌ خطأ أثناء الانتحال: {e}")

    # =========================================================
    # 13. استعادة الهوية الأصلية (محسّنة بشكل كامل)
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.رجوع'))
    async def restore_profile(event):
        await event.edit("♻️ `جاري استعادة الهوية الأصلية...`")
        with get_db() as conn:
            row = conn.execute('SELECT first_name, last_name, bio FROM profile_backup WHERE id = ?', (db_id,)).fetchone()
        if not row:
            return await event.edit("⚠️ لا توجد بيانات أصلية محفوظة.")
        try:
            # 1. استعادة الاسم والبايو
            await client(UpdateProfileRequest(
                first_name=row['first_name'],
                last_name=row['last_name'],
                about=row['bio']
            ))
            await event.edit("♻️ `تم استعادة الاسم... جاري معالجة الصور...`")

            # 2. حذف الصور الحالية مع انتظار تأكيد
            for attempt in range(3):
                try:
                    photos = await client.get_profile_photos('me')
                    if not photos:
                        break
                    await client(DeletePhotosRequest(id=[
                        InputPhoto(id=p.id, access_hash=p.access_hash, file_reference=p.file_reference)
                        for p in photos
                    ]))
                    await asyncio.sleep(3)  # انتظار تأكيد الحذف من السيرفر
                    # تحقق أن الصور اتحذفت فعلاً
                    remaining = await client.get_profile_photos('me')
                    if not remaining:
                        break
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds)
                except Exception:
                    break

            # 3. رفع الصور الأصلية بالترتيب مع انتظار بين كل صورة
            backup_files = sorted(glob.glob(f'{BACKUP_FOLDER}/orig_*.jpg'))
            if backup_files:
                uploaded_count = 0
                for f in backup_files:
                    if os.path.exists(f):
                        for attempt in range(3):  # إعادة المحاولة 3 مرات
                            try:
                                uploaded = await client.upload_file(f)
                                await client(UploadProfilePhotoRequest(file=uploaded))
                                uploaded_count += 1
                                await asyncio.sleep(2)  # انتظار بين كل صورة
                                break
                            except FloodWaitError as e:
                                await asyncio.sleep(e.seconds)
                            except Exception:
                                break

                # تحقق نهائي من وصول الصور
                await asyncio.sleep(2)
                final_photos = await client.get_profile_photos('me')
                if final_photos:
                    await event.edit(f"✅ تمت الاستعادة الكاملة بنجاح. ({len(final_photos)} صورة)")
                else:
                    await event.edit("⚠️ تمت استعادة الاسم والبايو، لكن الصور تأخرت. جرب مرة ثانية.")
            else:
                await event.edit("✅ تمت استعادة الاسم والبايو (لا توجد صور احتياطية).")

        except Exception as e:
            await event.edit(f"❌ خطأ أثناء الاستعادة: {e}")

    # =========================================================
    # 14. الملاحظات
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.ملاحظة\s+(.+)'))
    async def add_note(event):
        note_text = event.pattern_match.group(1)
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M')
        with get_db() as conn:
            conn.execute('INSERT INTO notes (text, created_at) VALUES (?, ?)', (note_text, created_at))
            conn.commit()
        await client.send_message('me', f"📝 **ملاحظة جديدة:**\n{note_text}\n\n🕐 {created_at}")
        await event.edit("✅ تم حفظ الملاحظة في المحفوظات.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.ملاحظاتي'))
    async def list_notes(event):
        with get_db() as conn:
            rows = conn.execute('SELECT id, text, created_at FROM notes ORDER BY id DESC').fetchall()
        if not rows:
            return await event.edit("📋 لا توجد ملاحظات محفوظة.")
        text = "📋 **ملاحظاتك:**\n\n"
        for row in rows:
            text += f"**[{row['id']}]** {row['text']}\n🕐 {row['created_at']}\n\n"
        await event.edit(text)

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.حذف_ملاحظة\s+(\d+)'))
    async def delete_note(event):
        note_id = int(event.pattern_match.group(1))
        with get_db() as conn:
            cursor = conn.execute('DELETE FROM notes WHERE id = ?', (note_id,))
            conn.commit()
            if cursor.rowcount > 0:
                await event.edit(f"✅ تم حذف الملاحظة رقم {note_id}.")
            else:
                await event.edit(f"⚠️ لا توجد ملاحظة برقم {note_id}.")

    # =========================================================
    # 15. الأوامر السريعة
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.نسخ_رد'))
    async def copy_reply(event):
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على الرسالة التي تريد نسخها.")
        reply_msg = await event.get_reply_message()
        if not reply_msg.raw_text:
            return await event.edit("⚠️ الرسالة لا تحتوي على نص.")
        saved_text = f"📌 **نص محفوظ:**\n{reply_msg.raw_text}\n\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        await client.send_message('me', saved_text)
        await event.edit("✅ تم نسخ الرسالة للمحفوظات.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.تحويل\s+@?([\w_]+)'))
    async def forward_message(event):
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على الرسالة التي تريد تحويلها.")
        username = event.pattern_match.group(1)
        reply_msg = await event.get_reply_message()
        try:
            target = await client.get_entity(username)
            await client.forward_messages(target, reply_msg)
            await event.edit(f"✅ تم تحويل الرسالة بنجاح.")
        except Exception as e:
            await event.edit(f"❌ فشل التحويل: {e}")

    # =========================================================
    # 16. فحص بيانات الحساب
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.فحص'))
    async def inspect_user(event):
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على الحساب.")
        reply_msg = await event.get_reply_message()
        await event.edit("🔍 `جاري سحب وفحص المعلومات...`")
        try:
            target_user = await client.get_entity(reply_msg.sender_id)
            full_info = await client(GetFullUserRequest(target_user))
            premium_status = "نعم 👑" if getattr(target_user, 'premium', False) else "لا ❌"
            info_text = (
                f"📊 **تقرير الفحص الاستخباراتي:**\n"
                f"━▬▭▬▭▬▭▬▭▬━\n"
                f"👤 **الاسم:** {target_user.first_name}\n"
                f"🆔 **ID:** `{target_user.id}`\n"
                f"🏷️ **اليوزر:** @{target_user.username or 'لا يوجد'}\n"
                f"👑 **بريميوم؟:** {premium_status}\n"
                f"📝 **البايو:**\n`{full_info.full_user.about or 'فارغ'}`\n"
                f"━▬▭▬▭▬▭▬▭▬━"
            )
            await event.edit(info_text)
        except Exception as e:
            await event.edit(f"❌ فشل الفحص: {e}")

    # =========================================================
    # 17. حفظ الوسائط صامتاً
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.حفظ'))
    async def save_media(event):
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على الوسائط.")
        reply_msg = await event.get_reply_message()
        if not reply_msg.media:
            return await event.edit("⚠️ لا توجد وسائط.")
        await event.edit("🔄 `جاري الحفظ الصامت...`")
        try:
            file = await reply_msg.download_media()
            await client.send_file('me', file, caption="📥 تم الحفظ بنجاح.")
            if os.path.exists(file):
                os.remove(file)
            await event.delete()
        except Exception as e:
            await event.edit(f"❌ فشل الحفظ: {e}")

    # =========================================================
    # 18. تنظيف الرسائل
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.تنظيف\s+(\d+)'))
    async def clean_my_messages(event):
        num_to_delete = int(event.pattern_match.group(1))
        await event.edit(f"🧹 `جاري تنظيف {num_to_delete} رسالة...`")
        count = 0
        async for msg in client.iter_messages(event.chat_id):
            if msg.out:
                try:
                    await msg.delete()
                    count += 1
                    if count >= num_to_delete:
                        break
                except Exception:
                    continue
        confirm = await client.send_message(event.chat_id, f"✅ تم تنظيف {count} رسالة.")
        await asyncio.sleep(2)
        await confirm.delete()

    # =========================================================
    # 19. إدارة الرد التلقائي والردود الذكية
    # =========================================================
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.(تفعيل|تعطيل|ضبط_الرد)'))
    async def auto_reply_handler(event):
        cmd = event.pattern_match.group(1)
        if cmd in ['تفعيل', 'تعطيل']:
            status = 1 if cmd == 'تفعيل' else 0
            with get_db() as conn:
                conn.execute('UPDATE auto_reply SET enabled = ? WHERE id = 1', (status,))
                conn.commit()
            # إعادة تعيين قائمة من رُد عليهم عند التفعيل
            if status == 1:
                with get_db() as conn:
                    conn.execute('DELETE FROM replied_users')
                    conn.commit()
            await event.edit(f"✅ تم {cmd} الرد التلقائي العام.")
        elif cmd == 'ضبط_الرد':
            parts = event.text.split(' ', 1)
            if len(parts) < 2 or not parts[1].strip():
                return await event.edit("⚠️ الصيغة: `.ضبط_الرد [النص الجديد]`")
            with get_db() as conn:
                conn.execute('UPDATE auto_reply SET message = ? WHERE id = 1', (parts[1],))
                conn.commit()
            await event.edit("✅ تم ضبط الرد العام الجديد.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.إضافة_رد'))
    async def add_smart_reply(event):
        args = event.text.split(' ', 2)
        if len(args) < 3:
            return await event.edit("⚠️ الصيغة: `.إضافة_رد [كلمة] [الرد]`")
        with get_db() as conn:
            try:
                conn.execute('INSERT INTO smart_replies (trigger, response) VALUES (?, ?)', (args[1], args[2]))
                conn.commit()
                await event.edit(f"✅ تم حفظ الرد الذكي للكلمة: `{args[1]}`")
            except sqlite3.IntegrityError:
                await event.edit(f"⚠️ الكلمة `{args[1]}` موجودة مسبقاً.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.حذف_رد'))
    async def delete_smart_reply(event):
        args = event.text.split(' ', 1)
        if len(args) < 2 or not args[1].strip():
            return await event.edit("⚠️ الصيغة: `.حذف_رد [الكلمة]`")
        keyword = args[1].strip()
        with get_db() as conn:
            cursor = conn.execute('DELETE FROM smart_replies WHERE trigger = ?', (keyword,))
            conn.commit()
            if cursor.rowcount > 0:
                await event.edit(f"✅ تم حذف الرد الذكي للكلمة: `{keyword}`")
            else:
                await event.edit(f"⚠️ لا يوجد رد مسجل للكلمة: `{keyword}`")

    # =========================================================
    # م1 - اليوتيوب والترفيه
    # =========================================================

    # تخزين نتائج البحث مؤقتاً
    youtube_results = {}

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.يوتيوب\s+(.+)'))
    async def youtube_search(event):
        query = event.pattern_match.group(1).strip()
        await event.edit(f"🔍 `جاري البحث عن: {query}...`")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://www.youtube.com/results",
                    params={"search_query": query},
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    html = await resp.text()

            import re
            pattern = r'"videoId":"([^"]+)".*?"title":\{"runs":\[\{"text":"([^"]+)".*?"longBylineText":\{"runs":\[\{"text":"([^"]+)".*?"lengthText":\{"accessibility":\{"accessibilityData":\{"label":"[^"]*"\}\},"simpleText":"([^"]+)"'
            results_raw = re.findall(r'"videoId":"([^"]{11})"', html)
            titles_raw = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"', html)
            channels_raw = re.findall(r'"ownerText":\{"runs":\[\{"text":"([^"]+)"', html)
            durations_raw = re.findall(r'"lengthText":\{"accessibility":\{"accessibilityData":\{"label":"[^"]*"\}\},"simpleText":"([^"]+)"', html)

            if not results_raw or not titles_raw:
                return await event.edit("❌ ما لقيت نتائج! جرب بحث ثاني.")

            youtube_results[event.chat_id] = []
            text = f"🔍 **نتائج البحث عن:** {query}\n\n"

            count = 0
            seen = set()
            for i, vid_id in enumerate(results_raw):
                if vid_id in seen or count >= 5:
                    break
                seen.add(vid_id)
                title = titles_raw[count] if count < len(titles_raw) else "بدون عنوان"
                channel = channels_raw[count] if count < len(channels_raw) else ""
                duration = durations_raw[count] if count < len(durations_raw) else ""
                url = f"https://youtu.be/{vid_id}"
                youtube_results[event.chat_id].append({'title': title, 'url': url})
                text += f"**{count+1}.** {title}\n📺 {channel} | ⏱ {duration}\n\n"
                count += 1

            if not youtube_results[event.chat_id]:
                return await event.edit("❌ ما لقيت نتائج!")

            text += "━━━━━━━━━━━━━━━\n🎵 تحميل صوت: `.صوت [رقم]`\n🎬 رابط فيديو: `.فيديو [رقم]`"
            await event.edit(text)

        except Exception as e:
            await event.edit(f"❌ خطأ بالبحث: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.فيديو\s+(\d+)'))
    async def youtube_video(event):
        num = int(event.pattern_match.group(1)) - 1
        results = youtube_results.get(event.chat_id, [])
        if not results or num < 0 or num >= len(results):
            return await event.edit("⚠️ ابحث أول بـ `.يوتيوب [اسم]` ثم اختر رقم.")
        item = results[num]
        await event.edit(f"🎬 **{item['title']}**\n\n🔗 {item['url']}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.صوت\s+(\d+)'))
    async def youtube_audio(event):
        num = int(event.pattern_match.group(1)) - 1
        results = youtube_results.get(event.chat_id, [])
        if not results or num < 0 or num >= len(results):
            return await event.edit("⚠️ ابحث أول بـ `.يوتيوب [اسم]` ثم اختر رقم.")
        item = results[num]
        await event.edit(f"⏳ `جاري تحميل الصوت...`\n🎵 {item['title']}")
        try:
            me = await get_me_cached(client)
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.cobalt.tools/",
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json"
                    },
                    json={
                        "url": item['url'],
                        "downloadMode": "audio",
                        "audioFormat": "mp3",
                        "audioBitrate": "128"
                    },
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    data = await resp.json()

            if data.get('status') not in ['tunnel', 'redirect', 'stream']:
                return await event.edit(f"❌ فشل التحميل: {data.get('error', {}).get('code', 'خطأ غير معروف')}")

            download_url = data.get('url')
            if not download_url:
                return await event.edit("❌ ما قدر يجيب رابط التحميل.")

            # تحميل الملف
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    audio_data = await resp.read()

            audio_file = f"audio_{me.id}.mp3"
            with open(audio_file, 'wb') as f:
                f.write(audio_data)

            if os.path.exists(audio_file):
                from telethon.tl.types import DocumentAttributeAudio
                await client.send_file(
                    event.chat_id,
                    audio_file,
                    caption=f"🎵 {item['title']}",
                    attributes=[DocumentAttributeAudio(duration=0, title=item['title'], performer="YouTube")]
                )
                os.remove(audio_file)
                await event.delete()
            else:
                await event.edit("❌ فشل تحميل الصوت.")
            if os.path.exists(audio_file):
                await client.send_file(
                    event.chat_id,
                    audio_file,
                    caption=f"🎵 {item['title']}",
                    attributes=[
                        __import__('telethon').tl.types.DocumentAttributeAudio(
                            duration=0,
                            title=item['title'],
                            performer="YouTube"
                        )
                    ]
                )
                os.remove(audio_file)
                await event.delete()
            else:
                await event.edit("❌ فشل تحميل الصوت.")
        except Exception as e:
            await event.edit(f"❌ خطأ: {e}")

    # =========================================================
    # م2 - أوامر الذكاء الاصطناعي
    # =========================================================

    async def ask_ai(prompt, system="أنت مساعد ذكي يرد بالعربية بشكل واضح ومختصر."):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "meta-llama/llama-3-8b-instruct:free",
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt}
                        ]
                    },
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    data = await resp.json()
                    return data['choices'][0]['message']['content']
        except Exception as e:
            return f"❌ خطأ: {e}"

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.سؤال\s+(.+)'))
    async def ai_question(event):
        question = event.pattern_match.group(1).strip()
        await event.edit("🤖 `جاري التفكير...`")
        answer = await ask_ai(question)
        await event.edit(f"🤖 **سؤال:** {question}\n\n💬 **الجواب:**\n{answer}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.تلخيص'))
    async def ai_summarize(event):
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على الرسالة التي تريد تلخيصها.")
        reply = await event.get_reply_message()
        if not reply.raw_text:
            return await event.edit("⚠️ الرسالة لا تحتوي على نص.")
        await event.edit("📝 `جاري التلخيص...`")
        answer = await ask_ai(
            f"لخص النص التالي بشكل مختصر وواضح:\n\n{reply.raw_text}",
            system="أنت مساعد متخصص بتلخيص النصوص. لخص بنقاط واضحة ومختصرة باللغة العربية."
        )
        await event.edit(f"📝 **الملخص:**\n\n{answer}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.ترجمة\s+(.+)'))
    async def ai_translate(event):
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على الرسالة التي تريد ترجمتها.")
        lang = event.pattern_match.group(1).strip()
        reply = await event.get_reply_message()
        if not reply.raw_text:
            return await event.edit("⚠️ الرسالة لا تحتوي على نص.")
        await event.edit(f"🌐 `جاري الترجمة إلى {lang}...`")
        answer = await ask_ai(
            f"ترجم النص التالي إلى اللغة {lang}، أرسل الترجمة فقط بدون أي شرح:\n\n{reply.raw_text}",
            system="أنت مترجم محترف. ترجم النص المعطى إلى اللغة المطلوبة فقط بدون أي إضافات."
        )
        await event.edit(f"🌐 **الترجمة إلى {lang}:**\n\n{answer}")

    # =========================================================
    # م3 - أوامر الوقتي (التحكم بالوقت بالاسم الأخير)
    # =========================================================

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.وقت\s+تفعيل'))
    async def time_enable(event):
        time_settings['enabled'] = True
        await event.edit("✅ **تم تفعيل الوقت بالاسم الأخير.**")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.وقت\s+تعطيل'))
    async def time_disable(event):
        time_settings['enabled'] = False
        try:
            await client(UpdateProfileRequest(last_name=""))
        except Exception:
            pass
        await event.edit("⛔ **تم تعطيل الوقت وحذفه من الاسم.**")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.وقت\s+(\d{1,2}|24)ساعة?'))
    async def time_format(event):
        fmt = int(event.pattern_match.group(1))
        if fmt in [12, 24]:
            time_settings['format'] = fmt
            await event.edit(f"🕐 **تم تغيير الصيغة إلى {fmt} ساعة.**")
        else:
            await event.edit("⚠️ اكتب `.وقت 12ساعة` أو `.وقت 24ساعة`")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.وقت\s+نمط\s+(\d+)'))
    async def time_pattern(event):
        num = int(event.pattern_match.group(1))
        if 1 <= num <= 5:
            time_settings['pattern'] = num
            examples = {
                1: "3:59",
                2: "〔3:59〕",
                3: "⏰3:59⏰",
                4: "❮3:59❯",
                5: "『3:59』",
            }
            await event.edit(f"✅ **تم تغيير النمط إلى {num}**\nمثال: `{examples[num]}`")
        else:
            await event.edit("⚠️ الأنماط المتاحة من 1 إلى 5.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.وقت\s+خط\s+(\d+)'))
    async def time_font(event):
        num = int(event.pattern_match.group(1))
        if 1 <= num <= 4:
            time_settings['font'] = num
            examples = {
                1: "3:59",
                2: "３：５９",
                3: "𝟑:𝟓𝟗",
                4: "𝟯:𝟱𝟵",
            }
            await event.edit(f"✅ **تم تغيير الخط إلى {num}**\nمثال: `{examples[num]}`")
        else:
            await event.edit("⚠️ الخطوط المتاحة من 1 إلى 4.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.وقت\s+مساعدة?'))
    async def time_help(event):
        await event.edit(
            "🕐 **أوامر الوقت:**\n\n"
            "▫️ `.وقت تفعيل` ← تشغيل الوقت بالاسم\n"
            "▫️ `.وقت تعطيل` ← إيقاف الوقت\n"
            "▫️ `.وقت 12ساعة` ← صيغة 12 ساعة\n"
            "▫️ `.وقت 24ساعة` ← صيغة 24 ساعة\n\n"
            "**الأنماط:**\n"
            "▫️ `.وقت نمط 1` ← `3:59`\n"
            "▫️ `.وقت نمط 2` ← `〔3:59〕`\n"
            "▫️ `.وقت نمط 3` ← `⏰3:59⏰`\n"
            "▫️ `.وقت نمط 4` ← `❮3:59❯`\n"
            "▫️ `.وقت نمط 5` ← `『3:59』`\n\n"
            "**الخطوط:**\n"
            "▫️ `.وقت خط 1` ← `3:59` عادي\n"
            "▫️ `.وقت خط 2` ← `３：５９` ياباني\n"
            "▫️ `.وقت خط 3` ← `𝟑:𝟓𝟗` بولد\n"
            "▫️ `.وقت خط 4` ← `𝟯:𝟱𝟵` إيطالي بولد"
        )

    # =========================================================
    # م4 - أوامر المجموعة
    # =========================================================

    # متغيرات الدوري والترحيب والوداع
    group_settings = {}
    periodic_tasks = {}

    async def get_group_members(client, chat_id):
        """جلب أعضاء المجموعة بدون البوتات"""
        members = []
        async for user in client.iter_participants(chat_id):
            if not user.bot and not user.deleted:
                members.append(user)
        return members

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.كتم_عضو'))
    async def mute_member(event):
        if event.is_private:
            return await event.edit("⚠️ هذا الأمر للمجموعات فقط.")
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على العضو.")
        reply = await event.get_reply_message()
        try:
            from telethon.tl.functions.channels import EditBannedRequest
            from telethon.tl.types import ChatBannedRights
            await client(EditBannedRequest(
                event.chat_id, reply.sender_id,
                ChatBannedRights(until_date=None, send_messages=True)
            ))
            await event.edit(f"🔇 **تم كتم العضو بنجاح.**")
        except Exception as e:
            await event.edit(f"❌ فشل الكتم: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.فك_كتم'))
    async def unmute_member(event):
        if event.is_private:
            return await event.edit("⚠️ هذا الأمر للمجموعات فقط.")
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على العضو.")
        reply = await event.get_reply_message()
        try:
            from telethon.tl.functions.channels import EditBannedRequest
            from telethon.tl.types import ChatBannedRights
            await client(EditBannedRequest(
                event.chat_id, reply.sender_id,
                ChatBannedRights(until_date=None, send_messages=False)
            ))
            await event.edit("🔊 **تم فك كتم العضو بنجاح.**")
        except Exception as e:
            await event.edit(f"❌ فشل فك الكتم: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.طرد'))
    async def kick_member(event):
        if event.is_private:
            return await event.edit("⚠️ هذا الأمر للمجموعات فقط.")
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على العضو.")
        reply = await event.get_reply_message()
        try:
            from telethon.tl.functions.channels import EditBannedRequest
            from telethon.tl.types import ChatBannedRights
            from datetime import timezone as tz, timedelta as td
            ban_until = datetime.now(tz.utc) + td(seconds=31)
            await client(EditBannedRequest(
                event.chat_id, reply.sender_id,
                ChatBannedRights(until_date=ban_until, view_messages=True)
            ))
            await client(EditBannedRequest(
                event.chat_id, reply.sender_id,
                ChatBannedRights(until_date=None, view_messages=False)
            ))
            await event.edit("👟 **تم طرد العضو بنجاح.**")
        except Exception as e:
            await event.edit(f"❌ فشل الطرد: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.تاك_الكل'))
    async def tag_all(event):
        if event.is_private:
            return await event.edit("⚠️ هذا الأمر للمجموعات فقط.")
        await event.edit("⏳ `جاري جلب الأعضاء...`")
        try:
            members = await get_group_members(client, event.chat_id)
            tags = ' '.join([f"@{m.username}" if m.username else f"[{m.first_name}](tg://user?id={m.id})" for m in members])
            await event.edit(f"📢 **تاك الكل:**\n{tags}")
        except Exception as e:
            await event.edit(f"❌ خطأ: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.تاك_عشوائي'))
    async def tag_random(event):
        if event.is_private:
            return await event.edit("⚠️ هذا الأمر للمجموعات فقط.")
        try:
            import random
            members = await get_group_members(client, event.chat_id)
            member = random.choice(members)
            mention = f"@{member.username}" if member.username else f"[{member.first_name}](tg://user?id={member.id})"
            await event.edit(f"🎲 العضو العشوائي: {mention}")
        except Exception as e:
            await event.edit(f"❌ خطأ: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.تثبيت'))
    async def pin_message(event):
        if event.is_private:
            return await event.edit("⚠️ هذا الأمر للمجموعات فقط.")
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على الرسالة.")
        reply = await event.get_reply_message()
        try:
            await client.pin_message(event.chat_id, reply.id, notify=False)
            await event.edit("📌 **تم تثبيت الرسالة.**")
        except Exception as e:
            await event.edit(f"❌ فشل التثبيت: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.فك_تثبيت'))
    async def unpin_message(event):
        if event.is_private:
            return await event.edit("⚠️ هذا الأمر للمجموعات فقط.")
        try:
            await client.unpin_message(event.chat_id)
            await event.edit("📌 **تم فك تثبيت الرسالة.**")
        except Exception as e:
            await event.edit(f"❌ فشل فك التثبيت: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.عدد'))
    async def members_count(event):
        if event.is_private:
            return await event.edit("⚠️ هذا الأمر للمجموعات فقط.")
        try:
            members = await get_group_members(client, event.chat_id)
            chat = await event.get_chat()
            await event.edit(
                f"👥 **إحصاء المجموعة:**\n\n"
                f"📌 **الاسم:** {chat.title}\n"
                f"👤 **الأعضاء:** {len(members)}"
            )
        except Exception as e:
            await event.edit(f"❌ خطأ: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.ادمنية'))
    async def list_admins(event):
        if event.is_private:
            return await event.edit("⚠️ هذا الأمر للمجموعات فقط.")
        await event.edit("⏳ `جاري جلب الادمنز...`")
        try:
            from telethon.tl.types import ChannelParticipantsAdmins
            admins = []
            async for admin in client.iter_participants(event.chat_id, filter=ChannelParticipantsAdmins):
                name = admin.first_name or "بدون اسم"
                admins.append(f"👑 {name} (@{admin.username})" if admin.username else f"👑 {name}")
            text = "👑 **قائمة الادمنز:**\n\n" + "\n".join(admins)
            await event.edit(text)
        except Exception as e:
            await event.edit(f"❌ خطأ: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.دوري\s+(\d+)(ث|ثانية|د|دقيقة)?\s+(.+)'))
    async def start_periodic(event):
        if event.is_private:
            return await event.edit("⚠️ هذا الأمر للمجموعات فقط.")
        amount = int(event.pattern_match.group(1))
        unit = event.pattern_match.group(2) or 'د'
        text = event.pattern_match.group(3).strip()
        chat_id = event.chat_id

        # تحويل للثواني
        if unit in ['ث', 'ثانية']:
            seconds = amount
            unit_text = f"{amount} ثانية"
        else:
            seconds = amount * 60
            unit_text = f"{amount} دقيقة"

        # الحد الأدنى 1 ثانية
        if seconds < 1:
            return await event.edit("⚠️ الحد الأدنى ثانية وحدة.")

        if chat_id in periodic_tasks and not periodic_tasks[chat_id].done():
            periodic_tasks[chat_id].cancel()

        await event.edit(f"✅ **تم تفعيل الدوري كل {unit_text}.**")

        async def periodic_loop():
            members = await get_group_members(client, chat_id)
            index = 0
            while True:
                try:
                    if not members or index >= len(members):
                        members = await get_group_members(client, chat_id)
                        index = 0
                    member = members[index]
                    mention = f"@{member.username}" if member.username else f"[{member.first_name}](tg://user?id={member.id})"
                    await client.send_message(chat_id, f"{mention} {text}")
                    index += 1
                except Exception:
                    pass
                await asyncio.sleep(seconds)

        periodic_tasks[chat_id] = asyncio.create_task(periodic_loop())

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.وقف_دوري'))
    async def stop_periodic(event):
        chat_id = event.chat_id
        if chat_id in periodic_tasks and not periodic_tasks[chat_id].done():
            periodic_tasks[chat_id].cancel()
            await event.edit("⛔ **تم إيقاف الدوري.**")
        else:
            await event.edit("⚠️ لا يوجد دوري نشط.")

    # تخزين مهام الملصق الدوري
    sticker_tasks = {}

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.ملصق_دوري\s+(\d+)(ث|ثانية|د|دقيقة)?'))
    async def start_sticker_periodic(event):
        if not event.is_reply:
            return await event.edit("⚠️ يرجى الرد على الملصق.")
        reply = await event.get_reply_message()
        if not reply.sticker:
            return await event.edit("⚠️ الرسالة لا تحتوي على ملصق.")

        amount = int(event.pattern_match.group(1))
        unit = event.pattern_match.group(2) or 'ث'
        chat_id = event.chat_id

        if unit in ['ث', 'ثانية']:
            seconds = amount
            unit_text = f"{amount} ثانية"
        else:
            seconds = amount * 60
            unit_text = f"{amount} دقيقة"

        if seconds < 1:
            return await event.edit("⚠️ الحد الأدنى ثانية وحدة.")

        # إيقاف المهمة القديمة لو موجودة
        if chat_id in sticker_tasks and not sticker_tasks[chat_id].done():
            sticker_tasks[chat_id].cancel()

        sticker = reply.sticker
        await event.edit(f"✅ **تم تفعيل الملصق الدوري كل {unit_text}.**")

        async def sticker_loop():
            while True:
                try:
                    await client.send_file(chat_id, sticker)
                except Exception:
                    pass
                await asyncio.sleep(seconds)

        sticker_tasks[chat_id] = asyncio.create_task(sticker_loop())

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.وقف_ملصق'))
    async def stop_sticker_periodic(event):
        chat_id = event.chat_id
        if chat_id in sticker_tasks and not sticker_tasks[chat_id].done():
            sticker_tasks[chat_id].cancel()
            await event.edit("⛔ **تم إيقاف الملصق الدوري.**")
        else:
            await event.edit("⚠️ لا يوجد ملصق دوري نشط.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.ترحيب\s+(تفعيل|تعطيل)'))
    async def toggle_welcome(event):
        if event.is_private:
            return await event.edit("⚠️ هذا الأمر للمجموعات فقط.")
        chat_id = event.chat_id
        cmd = event.pattern_match.group(1)
        if chat_id not in group_settings:
            group_settings[chat_id] = {}
        group_settings[chat_id]['welcome'] = cmd == 'تفعيل'
        if 'welcome_text' not in group_settings[chat_id]:
            group_settings[chat_id]['welcome_text'] = "أهلاً وسهلاً {name} بيننا! 🎉"
        await event.edit(f"✅ **تم {cmd} رسالة الترحيب.**")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.ترحيب_نص\s+(.+)'))
    async def set_welcome_text(event):
        chat_id = event.chat_id
        text = event.pattern_match.group(1)
        if chat_id not in group_settings:
            group_settings[chat_id] = {}
        group_settings[chat_id]['welcome_text'] = text
        await event.edit(f"✅ **تم ضبط نص الترحيب:**\n{text}\n\n💡 استخدم `{{name}}` لاسم العضو.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.وداع\s+(تفعيل|تعطيل)'))
    async def toggle_goodbye(event):
        if event.is_private:
            return await event.edit("⚠️ هذا الأمر للمجموعات فقط.")
        chat_id = event.chat_id
        cmd = event.pattern_match.group(1)
        if chat_id not in group_settings:
            group_settings[chat_id] = {}
        group_settings[chat_id]['goodbye'] = cmd == 'تفعيل'
        if 'goodbye_text' not in group_settings[chat_id]:
            group_settings[chat_id]['goodbye_text'] = "وداعاً {name}، نتمنى أن تعود قريباً! 👋"
        await event.edit(f"✅ **تم {cmd} رسالة الوداع.**")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.وداع_نص\s+(.+)'))
    async def set_goodbye_text(event):
        chat_id = event.chat_id
        text = event.pattern_match.group(1)
        if chat_id not in group_settings:
            group_settings[chat_id] = {}
        group_settings[chat_id]['goodbye_text'] = text
        await event.edit(f"✅ **تم ضبط نص الوداع:**\n{text}\n\n💡 استخدم `{{name}}` لاسم العضو.")

    # مراقبة انضمام ومغادرة الأعضاء
    @client.on(events.ChatAction())
    async def chat_action_handler(event):
        chat_id = event.chat_id
        settings = group_settings.get(chat_id, {})
        try:
            if event.user_joined or event.user_added:
                if settings.get('welcome'):
                    user = await event.get_user()
                    name = user.first_name or "عضو جديد"
                    text = settings.get('welcome_text', "أهلاً {name}! 🎉").replace("{name}", name)
                    await client.send_message(chat_id, text)
            elif event.user_left or event.user_kicked:
                if settings.get('goodbye'):
                    user = await event.get_user()
                    name = user.first_name or "عضو"
                    text = settings.get('goodbye_text', "وداعاً {name}! 👋").replace("{name}", name)
                    await client.send_message(chat_id, text)
        except Exception:
            pass

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.تنظيف_مجموعة\s+(\d+)'))
    async def clean_group_messages(event):
        if event.is_private:
            return await event.edit("⚠️ هذا الأمر للمجموعات فقط.")
        num = int(event.pattern_match.group(1))
        await event.edit(f"🧹 `جاري مسح {num} رسالة...`")
        count = 0
        async for msg in client.iter_messages(event.chat_id):
            if msg.out:
                try:
                    await msg.delete()
                    count += 1
                    if count >= num:
                        break
                except Exception:
                    continue
        confirm = await client.send_message(event.chat_id, f"✅ تم مسح {count} رسالة.")
        await asyncio.sleep(2)
        await confirm.delete()

    # =========================================================
    # م5 - أوامر الخاص والردود
    # =========================================================

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.حالة\s+(.+)'))
    async def set_bio(event):
        bio = event.pattern_match.group(1).strip()
        try:
            await client(UpdateProfileRequest(about=bio))
            await event.edit(f"✅ **تم تغيير البايو إلى:**\n{bio}")
        except Exception as e:
            await event.edit(f"❌ فشل تغيير البايو: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.حالة_مسح'))
    async def clear_bio(event):
        try:
            await client(UpdateProfileRequest(about=""))
            await event.edit("✅ **تم مسح البايو بنجاح.**")
        except Exception as e:
            await event.edit(f"❌ فشل: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.قائمة_المكتومين'))
    async def list_muted(event):
        with get_db() as conn:
            rows = conn.execute('SELECT user_id FROM muted_users').fetchall()
        if not rows:
            return await event.edit("📋 لا يوجد أشخاص مكتومون حالياً.")
        text = "🔇 **قائمة المكتومين:**\n\n"
        for i, row in enumerate(rows, 1):
            try:
                user = await client.get_entity(row['user_id'])
                name = f"{user.first_name} (@{user.username})" if user.username else user.first_name
            except Exception:
                name = str(row['user_id'])
            text += f"{i}. {name}\n"
        await event.edit(text)

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.رسالة_مجدولة\s+(\d+)\s+(.+)'))
    async def scheduled_message(event):
        minutes = int(event.pattern_match.group(1))
        text = event.pattern_match.group(2).strip()
        chat_id = event.chat_id
        await event.edit(f"⏳ **سيتم إرسال الرسالة بعد {minutes} دقيقة.**")
        await asyncio.sleep(minutes * 60)
        try:
            await client.send_message(chat_id, text)
        except Exception as e:
            await client.send_message('me', f"❌ فشل إرسال الرسالة المجدولة: {e}")

    # =========================================================
    # م8 - أوامر الانتحال والإرسال
    # =========================================================

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.حفظ_بروفايل'))
    async def save_profile(event):
        await event.edit("💾 `جاري حفظ بروفايلك...`")
        try:
            me = await get_me_cached(client)
            full_me = await client(GetFullUserRequest('me'))

            # حذف باك أب قديم
            for f in glob.glob(f'{BACKUP_FOLDER}/*'):
                try:
                    os.remove(f)
                except Exception:
                    pass

            # حفظ الصور
            my_photos = await client.get_profile_photos('me')
            for i, photo in enumerate(my_photos):
                await client.download_media(photo, f'{BACKUP_FOLDER}/orig_{i}.jpg')

            # حفظ البيانات بقاعدة البيانات
            with get_db() as conn:
                conn.execute(
                    'INSERT OR REPLACE INTO profile_backup (id, first_name, last_name, bio) VALUES (?, ?, ?, ?)',
                    (1, me.first_name, me.last_name or "", full_me.full_user.about or "")
                )
                # حفظ تاريخ الحفظ
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('profile_saved_at', ?)",
                    (datetime.now().strftime('%Y-%m-%d %H:%M'),))
                conn.commit()

            await event.edit(
                f"✅ **تم حفظ بروفايلك بنجاح!**\n\n"
                f"👤 **الاسم:** {me.first_name} {me.last_name or ''}\n"
                f"📝 **البايو:** {full_me.full_user.about or 'فارغ'}\n"
                f"🖼 **الصور المحفوظة:** {len(my_photos)}\n\n"
                f"استخدم `.رجوع` للرجوع لهذا البروفايل بأي وقت."
            )
        except Exception as e:
            await event.edit(f"❌ فشل الحفظ: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.تاريخ_الانتحال'))
    async def clone_history(event):
        with get_db() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = 'last_cloned'").fetchone()
            row_time = conn.execute("SELECT value FROM settings WHERE key = 'last_cloned_at'").fetchone()
            saved_at = conn.execute("SELECT value FROM settings WHERE key = 'profile_saved_at'").fetchone()
            backup = conn.execute('SELECT first_name, last_name FROM profile_backup WHERE id = 1').fetchone()

        text = "🎭 **تاريخ الانتحال:**\n\n"

        if row and row['value']:
            text += f"👤 **آخر انتحال:** {row['value']}\n"
            text += f"🕐 **وقت الانتحال:** {row_time['value'] if row_time else 'غير معروف'}\n\n"
        else:
            text += "❌ لم تنتحل أي شخص بعد.\n\n"

        if backup:
            text += f"💾 **البروفايل المحفوظ:** {backup['first_name']} {backup['last_name'] or ''}\n"
            text += f"📅 **وقت الحفظ:** {saved_at['value'] if saved_at else 'غير معروف'}"
        else:
            text += "⚠️ لم تحفظ بروفايلك بعد. استخدم `.حفظ_بروفايل`"

        await event.edit(text)


# =====================================================================
# بدء تشغيل الحساب
# =====================================================================
async def main():
    global _me_cache
    init_db()
    from telethon.sessions import StringSession
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    print("🚀 جاري بدء تشغيل السورس على Railway...")
    await client.start()
    _me_cache = await client.get_me()
    print(f"✅ تم الاتصال! السورس يعمل على: {_me_cache.first_name} (ID: {_me_cache.id})")
    await register_features(client)
    asyncio.create_task(update_name_with_time(client))
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())