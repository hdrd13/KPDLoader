import os
import asyncio
import logging
import shutil
import html
import sys
import re
import aiosqlite
import time
import json
import traceback
import io
from pyrogram import Client, filters, idle, enums
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto, BotCommand, ReplyParameters
)

try:
    import config
except ImportError:
    print("❌ ERROR: config.py not found")
    print("💡 HINT: Rename config.py.sample to config.py and fill it with your data")
    sys.exit(1)

API_ID = config.API_ID
API_HASH = config.API_HASH
BOT_TOKEN = config.BOT_TOKEN
DB_NAME = "cache.db"
DOWNLOAD_PATH = "downloads"
SETTINGS_FILE = "user_settings.json"

DEFAULT_SETTINGS = {
    "audio": True,
    "desc": True,
    "sep_desc": False,
    "link_btn": True
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except Exception as e:
            logging.error(f"Error loading settings: {e}")
    return {}

def save_settings_to_file():
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(user_settings, f, indent=4)
    except Exception as e:
        logging.error(f"Error saving settings: {e}")

user_settings = load_settings()

def get_settings(user_id):
    if user_id not in user_settings:
        user_settings[user_id] = DEFAULT_SETTINGS.copy()
    return user_settings[user_id]

def get_settings_kb(user_id):
    s = get_settings(user_id)
    kb = [
        [InlineKeyboardButton(f"🎵 Add audio to photos: {'✅' if s['audio'] else '❌'}", callback_data="set_audio")],
        [InlineKeyboardButton(f"📝 Add description: {'✅' if s['desc'] else '❌'}", callback_data="set_desc")],
    ]
    if s['desc']:
        kb.append([InlineKeyboardButton(f"📄 Desc. separately: {'✅' if s['sep_desc'] else '❌'}", callback_data="set_sep")])
    kb.append([InlineKeyboardButton(f"🔗 Add OG link: {'✅' if s['link_btn'] else '❌'}", callback_data="set_link")])
    kb.append([InlineKeyboardButton("🗑️ Delete", callback_data="set_close")])
    return InlineKeyboardMarkup(kb)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s")
logger = logging.getLogger(__name__)

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

if not os.path.exists(DOWNLOAD_PATH):
    os.makedirs(DOWNLOAD_PATH)

async def init_db():
    async with aiosqlite.connect(DB_NAME) as con:
        await con.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                url TEXT PRIMARY KEY,
                video_id TEXT,
                audio_id TEXT,
                photos TEXT,
                caption TEXT,
                timestamp REAL
            )
        """)
        await con.commit()

async def get_cache(url):
    async with aiosqlite.connect(DB_NAME) as con:
        await con.execute("DELETE FROM cache WHERE timestamp < ?", (time.time() - 259200,))
        await con.commit()
        async with con.execute(
            "SELECT video_id, audio_id, caption, photos FROM cache WHERE url = ?", (url,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return {
                    'video': row[0],
                    'audio': row[1],
                    'caption': row[2],
                    'photos': json.loads(row[3]) if row[3] else None
                }
            return None

async def update_cache(url, video_id=None, audio_id=None, caption=None, photos=None):
    async with aiosqlite.connect(DB_NAME) as con:
        await con.execute(
            "INSERT OR IGNORE INTO cache (url, timestamp) VALUES (?, ?)", (url, time.time())
        )
        if video_id:
            await con.execute(
                "UPDATE cache SET video_id = ?, timestamp = ? WHERE url = ?", (video_id, time.time(), url)
            )
        if audio_id:
            await con.execute(
                "UPDATE cache SET audio_id = ?, timestamp = ? WHERE url = ?", (audio_id, time.time(), url)
            )
        if caption is not None:
            await con.execute(
                "UPDATE cache SET caption = ?, timestamp = ? WHERE url = ?", (caption, time.time(), url)
            )
        if photos:
            await con.execute(
                "UPDATE cache SET photos = ?, timestamp = ? WHERE url = ?",
                (json.dumps(photos), time.time(), url)
            )
        await con.commit()

async def download_gallery(url, save_dir):
    """Download via gallery-dl. Returns (success, caption, track_title, track_artist)."""
    abs_save_dir = os.path.abspath(save_dir)
    cmd = ["gallery-dl", "--directory", abs_save_dir, "--write-info-json", "--no-mtime", url]

    caption = ""
    track_title = "Original Audio"
    track_artist = "Bot"

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode('utf-8', errors='ignore') or stdout.decode('utf-8', errors='ignore')
            logger.error(f"gallery-dl failed: {err}")
            return False, "", track_title, track_artist

        json_file = next(
            (os.path.join(abs_save_dir, f) for f in os.listdir(abs_save_dir) if f.endswith('.json')),
            None
        )
        if json_file:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    data = data[0] if data else {}
                if isinstance(data, dict):
                    user_field = data.get('user')
                    if isinstance(user_field, dict):
                        author_raw = (user_field.get('nickname') or
                                      user_field.get('unique_id') or
                                      user_field.get('name') or "User")
                    elif isinstance(user_field, str):
                        author_raw = user_field
                    else:
                        author_raw = (data.get('username') or
                                      data.get('author', {}).get('name') or
                                      data.get('nick') or "User")

                    author = html.escape(str(author_raw))
                    desc_raw = (data.get('title') or data.get('desc') or
                                data.get('description') or data.get('caption') or
                                data.get('text') or "")
                    desc = html.escape(str(desc_raw).strip())
                    if len(desc) > 800:
                        desc = desc[:800] + "..."

                    caption = f"<blockquote expandable><b>{author}</b>\n\n{desc}</blockquote>" if desc else f"<b>{author}</b>"

                    music_obj = data.get('music') or {}
                    track_title = (music_obj.get('title') or
                                   data.get('track', {}).get('name') or "Original Audio")
                    track_artist = (music_obj.get('authorName') or music_obj.get('author') or
                                    music_obj.get('artist') or data.get('track', {}).get('artist') or author)
            except Exception as e:
                logger.error(f"JSON parse error: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"gallery-dl exec error: {e}")
        return False, "", track_title, track_artist

    media_files = [
        f for f in os.listdir(abs_save_dir)
        if f.lower().endswith(('.jpg', '.png', '.webp', '.mp4', '.mp3'))
    ]
    if media_files:
        return True, caption, track_title, track_artist

    return False, "", "Original Audio", "Bot"

@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply(
        "👋 <b>Hi! :3</b>\n\n"
        "I can download content from <b>TikTok</b>.\n\n"
        "Just send me a link!\n\n"
        "To change preferences: /settings"
    )

@app.on_message(filters.command("settings"))
async def settings_handler(client, message):
    await message.reply("⚙️ <b>Download settings:</b>", reply_markup=get_settings_kb(message.chat.id))

@app.on_callback_query(filters.regex("^set_"))
async def callback_handler(client, callback):
    chat_id = callback.message.chat.id
    action = callback.data.split("_")[1]
    s = get_settings(chat_id)

    if action == "close":
        try:
            await callback.message.delete()
        except Exception:
            pass
        return

    if action == "audio":
        s['audio'] = not s['audio']
    elif action == "desc":
        s['desc'] = not s['desc']
    elif action == "sep":
        s['sep_desc'] = not s['sep_desc']
    elif action == "link":
        s['link_btn'] = not s['link_btn']

    save_settings_to_file()
    await callback.message.edit_reply_markup(get_settings_kb(chat_id))

@app.on_message(filters.regex(r"tiktok\.com"))
async def link_handler(client, message: Message):
    chat_id = message.chat.id
    settings = get_settings(chat_id)

    match = re.search(r"(https?://(?:www\.)?[\w.-]*tiktok\.com[^\s]+)", message.text)
    if not match:
        return

    url = match.group(0)
    status = await message.reply("⏳ Downloading...")

    unique_id = str(message.id)
    save_dir = os.path.join(DOWNLOAD_PATH, unique_id)
    os.makedirs(save_dir, exist_ok=True)

    try:
        og_button = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 OG Link", url=url)]]) if settings['link_btn'] else None

        cached = await get_cache(url)
        if cached:
            if cached.get('photos'):
                file_ids = cached['photos']
                cap = cached['caption'] or "" if settings['desc'] else ""
                for i in range(0, len(file_ids), 10):
                    chunk = file_ids[i:i + 10]
                    media_group = [
                        InputMediaPhoto(
                            fid,
                            caption=cap if (i == 0 and idx == 0 and not settings['sep_desc']) else "",
                            parse_mode=enums.ParseMode.HTML
                        )
                        for idx, fid in enumerate(chunk)
                    ]
                    await client.send_media_group(chat_id, media=media_group, reply_parameters=ReplyParameters(message_id=message.id))
                if settings['desc'] and settings['sep_desc'] and cap:
                    await message.reply(cap, reply_markup=og_button, parse_mode=enums.ParseMode.HTML)
                await status.delete()
                return

            elif cached.get('video'):
                try:
                    vid_cap = cached['caption'] if (settings['desc'] and not settings['sep_desc'] and cached['caption']) else ""
                    vid_btn = og_button if not settings['sep_desc'] else None
                    await client.send_video(
                        chat_id, video=cached['video'], caption=vid_cap,
                        reply_markup=vid_btn, reply_parameters=ReplyParameters(message_id=message.id),
                        parse_mode=enums.ParseMode.HTML
                    )
                    if settings['desc'] and settings['sep_desc'] and cached['caption']:
                        await message.reply(cached['caption'], reply_markup=og_button, parse_mode=enums.ParseMode.HTML)
                    await status.delete()
                    return
                except Exception as e:
                    logger.warning(f"Cache send failed, re-downloading: {e}")

        success, caption, track_title, track_artist = await download_gallery(url, save_dir)

        if not success:
            await status.edit_text("❌ Download failed.")
            return

        if not settings['desc']:
            caption = ""

        await status.edit_text("🔄️ Uploading...")

        photos = sorted([
            os.path.join(r, f)
            for r, _, fs in os.walk(save_dir)
            for f in fs if f.lower().endswith(('.jpg', '.png', '.webp'))
        ])
        video_file = next(
            (os.path.join(r, f) for r, _, fs in os.walk(save_dir) for f in fs if f.lower().endswith('.mp4')),
            None
        )
        audio_file = next(
            (os.path.join(r, f) for r, _, fs in os.walk(save_dir) for f in fs if f.lower().endswith(('.mp3', '.m4a'))),
            None
        )

        if photos:
            uploaded_ids = []
            for i in range(0, len(photos), 10):
                chunk = photos[i:i + 10]
                media_group = [
                    InputMediaPhoto(
                        p,
                        caption=caption if (i == 0 and idx == 0 and not settings['sep_desc']) else "",
                        parse_mode=enums.ParseMode.HTML
                    )
                    for idx, p in enumerate(chunk)
                ]
                msgs = await client.send_media_group(
                    chat_id, media=media_group, reply_parameters=ReplyParameters(message_id=message.id)
                )
                uploaded_ids.extend([m.photo.file_id for m in msgs if m.photo])

            if uploaded_ids:
                await update_cache(url, photos=uploaded_ids, caption=caption)

            if audio_file and settings['audio']:
                sent_audio = await client.send_audio(
                    chat_id, audio_file,
                    title=track_title, performer=track_artist,
                    reply_parameters=ReplyParameters(message_id=message.id)
                )
                if sent_audio.audio:
                    await update_cache(url, audio_id=sent_audio.audio.file_id)

            if settings['desc'] and settings['sep_desc'] and caption:
                await message.reply(caption, reply_markup=og_button, parse_mode=enums.ParseMode.HTML)

        elif video_file:
            vid_cap = caption if not settings['sep_desc'] else ""
            vid_btn = og_button if not settings['sep_desc'] else None
            sent_msg = await client.send_video(
                chat_id, video=video_file, caption=vid_cap,
                reply_markup=vid_btn, reply_parameters=ReplyParameters(message_id=message.id),
                parse_mode=enums.ParseMode.HTML
            )
            if sent_msg.video:
                await update_cache(url, video_id=sent_msg.video.file_id, caption=caption)

            if settings['desc'] and settings['sep_desc'] and caption:
                await message.reply(caption, reply_markup=og_button, parse_mode=enums.ParseMode.HTML)

        else:
            await status.edit_text("❌ No media found after download.")
            return

        await status.delete()

    except Exception as e:
        logger.error(f"Error processing {url}: {e}")
        user_msg = (
            "Uh-oh. Houston, we have a problem:\n"
            f"<blockquote expandable>{html.escape(str(e))}</blockquote>"
        )
        try:
            await status.edit_text(user_msg, parse_mode=enums.ParseMode.HTML)
        except Exception:
            pass

        if hasattr(config, 'OWNER_ID'):
            tb_text = traceback.format_exc()
            doc = io.BytesIO(tb_text.encode('utf-8'))
            doc.name = "error_log.txt"
            try:
                await client.send_document(
                    config.OWNER_ID, document=doc,
                    caption=f"🚨 <b>Error</b>\n<blockquote expandable>{html.escape(str(e))}</blockquote>",
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception as err:
                logger.error(f"Failed to send error log: {err}")

    finally:
        await asyncio.sleep(2)
        if os.path.exists(save_dir):
            shutil.rmtree(save_dir, ignore_errors=True)

async def start_bot():
    await init_db()
    print("🚀 Starting bot...")
    await app.start()
    await app.set_bot_commands([
        BotCommand("start", "Start/restart bot"),
        BotCommand("settings", "Download preferences")
    ])
    print("✅ Bot started!")
    await idle()
    await app.stop()

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(start_bot())
    except KeyboardInterrupt:
        print("🛑 Bot stopped.")