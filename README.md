# KPDLoader

Simple (vibecoded 🫩) Telegram bot for downloading content from TikTok, YouTube Shorts, Instagram and YT Music (only music.youtube.com links are supported) 

## Requirements 
<ul>
<li><b>Python 3.8+</b></li>
<li><b>FFmpeg</b></li>
</ul>
  
## Before using it
Firstly, install dependencies
<pre><code>pip install -r requirements.txt</code></pre>
Then you need to rename <code>config.py.sample</code> to <code>config.py</code> and add your API_ID, API_HASH and BOT_TOKEN information
### bbut where to get it?
<ul>
  <li><b>API_ID & API_HASH:</b> Get them from <a href="https://my.telegram.org">my.telegram.org</a>.</li>
  <li><b>BOT_TOKEN:</b> Get it from <a href="https://t.me/BotFather">@BotFather</a>.</li>
</ul>
Optional: add your account ID to OWNER_ID line if you want to receive error logs

### And, finally, run it
<pre><code>python KPDLoader.py</code></pre>
