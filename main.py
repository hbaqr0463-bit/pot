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
import requests

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
async def update_name_with_time(client):
    while True:
        try:
            now = datetime.now()
            time_str = f"{now.hour}.{now.minute:02d}"
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
            "📌 **قائمة أوامر السورس المطور V4:**\n\n"
            "🎭 **الهوية والانتحال:**\n"
            "▫️ `.انتحال` 👈 بالرد أو باليوزر لنسخ الهوية والميديا النشطة.\n"
            "▫️ `.رجوع` 👈 لاستعادة حسابك وصورك الأصلية بشكل مضمون.\n\n"
            "🛡️ **أنظمة الكتم والحظر:**\n"
            "▫️ `.كتم` 👈 بالرد لمنع الشخص من التحدث معك بالخاص.\n"
            "▫️ `.الغاء_كتم` / `.إلغاء_كتم` 👈 بالرد لفك الكتم.\n"
            "▫️ `.بلوك` / `.حظر` 👈 لحظر الشخص نهائياً.\n"
            "▫️ `.الغاء_بلوك` / `.إلغاء_بلوك` 👈 لفك الحظر.\n"
            "▫️ `.تاريخ` 👈 جلب تاريخ إنشاء الحساب.\n"
            "▫️ `.غادر` 👈 للخروج من المجموعة أو القناة.\n\n"
            "🤖 **الرد التلقائي والذكاء الاصطناعي:**\n"
            "▫️ `.تفعيل` / `.تعطيل` 👈 تشغيل/إيقاف الرد التلقائي.\n"
            "▫️ `.ضبط_الرد [النص]` 👈 تعديل نص الرد العام.\n"
            "▫️ `.إضافة_رد [كلمة] [رد]` 👈 رد ذكي مخصص.\n"
            "▫️ `.حذف_رد [كلمة]` 👈 حذف رد ذكي.\n"
            "▫️ `.استثناء` 👈 بالرد لاستثناء شخص من الرد التلقائي.\n"
            "▫️ `.حذف_استثناء` 👈 بالرد لحذف الاستثناء.\n"
            "▫️ `.قائمة_الاستثناءات` 👈 عرض المستثنين.\n"
            "▫️ `.ذكاء تفعيل` / `.ذكاء تعطيل` 👈 تفعيل الرد بالذكاء الاصطناعي.\n\n"
            "👻 **وضع الشبح:**\n"
            "▫️ `.شبح تفعيل` / `.شبح تعطيل` 👈 القراءة بدون علامة قراءة.\n\n"
            "📝 **الملاحظات:**\n"
            "▫️ `.ملاحظة [نص]` 👈 حفظ ملاحظة.\n"
            "▫️ `.ملاحظاتي` 👈 عرض كل الملاحظات.\n"
            "▫️ `.حذف_ملاحظة [رقم]` 👈 حذف ملاحظة محددة.\n\n"
            "⚡ **أوامر سريعة:**\n"
            "▫️ `.نسخ_رد` 👈 نسخ نص الرسالة للمحفوظات.\n"
            "▫️ `.تحويل [يوزر]` 👈 تحويل الرسالة لشخص آخر.\n"
            "▫️ `.فحص` 👈 جلب بيانات عميقة للحساب.\n"
            "▫️ `.حفظ` 👈 حفظ الوسائط المختفية صامتاً.\n"
            "▫️ `.تنظيف [العدد]` 👈 مسح رسائلك.\n"
            "▫️ `.ضبط_صورة` 👈 تعيين صورة للرد التلقائي.\n"
            "▫️ `.حذف_صورة` 👈 حذف صورة الرد."
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

            # إرسال الرد وتسجيل الشخص
            await asyncio.sleep(0.8)
            media_file = get_reply_media()
            try:
                if media_file:
                    await client.send_file(event.chat_id, media_file, caption=row['message'], reply_to=event.id)
                else:
                    await event.reply(row['message'])
                # تسجيل أن هذا الشخص وصله الرد
                conn.execute(
                    'INSERT OR REPLACE INTO replied_users (user_id, last_reply) VALUES (?, ?)',
                    (event.sender_id, datetime.now().timestamp())
                )
                conn.commit()
            except Exception:
                pass

            # الرد بالذكاء الاصطناعي (OpenRouter مجاني)
            if get_setting('ai_reply') == '1' and msg_text:
                try:
                    response = requests.p      try:
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