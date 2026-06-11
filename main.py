# -*- coding: utf-8 -*-
import asyncio
import sqlite3
import os
import glob
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.functions.contacts import BlockRequest, UnblockRequest
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.types import InputPhoto
from telethon.errors import FloodWaitError

# --- إعدادات Railway الآمنة (يتم ضبطها في Variables في لوحة التحكم) ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING")

DB_NAME = 'userbot_master.db'
BACKUP_FOLDER = 'backup_photos_acc'

if not os.path.exists(BACKUP_FOLDER): 
    os.makedirs(BACKUP_FOLDER)

def get_reply_media():
    supported_extensions = ['*.jpg', '*.jpeg', '*.png', '*.mp4', '*.gif']
    for ext in supported_extensions:
        files = glob.glob(f'reply_media{ext}')
        if files:
            return files[0]
    return None

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS profile_backup 
                          (id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, bio TEXT)''')
        cursor.execute('CREATE TABLE IF NOT EXISTS auto_reply (id INTEGER PRIMARY KEY, enabled INTEGER, message TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS smart_replies (id INTEGER PRIMARY KEY AUTOINCREMENT, trigger TEXT UNIQUE, response TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS muted_users (user_id INTEGER PRIMARY KEY)')
        
        default_caption = (
            "╭━━━▬▭▬  ⚡️  ▬▭▬━━━╮\n"
            "    مـرحـبـاً بـك عـزيـزي 🧑‍💻\n"
            "╰━━━▬▭▬  ⚜️  ▬▭▬━━━╯\n\n"
            "⚠️ **الـرد الـتـلـقـائـي للـحـسـاب الـمـطـوّر**\n"
            "« صـاحـب الـحـسـاب غـيـر مـتـواجـد حـالـيـاً »\n\n"
            "💬 أترك رسالتك بوضوح ولُطف، وسأقوم بالرد عليك فور تواجدي وتفرغي كالألفا. 🖤\n\n"
            "⏳ __يُرجى عدم تكرار الاتصال أو السبام المزعج.__"
        )
        cursor.execute('INSERT OR IGNORE INTO auto_reply (id, enabled, message) VALUES (1, 1, ?)', (default_caption,))
        conn.commit()

def estimate_creation_date(telegram_id):
    id_milestones = [
        (0, datetime(2013, 8, 1).timestamp()), (50000000, datetime(2014, 8, 1).timestamp()),
        (120000000, datetime(2015, 8, 1).timestamp()), (230000000, datetime(2016, 8, 1).timestamp()),
        (400000000, datetime(2017, 8, 1).timestamp()), (650000000, datetime(2018, 8, 1).timestamp()),
        (950000000, datetime(2019, 8, 1).timestamp()), (1250000000, datetime(2020, 8, 1).timestamp()),
        (1850000000, datetime(2021, 8, 1).timestamp()), (5000000000, datetime(2022, 8, 1).timestamp()),
        (6200000000, datetime(2023, 8, 1).timestamp()), (7000000000, datetime(2024, 8, 1).timestamp()),
        (7800000000, datetime(2025, 1, 1).timestamp()), (8500000000, datetime(2026, 1, 1).timestamp())
    ]
    if telegram_id < 0: return "غير معروف"
    closest_milestone = id_milestones[0]; next_milestone = id_milestones[-1]
    for i in range(len(id_milestones) - 1):
        if id_milestones[i][0] <= telegram_id <= id_milestones[i+1][0]:
            closest_milestone = id_milestones[i]; next_milestone = id_milestones[i+1]; break
    id_diff = next_milestone[0] - closest_milestone[0]
    time_diff = next_milestone[1] - closest_milestone[1]
    estimated_timestamp = closest_milestone[1] + (((telegram_id - closest_milestone[0]) / id_diff) * time_diff) if id_diff != 0 else closest_milestone[1]
    return datetime.fromtimestamp(estimated_timestamp).strftime('%Y / %m (%B)')

async def register_features(client):
    db_id = 1  
    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.(الاوامر|أوامر|اوامر)'))
    async def show_commands(event):
        await event.edit("📌 **قائمة أوامر السورس المطور V3:**\n\n🎭 **الهوية:** `.انتحال`, `.رجوع`\n🛡️ **الكتم:** `.كتم`, `.الغاء_كتم`, `.بلوك`, `.غادر`\n🤖 **الرد:** `.تفعيل`, `.ضبط_الرد`, `.إضافة_رد`\n⚙️ **أدوات:** `.تاريخ`, `.فحص`, `.حفظ`, `.تنظيف`")

    @client.on(events.NewMessage(incoming=True))
    async def mute_enforcer(event):
        if not event.is_private: return
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM muted_users WHERE user_id = ?', (event.sender_id,))
            if cursor.fetchone():
                try: await event.delete()
                except: pass

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.كتم'))
    async def mute_user(event):
        if not event.is_reply: return await event.edit("⚠️ يرجى الرد على الشخص.")
        reply_msg = await event.get_reply_message()
        target_id = reply_msg.sender_id
        if target_id == (await client.get_me()).id: return await event.edit("❌ لا يمكنك كتم نفسك!")
        with sqlite3.connect(DB_NAME) as conn:
            try: conn.cursor().execute('INSERT INTO muted_users (user_id) VALUES (?)', (target_id,)); conn.commit(); await event.edit("🔇 تم الكتم.")
            except sqlite3.IntegrityError: await event.edit("⚠️ مكتوم بالفعل.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.الغاء_كتم'))
    async def unmute_user(event):
        if not event.is_reply: return await event.edit("⚠️ يرجى الرد على الشخص.")
        with sqlite3.connect(DB_NAME) as conn: conn.cursor().execute('DELETE FROM muted_users WHERE user_id = ?', ((await event.get_reply_message()).sender_id,)); conn.commit(); await event.edit("🔊 تم الإلغاء.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.(بلوك|حظر)'))
    async def block_user(event):
        if not event.is_reply: return await event.edit("⚠️ يرجى الرد.")
        try: await client(BlockRequest(id=(await event.get_reply_message()).sender_id)); await event.edit("🚫 تم الحظر.")
        except Exception as e: await event.edit(f"❌ {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.الغاء_بلوك'))
    async def unmute_block(event):
        if not event.is_reply: return await event.edit("⚠️ يرجى الرد.")
        try: await client(UnblockRequest(id=(await event.get_reply_message()).sender_id)); await event.edit("✅ تم فك الحظر.")
        except Exception as e: await event.edit(f"❌ {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.تاريخ'))
    async def get_creation_time(event):
        target_id = event.chat_id
        if event.is_reply: target_id = (await event.get_reply_message()).sender_id
        await event.edit(f"📅 تاريخ التأسيس: {estimate_creation_date(target_id)}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.غادر'))
    async def leave_group(event):
        if not event.is_private: await client(LeaveChannelRequest(event.chat_id))

    @client.on(events.NewMessage(incoming=True))
    async def responder_handler(event):
        if not event.is_private: return
        try:
            me = await client.get_me()
            if event.sender_id == me.id: return
        except: return
        msg_text = event.raw_text.lower() if event.raw_text else ""
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            if msg_text:
                cursor.execute('SELECT response FROM smart_replies WHERE ? LIKE "%" || trigger || "%"', (msg_text,))
                smart = cursor.fetchone()
                if smart: await asyncio.sleep(0.5); await event.reply(smart[0]); return
            cursor.execute('SELECT enabled, message FROM auto_reply WHERE id = 1')
            row = cursor.fetchone()
            if row and row[0] == 1:
                cursor.execute('SELECT user_id FROM muted_users WHERE user_id = ?', (event.sender_id,))
                if not cursor.fetchone():
                    media = get_reply_media()
                    if media: await client.send_file(event.chat_id, media, caption=row[1], reply_to=event.id)
                    else: await event.reply(row[1])

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.ضبط_صورة'))
    async def set_reply_image(event):
        if not event.is_reply: return
        for f in glob.glob('reply_media*'): os.remove(f)
        await (await event.get_reply_message()).download_media(file='reply_media')
        await event.edit("✅ تم الحفظ.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.انتحال(?:\s+@?([\w_]+))?'))
    async def clone_profile(event):
        target = None
        if event.is_reply: target = await client.get_entity((await event.get_reply_message()).sender_id)
        elif event.pattern_match.group(1): target = await client.get_entity(event.pattern_match.group(1))
        else: return await event.edit("⚠️ حدد الشخص.")
        await event.edit("🔄 جاري الانتحال...")
        try:
            full_target = await client(GetFullUserRequest(target))
            my_user = await client.get_me()
            with sqlite3.connect(DB_NAME) as conn: conn.cursor().execute('INSERT OR REPLACE INTO profile_backup (id, first_name, last_name, bio) VALUES (?, ?, ?, ?)', (db_id, my_user.first_name, my_user.last_name or "", (await client(GetFullUserRequest('me'))).full_user.about or ""))
            await client(UpdateProfileRequest(first_name=target.first_name, last_name=target.last_name or "", about=full_target.full_user.about or ""))
            photo = await client.download_profile_photo(target, file="target_photo")
            if photo: await client(UploadProfilePhotoRequest(file=await client.upload_file(photo))); os.remove(photo)
            await event.edit("✅ تم الانتحال.")
        except Exception as e: await event.edit(f"❌ {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.رجوع'))
    async def restore_profile(event):
        with sqlite3.connect(DB_NAME) as conn: row = conn.cursor().execute('SELECT first_name, last_name, bio FROM profile_backup WHERE id = ?', (db_id,)).fetchone()
        if row: await client(UpdateProfileRequest(first_name=row[0], last_name=row[1], about=row[2])); await event.edit("✅ تمت الاستعادة.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.حفظ'))
    async def save_media(event):
        if event.is_reply:
            f = await (await event.get_reply_message()).download_media()
            await client.send_file('me', f); os.remove(f); await event.delete()

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.تنظيف\s+(\d+)'))
    async def clean_my_messages(event):
        num = int(event.pattern_match.group(1))
        count = 0
        async for msg in client.iter_messages(event.chat_id):
            if msg.out: await msg.delete(); count += 1
            if count >= num: break
        await event.respond(f"✅ تم مسح {count} رسالة."); await asyncio.sleep(2); await event.delete()

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.فحص'))
    async def inspect_user(event):
        if not event.is_reply: return
        t = await client.get_entity((await event.get_reply_message()).sender_id)
        await event.edit(f"👤 الاسم: {t.first_name}\n🆔 ID: `{t.id}`\n👑 بريميوم: {'نعم' if t.premium else 'لا'}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.(تفعيل|تعطيل|إضافة_رد|ضبط_الرد)'))
    async def admin_handler(event):
        cmd = event.pattern_match.group(1)
        if cmd in ['تفعيل', 'تعطيل']:
            with sqlite3.connect(DB_NAME) as conn: conn.cursor().execute('UPDATE auto_reply SET enabled = ? WHERE id = 1', (1 if cmd == 'تفعيل' else 0,))
            await event.edit(f"✅ تم {cmd}.")
        elif cmd == 'ضبط_الرد':
            with sqlite3.connect(DB_NAME) as conn: conn.cursor().execute('UPDATE auto_reply SET message = ? WHERE id = 1', (event.text.split(' ', 1)[1],))
            await event.edit("✅ تم ضبط الرد.")
        elif cmd == 'إضافة_رد':
            args = event.text.split(' ', 2)
            with sqlite3.connect(DB_NAME) as conn: conn.cursor().execute('INSERT OR REPLACE INTO smart_replies (trigger, response) VALUES (?, ?)', (args[1], args[2]))
            await event.edit("✅ تم حفظ الرد.")

async def main():
    init_db()
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    print("🚀 جاري بدء تشغيل السورس على Railway...")
    await client.start()
    await register_features(client)
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
      
