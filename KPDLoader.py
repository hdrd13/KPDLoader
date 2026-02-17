import os
import asyncio
import logging
import shutil
import html
import sys
import re
import aiosqlite
import aiohttp
import time
import json
import traceback
import io
from pyrogram import Client, filters, idle, enums
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    InputMediaPhoto, BotCommand, ReplyParameters
)
import yt_dlp

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
        try:
            await con.execute("ALTER TABLE cache ADD COLUMN photos TEXT")
        except Exception:
            pass
            
        await con.commit()

async def get_cache(url):
    async with aiosqlite.connect(DB_NAME) as con:
        await con.execute("DELETE FROM cache WHERE timestamp < ?", (time.time() - 259200,))
        await con.commit()
        
        async with con.execute("SELECT video_id, audio_id, caption, photos FROM cache WHERE url = ?", (url,)) as cur:
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
        await con.execute("INSERT OR IGNORE INTO cache (url, timestamp) VALUES (?, ?)", (url, time.time()))
        if video_id:
            await con.execute("UPDATE cache SET video_id = ?, timestamp = ? WHERE url = ?", (video_id, time.time(), url))
        if audio_id:
            await con.execute("UPDATE cache SET audio_id = ?, timestamp = ? WHERE url = ?", (audio_id, time.time(), url))
        if caption:
            await con.execute("UPDATE cache SET caption = ?, timestamp = ? WHERE url = ?", (caption, time.time(), url))
        if photos:
            await con.execute("UPDATE cache SET photos = ?, timestamp = ? WHERE url = ?", (json.dumps(photos), time.time(), url))
            
        await con.commit()

def get_settings(user_id):
    if user_id not in user_settings:
        user_settings[user_id] = DEFAULT_SETTINGS.copy()
    return user_settings[user_id]

async def get_real_url(short_url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        async with aiohttp.ClientSession() as session:
            async with session.head(short_url, headers=headers, allow_redirects=True, timeout=5) as response:
                return str(response.url)
    except Exception:
        return short_url

async def download_gallery(url, save_dir):
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
            logging.error(f"❌ Gallery-dl failed: {err}")
            return False, "", "", ""

        if os.path.exists(abs_save_dir):
            json_file = next((os.path.join(abs_save_dir, f) for f in os.listdir(abs_save_dir) if f.endswith('.json')), None)
            
            if json_file:
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    if isinstance(data, list):
                        data = data[0] if data else {}

                    if isinstance(data, dict):
                        user_field = data.get('user')
                        author_raw = "User"

                        if isinstance(user_field, dict):
                            author_raw = (user_field.get('nickname') or 
                                          user_field.get('unique_id') or 
                                          user_field.get('name') or 
                                          "User")
                        elif isinstance(user_field, str):
                            author_raw = user_field
                        else:
                            author_raw = (data.get('username') or 
                                          data.get('author', {}).get('name') or 
                                          data.get('nick') or 
                                          "User")
                        
                        author = html.escape(str(author_raw))

                        desc_raw = (data.get('title') or 
                                    data.get('desc') or 
                                    data.get('description') or 
                                    data.get('caption') or 
                                    data.get('text') or 
                                    "")
                        
                        desc = html.escape(str(desc_raw).strip())
                        if len(desc) > 800: desc = desc[:800] + "..."
                        
                        if desc:
                            caption = f"<blockquote expandable><b>{author}</b>\n\n{desc}</blockquote>"
                        else:
                            caption = f"<b>{author}</b>"

                        music_obj = data.get('music') or {}
                        
                        track_title = (music_obj.get('title') or 
                                       data.get('track', {}).get('name') or 
                                       "Original Audio")
                        
                        track_artist = (music_obj.get('authorName') or
                                        music_obj.get('author') or 
                                        music_obj.get('artist') or 
                                        data.get('track', {}).get('artist') or 
                                        author)

                except Exception as e:
                    logging.error(f"JSON structure error: {e}", exc_info=True)

    except Exception as e:
        logging.error(f"Exec error: {e}")

    if os.path.exists(abs_save_dir):
        media_files = [f for f in os.listdir(abs_save_dir) if f.lower().endswith(('.jpg', '.png', '.webp', '.mp4', '.mp3'))]
        if len(media_files) > 0:
            return True, caption, track_title, track_artist
            
    return False, "", "Original Audio", "Bot"

def download_audio_force(url, save_dir):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{save_dir}/audio.%(ext)s',
        'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}],
        'noplaylist': True, 'quiet': True,
        'concurrent_fragment_downloads': 5,
        'extractor_args': {
            'youtube': {
                'player_client': ['android_vr']
            }
        }    
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([url])
            return True
        except Exception as e:
            logging.error(f"Audio DL error: {e}")
            return False

def download_video(url, save_dir):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{save_dir}/video.%(ext)s',
        'noplaylist': True, 'quiet': True,
        'concurrent_fragment_downloads': 5,
        'extractor_args': {
            'youtube': {
                'player_client': ['android_vr']
            }
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info), info

def get_meta_info(url):
    ydl_opts = {'quiet': True, 'noplaylist': True, 'extractor_args': {'youtube': {'player_client': ['android_vr']}}}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            return ydl.extract_info(url, download=False)
        except:
            return None

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

@app.on_message(filters.command("settings"))
async def settings_handler(client, message):
    await message.reply("⚙️ <b>Download settings:</b>", reply_markup=get_settings_kb(message.from_user.id))

@app.on_callback_query(filters.regex("^set_"))
async def callback_handler(client, callback):
    uid = callback.from_user.id
    action = callback.data.split("_")[1]
    s = get_settings(uid)
    
    if action == "close":
        try:
            await callback.message.delete()
        except:
            pass
        return
    if action == "audio": s['audio'] = not s['audio']
    elif action == "desc": s['desc'] = not s['desc']
    elif action == "sep": s['sep_desc'] = not s['sep_desc']
    elif action == "link": s['link_btn'] = not s['link_btn']

    save_settings_to_file()
    
    await callback.message.edit_reply_markup(get_settings_kb(uid))

@app.on_message(filters.command("start"))
async def start_handler(client, message):
    text = (
        "👋 <b>Hi! :3</b>\n\n"
        "I can download (almost) anything from:\n"
        "<b>TikTok</b>\n"
        "<b>YouTube Shorts</b>\n"
        "<b>Instagram</b> (Reels & Photos)\n\n"
        "Just send me a link!\n\n"
        "To change preferences just type /settings"
    )
    await message.reply(text)

@app.on_message(filters.regex(r"(tiktok\.com|instagram\.com|youtube\.com/shorts/|music\.youtube\.com)"))
async def link_handler(client, message: Message):
    uid = message.from_user.id
    settings = get_settings(uid)
    
    match = re.search(r"(https?://(?:www\.)?[\w.-]*(?:tiktok\.com|instagram\.com|youtube\.com/shorts/|music\.youtube\.com).*[/\?][^\s]+)", message.text)
    if not match: return
    raw_url = match.group(0)
    
    status = await message.reply("⏳ Downloading...")
    unique_id = str(message.id)
    save_dir = os.path.join(DOWNLOAD_PATH, unique_id)
    if not os.path.exists(save_dir): os.makedirs(save_dir)

    try:
        real_url = await get_real_url(raw_url)
        is_photo = "/photo/" in real_url or "instagram.com/p/" in real_url
        is_yt_music = "music.youtube.com" in real_url
        is_simple_video = not (is_photo or is_yt_music)
        default_buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 OG Link", url=real_url)]]) if settings['link_btn'] else None

        if is_photo:
            cached_data = await get_cache(real_url)
            
            if cached_data and cached_data['photos']:
                file_ids = cached_data['photos']
                cap = cached_data['caption'] if cached_data['caption'] else ""
                
                for i in range(0, len(file_ids), 10):
                    chunk = file_ids[i:i + 10]
                    media_group = []
                    for idx, fid in enumerate(chunk):
                        c = cap if (i == 0 and idx == 0 and not settings['sep_desc']) else ""
                        media_group.append(InputMediaPhoto(fid, caption=c, parse_mode=enums.ParseMode.HTML))
                    
                    await client.send_media_group(message.chat.id, media=media_group, reply_parameters=ReplyParameters(message_id=message.id))
                
                if settings['desc'] and settings['sep_desc'] and cap:
                    await message.reply(cap, reply_markup=default_buttons, parse_mode=enums.ParseMode.HTML)
                
                await status.delete()
                return

            success, caption, meta_title, meta_artist = await download_gallery(real_url, save_dir)
            
            if not success:
                await status.edit_text("❌ Gallery download failed.")
                return

            await status.edit_text("🔄️ Uploading...")

            photos = sorted([os.path.join(r, f) for r, _, fs in os.walk(save_dir) for f in fs if f.lower().endswith(('.jpg', '.png', '.webp'))])
            audio_file = next((os.path.join(r, f) for r, _, fs in os.walk(save_dir) for f in fs if f.lower().endswith(('.mp3', '.m4a'))), None)
            
            uploaded_file_ids = []

            if photos:
                for i in range(0, len(photos), 10):
                    chunk = photos[i:i + 10]
                    media_group = []
                    for idx, p in enumerate(chunk):
                        cap = caption if (i==0 and idx==0 and not settings['sep_desc']) else ""
                        media_group.append(InputMediaPhoto(p, caption=cap, parse_mode=enums.ParseMode.HTML))
                    
                    msgs = await client.send_media_group(message.chat.id, media=media_group, reply_parameters=ReplyParameters(message_id=message.id))
                    
                    for m in msgs:
                        if m.photo: uploaded_file_ids.append(m.photo.file_id)

                if uploaded_file_ids:
                    await update_cache(real_url, photos=uploaded_file_ids, caption=caption)

                if settings['desc'] and settings['sep_desc'] and caption:
                    await message.reply(caption, reply_markup=default_buttons, parse_mode=enums.ParseMode.HTML)

                if audio_file and settings['audio']:
                    sent_audio = await client.send_audio(message.chat.id, audio_file, title=meta_title, performer=meta_artist, reply_parameters=ReplyParameters(message_id=message.id))
                    if sent_audio.audio: await update_cache(real_url, audio_id=sent_audio.audio.file_id)
            
            await status.delete()
            return

        if is_simple_video:
            cached_data = await get_cache(real_url)
            if cached_data and cached_data['video']:
                try:
                    vid_cap = cached_data['caption'] if (cached_data['caption'] and not settings['sep_desc']) else ""
                    vid_btn = default_buttons if not settings['sep_desc'] else None

                    await client.send_video(message.chat.id, video=cached_data['video'], caption=vid_cap, reply_markup=vid_btn, reply_parameters=ReplyParameters(message_id=message.id), parse_mode=enums.ParseMode.HTML)
                    
                    if settings['desc'] and settings['sep_desc'] and cached_data['caption']:
                        await message.reply(cached_data['caption'], reply_markup=default_buttons)

                    await status.delete()
                    if os.path.exists(save_dir): shutil.rmtree(save_dir)
                    return
                except Exception as e:
                    logging.warning(f"Cache expired: {e}")

        info = await asyncio.to_thread(get_meta_info, real_url)
        caption = ""

        if info:
            author = html.escape(info.get('uploader', 'User'))
            desc = html.escape(info.get('description', '') or info.get('title', ''))
            if len(desc) > 800: desc = desc[:800] + "..."
            if settings['desc']: caption = f"<blockquote expandable><b>{author}</b>\n\n{desc}</blockquote>"

        if is_yt_music:
            meta_title = info.get('track') or info.get('title') or "Audio"
            meta_artist = info.get('artist') or info.get('uploader') or "Bot"
            if await asyncio.to_thread(download_audio_force, real_url, save_dir):
                await status.edit_text("🔄️ Uploading...")
                audio_file = next((os.path.join(r, f) for r, _, fs in os.walk(save_dir) for f in fs if f.endswith(('.mp3', '.m4a'))), None)
                if audio_file:
                    sent_audio = await client.send_audio(message.chat.id, audio_file, title=meta_title, performer=meta_artist, reply_markup=default_buttons, reply_parameters=ReplyParameters(message_id=message.id))
                await status.delete()
            else:
                await status.edit_text("❌ Audio download error.")

        else:
            tasks = [asyncio.to_thread(download_video, real_url, save_dir)]
            if settings['audio']: tasks.append(asyncio.to_thread(download_audio_force, real_url, save_dir))
            
            results = await asyncio.gather(*tasks)
            vid_path = results[0][0]
            
            if vid_path and os.path.exists(vid_path):
                await status.edit_text("🔄️ Uploading...")
                vid_cap = caption if not settings['sep_desc'] else ""
                vid_btn = default_buttons if not settings['sep_desc'] else None
                
                sent_msg = await client.send_video(
                    message.chat.id, 
                    video=vid_path, 
                    caption=vid_cap, 
                    reply_markup=vid_btn, 
                    reply_parameters=ReplyParameters(message_id=message.id), 
                    parse_mode=enums.ParseMode.HTML
                )
                
                if sent_msg.video: 
                    await update_cache(real_url, video_id=sent_msg.video.file_id, caption=caption)

                if settings['desc'] and settings['sep_desc'] and caption:
                    await message.reply(caption, reply_markup=default_buttons, parse_mode=enums.ParseMode.HTML)

                await status.delete()
            else:
                await status.edit_text("❌ Video download error.")

    except Exception as e:
        logger.error(f"Error processing {raw_url}: {e}")
        error_text = str(e)
        user_msg = (
            "Uh-oh. Houston, we have a problem:\n"
            f"<blockquote expandable>{html.escape(error_text)}</blockquote>"
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
                owner_report = (
                    f"🚨 <b>Something happened...</b>\n"
                    f"<blockquote expandable>{html.escape(error_text)}</blockquote>\n"
                )
                await client.send_document(config.OWNER_ID, document=doc, caption=owner_report, parse_mode=enums.ParseMode.HTML)
            except Exception as admin_err:
                logger.error(f"Failed to send log file: {admin_err}")
            except Exception as owner_err:
                logger.error(f"Failed to send log to owner: {owner_err}")
    finally:
        await asyncio.sleep(2)
        if os.path.exists(save_dir): shutil.rmtree(save_dir, ignore_errors=True)

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