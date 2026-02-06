import os
import asyncio
import logging
import shutil
import subprocess
import requests
import html
import sys
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    InputMediaPhoto, BotCommand
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

DOWNLOAD_PATH = "downloads"

DEFAULT_SETTINGS = {
    "audio": True,
    "desc": True,
    "sep_desc": False,
    "link_btn": True 
}

user_settings = {}

logging.basicConfig(level=logging.INFO)

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

if not os.path.exists(DOWNLOAD_PATH):
    os.makedirs(DOWNLOAD_PATH)

def get_settings(user_id):
    if user_id not in user_settings:
        user_settings[user_id] = DEFAULT_SETTINGS.copy()
    return user_settings[user_id]

def get_real_url(short_url):
    try:
        return requests.head(short_url, allow_redirects=True, timeout=5).url
    except:
        return short_url

def download_gallery(url, save_dir):
    cmd = ["gallery-dl", "--directory", save_dir, "--no-mtime", url]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except Exception as e:
        logging.error(f"Gallery error: {e}")
        return False

def download_audio_force(url, save_dir):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{save_dir}/audio.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'noplaylist': True,
        'quiet': True,
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
        'noplaylist': True,
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info), info

def get_meta_info(url):
    ydl_opts = {'quiet': True, 'noplaylist': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            return ydl.extract_info(url, download=False)
        except:
            return None

def get_settings_kb(user_id):
    s = get_settings(user_id)
    kb = [
        [InlineKeyboardButton(f"🎵 Download audio: {'✅' if s['audio'] else '❌'}", callback_data="set_audio")],
        [InlineKeyboardButton(f"📝 Add desc: {'✅' if s['desc'] else '❌'}", callback_data="set_desc")],
    ]
    if s['desc']:
        kb.append([InlineKeyboardButton(f"📄 Desc. separately: {'✅' if s['sep_desc'] else '❌'}", callback_data="set_sep")])
    
    kb.append([InlineKeyboardButton(f"🔗 Add OG link: {'✅' if s['link_btn'] else '❌'}", callback_data="set_link")])
    return InlineKeyboardMarkup(kb)

@app.on_message(filters.command("settings"))
async def settings_handler(client, message):
    await message.reply("⚙️ <b>Download settings:</b>", reply_markup=get_settings_kb(message.from_user.id))

@app.on_callback_query(filters.regex("^set_"))
async def callback_handler(client, callback):
    uid = callback.from_user.id
    action = callback.data.split("_")[1]
    s = get_settings(uid)
    
    if action == "audio": s['audio'] = not s['audio']
    elif action == "desc": s['desc'] = not s['desc']
    elif action == "sep": s['sep_desc'] = not s['sep_desc']
    elif action == "link": s['link_btn'] = not s['link_btn']
    
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

@app.on_message(filters.regex(r"(tiktok\.com|youtu\.be|youtube\.com|instagram\.com)"))
async def link_handler(client, message: Message):
    uid = message.from_user.id
    settings = get_settings(uid)
    
    raw_url = message.text.split()[0]
    
    status = await message.reply("⏳ Downloading...")
    
    unique_id = str(message.id)
    save_dir = os.path.join(DOWNLOAD_PATH, unique_id)
    if not os.path.exists(save_dir): os.makedirs(save_dir)

    try:
        real_url = await asyncio.to_thread(get_real_url, raw_url)
        info = await asyncio.to_thread(get_meta_info, real_url)
        
        caption = ""
        buttons = None
        
        meta_title = "Original Audio"
        meta_artist = "Bot"

        if info:
            author = html.escape(info.get('uploader', 'User'))
            desc = html.escape(info.get('description', '') or info.get('title', ''))
            if len(desc) > 800: desc = desc[:800] + "..."
            
            if settings['desc']:
                caption = f"<b>{author}</b>\n\n{desc}"

            meta_title = info.get('track') or info.get('title') or "Audio"
            meta_artist = info.get('artist') or info.get('uploader') or "Bot"
            if len(meta_title) > 100: meta_title = meta_title[:100]

        if settings['link_btn']:
            buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 OG Link", url=real_url)]])
        elif settings['desc']:
            caption += f"\n\n<a href='{real_url}'>Source Link</a>"

        is_photo = "/photo/" in real_url or "instagram.com/p/" in real_url

        if is_photo:
            tasks = [asyncio.to_thread(download_gallery, real_url, save_dir)]
            if settings['audio']:
                tasks.append(asyncio.to_thread(download_audio_force, real_url, save_dir))
            
            await asyncio.gather(*tasks)

            photos = []
            audio_file = None
            
            for root, _, files in os.walk(save_dir):
                for f in files:
                    path = os.path.join(root, f)
                    if f.lower().endswith(('.jpg', '.png', '.webp')):
                        photos.append(path)
                    elif f.lower().endswith(('.mp3', '.m4a')):
                        audio_file = path
            
            if not photos:
                await status.edit_text("❌ Nothing found.")
                return

            await status.edit_text("🔄️ Uploading...")

            photos.sort()
            
            chunk_size = 10
            first_caption = caption if (not settings['sep_desc']) else ""
            
            for i in range(0, len(photos), chunk_size):
                chunk = photos[i:i + chunk_size]
                media_group = []
                for idx, p in enumerate(chunk):
                    cap = first_caption if (i==0 and idx==0) else ""
                    media_group.append(InputMediaPhoto(p, caption=cap))
                
                await client.send_media_group(message.chat.id, media=media_group, reply_to_message_id=message.id)

            if settings['desc'] and settings['sep_desc'] and caption:
                btn_to_use = buttons if (not audio_file or not settings['audio']) else None
                await message.reply(caption, reply_markup=btn_to_use)
                if not audio_file: buttons = None

            if audio_file and settings['audio']:
                await client.send_audio(
                    message.chat.id, 
                    audio_file, 
                    title=meta_title, 
                    performer=meta_artist, 
                    reply_markup=buttons, 
                    reply_to_message_id=message.id
                )
                buttons = None

            if buttons and settings['link_btn'] and not settings['sep_desc']:
                 await message.reply("🔗", reply_markup=buttons)

            await status.delete()

        else:
            tasks = [asyncio.to_thread(download_video, real_url, save_dir)]
            if settings['audio']:
                tasks.append(asyncio.to_thread(download_audio_force, real_url, save_dir))
            
            results = await asyncio.gather(*tasks)
            vid_path = results[0][0]
            
            if vid_path and os.path.exists(vid_path):
                await status.edit_text("🔄️ Uploading...")
                
                vid_cap = caption if not settings['sep_desc'] else ""
                vid_btn = buttons if not settings['sep_desc'] else None
                
                await client.send_video(
                    message.chat.id, 
                    video=vid_path, 
                    caption=vid_cap, 
                    reply_markup=vid_btn,
                    reply_to_message_id=message.id
                )
                
                if settings['audio']:
                    audio_file = None
                    for root, _, files in os.walk(save_dir):
                        for f in files:
                            if f.lower().endswith(('.mp3', '.m4a')):
                                audio_file = os.path.join(root, f)
                                break
                    
                    if audio_file:
                         await client.send_audio(
                             message.chat.id, 
                             audio_file, 
                             title=meta_title, 
                             performer=meta_artist, 
                             reply_to_message_id=message.id
                        )

                if settings['desc'] and settings['sep_desc'] and caption:
                    await message.reply(caption, reply_markup=buttons)

                await status.delete()
            else:
                await status.edit_text("❌ Video download error.")

    except Exception as e:
        await status.edit_text(f"Error: {e}")
        logging.error(e)
    
    finally:
        await asyncio.sleep(5)
        if os.path.exists(save_dir):
            try: shutil.rmtree(save_dir)
            except: pass

async def start_bot():
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