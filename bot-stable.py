import os
import discord
from discord.ext import commands
import aiohttp
import random
import time
import asyncio
import yt_dlp
import json
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
import io

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# FILE CONSTANTS
POKEMON_FILE = "pokedex.json"
INVENTORY_FILE = "inventory.json"
PACKS_FILE = "packs.json"
PACK_PRICE = 100


# ==================== MUSIC SETUP ====================
queues = {}  # guild_id: list of (source, title, url)

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -reconnect_at_eof 1',
    'options': '-vn'
}

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')          # Original webpage URL
        self.webpage_url = data.get('webpage_url') or data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ytdl_format_options).extract_info(url, download=not stream))
        
        if 'entries' in data:
            data = data['entries'][0]
        
        filename = data['url'] if stream else yt_dlp.YoutubeDL(ytdl_format_options).prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


def get_queue(guild_id):
    if guild_id not in queues:
        queues[guild_id] = []
    return queues[guild_id]


async def play_next(ctx):
    queue = get_queue(ctx.guild.id)
    
    if not queue:
        return

    next_source, next_title, next_url = queue.pop(0)
    try:
        ctx.voice_client.play(
            next_source,
            after=lambda e: after_play(ctx, bot, e)
        )
        await ctx.send(f"🎵 Now playing: **{next_title}**\n🔗 {next_url}")
    except Exception:
        await play_next(ctx)

def after_play(ctx, bot, err):
    if err:
        print(f"[ERROR] Player crashed: {err}")
    else:
        print("[INFO] Song finished normally")

    fut = asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
    try:
        fut.result()
    except Exception as e:
        print(f"[ERROR] Failed to play next: {e}")


# ==================== POKEMON SYSTEM ====================
def load_json(file):
    try:
        with open(file, "r") as f:
            return json.load(f)
    except:
        return {}

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

pokemon_data = load_json(POKEMON_FILE)
#pokemon_list = [p["name"]["english"] for p in pokemon_data]
pokemon_list = pokemon_data

# pokemon lookup funcs
pokemon_lookup = {
    p["name"]["english"].lower(): p
    for p in pokemon_data
}
inventory_data = load_json(INVENTORY_FILE)
packs_data = load_json(PACKS_FILE)

def get_inventory(user_id):
    user_id = str(user_id)
    if user_id not in inventory_data:
        inventory_data[user_id] = {}
    return inventory_data[user_id]

def get_packs(user_id):
    user_id = str(user_id)
    if user_id not in packs_data:
        packs_data[user_id] = 0
    return packs_data[user_id]

@bot.hybrid_command(name="shop", description="View shop")
async def shop(ctx):
    await ctx.send(
        f"🛒 **Shop**\n"
        f"📦 Pokemon Pack (6 cards) — {PACK_PRICE} coins\n\n"
        f"Use `/buy pack <amount>`"
    )

@bot.hybrid_command(name="info", description="View details of a Pokémon")
async def info(ctx, *, name: str):
    name = name.lower()

    if name not in pokemon_lookup:
        await ctx.send("❌ Pokémon not found.")
        return

    poke = pokemon_lookup[name]

    stats = poke["base"]
    types = ", ".join(poke["type"])

    embed = discord.Embed(
        title=poke["name"]["english"],
        description=poke.get("description", "No description available."),
        color=0x00ffcc
    )

    embed.add_field(
        name="📊 Stats",
        value=(
            f"HP: {stats['HP']}\n"
            f"ATK: {stats['Attack']}\n"
            f"DEF: {stats['Defense']}\n"
            f"SP. ATK: {stats['Sp. Attack']}\n"
            f"SP. DEF: {stats['Sp. Defense']}\n"
            f"SPD: {stats['Speed']}"
        ),
        inline=False
    )

    embed.add_field(name="🌿 Type", value=types, inline=True)
    embed.add_field(name="📏 Height", value=poke["profile"]["height"], inline=True)
    embed.add_field(name="⚖️ Weight", value=poke["profile"]["weight"], inline=True)

    # image (nice touch)
    embed.set_thumbnail(url=poke["image"]["thumbnail"])

    await ctx.send(embed=embed)

@bot.hybrid_command(name="buy", description="Buy items from shop")
async def buy(ctx, item: str, amount: int = 1):
    stats = get_user_stats(ctx.guild.id, ctx.author.id)

    if item.lower() != "pack":
        await ctx.send("❌ Only 'pack' is available right now.")
        return

    if amount <= 0:
        await ctx.send("❌ Invalid amount.")
        return

    cost = PACK_PRICE * amount

    if stats["coins"] < cost:
        await ctx.send("❌ Not enough coins.")
        return

    stats["coins"] -= cost

    packs_data[str(ctx.author.id)] = get_packs(ctx.author.id) + amount

    save_stats(user_stats)
    save_json(PACKS_FILE, packs_data)

    await ctx.send(f"✅ You bought {amount} pack(s)!")

# @bot.hybrid_command(name="open", description="Open a pokemon pack")
# async def open_pack(ctx):
#     user_id = str(ctx.author.id)

#     if get_packs(user_id) <= 0:
#         await ctx.send("❌ You don't have any packs.")
#         return

#     packs_data[user_id] -= 1

#     inventory = get_inventory(user_id)

#     pulled = []

#     for _ in range(6):  # 6 cards per pack
#         poke = random.choice(pokemon_list)  # equal chance
#         pulled.append(poke)

#         if poke in inventory:
#             inventory[poke] += 1
#         else:
#             inventory[poke] = 1

#     save_json(INVENTORY_FILE, inventory_data)
#     save_json(PACKS_FILE, packs_data)

#     result = "\n".join([f"• {p}" for p in pulled])

#     await ctx.send(
#         f"🎁 **You opened a pack!**\n\n{result}"
#     )

@bot.hybrid_command(name="open", description="Open a pokemon pack")
async def open_pack(ctx):
    user_id = str(ctx.author.id)

    if get_packs(user_id) <= 0:
        await ctx.send("❌ You don't have any packs.")
        return

    packs_data[user_id] -= 1
    inventory = get_inventory(user_id)

    embeds = []

    for _ in range(6):
        poke = random.choice(pokemon_list)  # full object
        name = poke["name"]["english"]

        # add to inventory
        if name in inventory:
            inventory[name] += 1
        else:
            inventory[name] = 1

        types = ", ".join(poke["type"])
        desc = poke.get("description", "No description.")

        embed = discord.Embed(
            title=name,
            description=desc[:150] + ("..." if len(desc) > 150 else ""),
            color=0x00ffcc
        )

        embed.add_field(name="🌿 Type", value=types, inline=False)

        embed.set_thumbnail(url=poke["image"]["thumbnail"])

        embeds.append(embed)
        

    save_json(INVENTORY_FILE, inventory_data)
    save_json(PACKS_FILE, packs_data)
    
    #for origianl embed sending method (one by one)
    #await ctx.send("🎁 **You opened a pack!**")
    # # send all 6 embeds
    # for e in embeds:
    #     await ctx.send(embed=e)
    await ctx.send(content="🎁 **You opened a pack!**", embeds=embeds)

# inventory original
# @bot.hybrid_command(name="inventory", description="View your pokemon cards")
# async def inventory(ctx):
#     inv = get_inventory(ctx.author.id)

#     if not inv:
#         await ctx.send("📭 Your inventory is empty.")
#         return

#     text = ""

#     for name, count in sorted(inv.items()):
#         text += f"{name} x{count}\n"

#     await ctx.send(f"🎒 **Your Cards:**\n{text}")

@bot.hybrid_command(name="inventory", description="View your pokemon cards")
async def inventory(ctx):
    await ctx.defer()
    inv = get_inventory(ctx.author.id)

    if not inv:
        await ctx.send("📭 Your inventory is empty.")
        return

    # SETTINGS
    cols = 6
    cell_size = 96
    padding = 10

    items = list(inv.items())
    rows = (len(items) + cols - 1) // cols

    width = cols * (cell_size + padding) + padding
    height = rows * (cell_size + padding) + padding

    # Create background
    img = Image.new("RGBA", (width, height), (30, 30, 30, 255))
    draw = ImageDraw.Draw(img)

    font = ImageFont.truetype("Roboto-Regular.ttf", 16)

    async with aiohttp.ClientSession() as session:

        for i, (name, count) in enumerate(items):
            row = i // cols
            col = i % cols

            x = padding + col * (cell_size + padding)
            y = padding + row * (cell_size + padding)

            # 🔍 get pokemon data
            poke = pokemon_lookup.get(name.lower())
            if not poke:
                continue

            img_url = poke["image"]["thumbnail"]  # using thumbnail for faster loading

            # 🌐 fetch image
            try:
                async with session.get(img_url) as resp:
                    data = await resp.read()
                poke_img = Image.open(io.BytesIO(data)).convert("RGBA")
            except:
                continue

            poke_img = poke_img.resize((cell_size, cell_size))
            img.paste(poke_img, (x, y), poke_img)

            # 🔢 draw count
            text = f"{name} x{count}"
            draw.text((x + 5, y + cell_size - 18), text, font=font, fill="white")

    # send image
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    file = discord.File(fp=buffer, filename="inventory.png")
    await ctx.send(file=file)


# ==================== STATS SYSTEM ====================
STATS_FILE = "stats.json"

def load_stats():
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_stats(data):
    with open(STATS_FILE, "w") as f:
        json.dump(data, f, indent=4)
        f.flush()

user_stats = load_stats()

def get_user_stats(guild_id, user_id):
    guild_id = str(guild_id)
    user_id = str(user_id)

    if guild_id not in user_stats:
        user_stats[guild_id] = {}

    if user_id not in user_stats[guild_id]:
        user_stats[guild_id][user_id] = {
            "messages": 0,
            "commands": 0,
            "coins": 0
        }

    # 🔥 ensures old users get coins field too
    if "coins" not in user_stats[guild_id][user_id]:
        user_stats[guild_id][user_id]["coins"] = 0

    return user_stats[guild_id][user_id]

# ==================== EVENTS ====================

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return
    
    if random.random() < 0.03:
        responses = [
            "I don't trust any of you.",
            "Something feels off.",
            "This server has terrible decision-making skills.",
            "I'm just watching."
        ]
        await message.channel.send(random.choice(responses))

    stats = get_user_stats(message.guild.id, message.author.id)
    stats["messages"] += 1
    stats["coins"] += 1   # 💰 1 coin per message
    save_stats(user_stats)

    await bot.process_commands(message)

@bot.event
async def on_command(ctx):
    if not ctx.guild:
        return

    stats = get_user_stats(ctx.guild.id, ctx.author.id)
    stats["commands"] += 1
    save_stats(user_stats)


# ==================== REDDIT COMMAND ====================
@bot.hybrid_command(name="reddit", description="Fetch random posts from a subreddit")
async def fetch_reddit(ctx, subreddit: str, sort: str = "24h"):
    if len(subreddit) < 2:
        await ctx.send("❌ Please provide a valid subreddit name.")
        return

    subreddit = subreddit.lower().strip().replace("r/", "")

    if sort.lower() in ["new", "latest"]:
        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=50"
        mode_text = "Newest"
    elif sort.lower() in ["hot"]:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=30"
        mode_text = "Hot"
    else:
        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=50"
        mode_text = "Random from last 24h"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers={"User-Agent": "DiscordBot:Jarvis/1.0"}) as resp:
            if resp.status != 200:
                await ctx.send(f"❌ Could not fetch r/{subreddit} (Error: {resp.status}).")
                return

            try:
                data = await resp.json()
            except Exception:
                await ctx.send(f"❌ Failed to read response from r/{subreddit}.")
                return

            if not data.get('data') or not data['data'].get('children'):
                await ctx.send(f"❌ **Subreddit not found**: r/{subreddit} does not exist or is private/banned.")
                return

    posts = data['data']['children']
    now = time.time()
    filtered_posts = []

    for post in posts:
        p = post['data']
        if p.get('stickied'):
            continue
        if sort.lower() not in ["new", "latest", "hot"]:
            if now - p.get('created_utc', 0) > 86400:
                continue
        filtered_posts.append(p)

    if not filtered_posts:
        await ctx.send(f"❌ No posts found in r/{subreddit}.")
        return

    await ctx.send(f"🎲 **{mode_text} in r/{subreddit}**")

    selected = random.sample(filtered_posts, min(3, len(filtered_posts)))

    for p in selected:
        title = p['title'][:256]
        link = f"https://reddit.com{p['permalink']}"
        upvotes = p['score']
        comments = p['num_comments']

        embed = discord.Embed(title=title, url=link, color=0xFF4500)
        embed.add_field(name="Upvotes", value=upvotes, inline=True)
        embed.add_field(name="Comments", value=comments, inline=True)

        if p.get('selftext'):
            embed.description = p['selftext'][:500]

        if p.get('url') and any(p['url'].endswith(ext) for ext in ('.jpg', '.png', '.gif', '.jpeg')):
            embed.set_image(url=p['url'])

        await ctx.send(embed=embed)


# ==================== MUSIC COMMANDS ====================
@bot.hybrid_command(name="play", description="Play a song or add to queue")
async def play(ctx, *, query: str):
    if not ctx.author.voice:
        await ctx.send("❌ You need to be in a voice channel first!")
        return

    await ctx.send(f"🔎 Searching for: **{query}**...")

    try:
        source = await YTDLSource.from_url(query, loop=bot.loop)
    except Exception as e:
        await ctx.send(f"❌ Could not find that song.\nTry a different search term or YouTube link.")
        return

    # Join or move to voice channel
    if ctx.voice_client is None:
        await ctx.author.voice.channel.connect()
    elif ctx.voice_client.channel != ctx.author.voice.channel:
        await ctx.voice_client.move_to(ctx.author.voice.channel)

    queue = get_queue(ctx.guild.id)
    song_url = source.webpage_url or source.url

    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        queue.append((source, source.title, song_url))
        await ctx.send(f"✅ **{source.title}** added to queue.\n🔗 {song_url}")
    else:
        ctx.voice_client.play(
            source,
            after=lambda e: after_play(ctx, bot, e)
        )
        await ctx.send(f"🎵 Now playing: **{source.title}**\n🔗 {song_url}")


@bot.hybrid_command(name="next", description="Skip to the next song")
async def next_song(ctx):
    if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        ctx.voice_client.stop()
        await ctx.send("⏭️ Skipped to next song.")
    else:
        await ctx.send("Nothing is playing right now.")


@bot.hybrid_command(name="nowplaying", description="Show what song is currently playing with link")
async def nowplaying(ctx):
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        await ctx.send("❌ Nothing is currently playing.")
        return

    source = ctx.voice_client.source
    if not hasattr(source, 'title'):
        await ctx.send("❌ Could not get current song info.")
        return

    song_url = getattr(source, 'webpage_url', None) or getattr(source, 'url', 'No link available')

    embed = discord.Embed(title="🎵 Now Playing", color=0xFF4500)
    embed.add_field(name="Song", value=source.title, inline=False)
    embed.add_field(name="Link", value=f"[Watch on YouTube]({song_url})", inline=False)
    
    await ctx.send(embed=embed)


@bot.hybrid_command(name="queue", description="Show the current music queue")
async def show_queue(ctx):
    queue = get_queue(ctx.guild.id)
    voice_client = ctx.voice_client

    if not queue and not (voice_client and voice_client.is_playing()):
        await ctx.send("🎵 The queue is empty.")
        return

    embed = discord.Embed(title="🎵 Music Queue", color=0xFF4500)

    # Currently Playing
    if voice_client and voice_client.is_playing():
        source = voice_client.source
        song_url = getattr(source, 'webpage_url', None) or getattr(source, 'url', 'No link')
        embed.add_field(
            name="Now Playing", 
            value=f"▶️ **{source.title}**\n[Watch on YouTube]({song_url})", 
            inline=False
        )

    # Queue
    if queue:
        queue_text = ""
        for i, (_, title, url) in enumerate(queue, 1):
            queue_text += f"{i}. **{title}**\n   [Link]({url})\n"
        embed.add_field(name=f"Up Next ({len(queue)} songs)", value=queue_text, inline=False)
    else:
        embed.add_field(name="Up Next", value="No songs in queue.", inline=False)

    await ctx.send(embed=embed)


@bot.hybrid_command(name="stop", description="Stop music and disconnect")
async def stop(ctx):
    if ctx.voice_client:
        queues.pop(ctx.guild.id, None)
        await ctx.voice_client.disconnect()
        await ctx.send("⏹️ Stopped music and left the voice channel.")
    else:
        await ctx.send("I'm not in a voice channel.")


@bot.hybrid_command(name="pause", description="Pause current song")
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Paused.")
    else:
        await ctx.send("Nothing is playing.")


@bot.hybrid_command(name="resume", description="Resume paused song")
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ Resumed.")
    else:
        await ctx.send("Nothing to resume.")


@bot.hybrid_command(name="geek", description="Play random geek music")
async def geek(ctx):
    geek_searches = [
        "cyberpunk synthwave mix",
        "best chiptune music",
        "retrowave 2026",
        "epic geek electronic music",
        "lofi geek beats"
    ]
    query = random.choice(geek_searches)
    await ctx.invoke(bot.get_command("play"), query=query)

# ==================== STATS COMMANDS ====================

@bot.hybrid_command(name="stats", description="Show your stats")
async def stats(ctx):
    stats = get_user_stats(ctx.guild.id, ctx.author.id)

    await ctx.send(
        f"📊 **Stats for {ctx.author.display_name}**\n"
        f"💬 Messages: {stats['messages']}\n"
        f"⚙️ Commands: {stats['commands']}\n"
        f"💰 Coins: {stats['coins']}"
    )

@bot.hybrid_command(name="leaderboard", description="Top chatters")
async def leaderboard(ctx):
    guild_data = user_stats.get(str(ctx.guild.id), {})

    sorted_users = sorted(
        guild_data.items(),
        key=lambda x: x[1]["messages"],
        reverse=True
    )[:5]

    text = "🏆 **Top Chatters**\n\n"

    for i, (user_id, data) in enumerate(sorted_users, 1):
        user = await bot.fetch_user(int(user_id))
        text += f"{i}. {user.name} — {data['messages']} messages and {data['coins']} coins\n"

    await ctx.send(text)

@bot.hybrid_command(name="balance", description="Check your coins")
async def balance(ctx):
    stats = get_user_stats(ctx.guild.id, ctx.author.id)

    await ctx.send(
        f"💰 **{ctx.author.display_name}'s Balance**\n"
        f"Coins: {stats['coins']}"
    )

# PAYMENT COMMANDS
@bot.hybrid_command(name="pay", description="Send coins to another user")
async def pay(ctx, member: discord.Member, amount: int):
    if member.bot:
        await ctx.send("❌ You can't pay bots.")
        return

    if member.id == ctx.author.id:
        await ctx.send("❌ You can't pay yourself.")
        return

    if amount <= 0:
        await ctx.send("❌ Enter a valid amount.")
        return

    sender = get_user_stats(ctx.guild.id, ctx.author.id)
    receiver = get_user_stats(ctx.guild.id, member.id)

    if sender["coins"] < amount:
        await ctx.send("❌ You don't have enough coins.")
        return

    sender["coins"] -= amount
    receiver["coins"] += amount

    save_stats(user_stats)

    await ctx.send(
        f"💸 **{ctx.author.display_name}** sent {amount} coins to **{member.display_name}**!"
    )


# ================= MISC COMMANDS ==================

# This command is a fun image editor that adds text to an image at specified positions.
@bot.hybrid_command(name="imedit", description="Add text to an image")
async def imedit(
    ctx,
    text: str,
    position: str,
    image: discord.Attachment
):
    await ctx.defer()

    # 🔽 VALID POSITIONS
    positions = {
        "topleft": (0, 0),
        "topcenter": (0.5, 0),
        "topright": (1, 0),
        "centerleft": (0, 0.5),
        "center": (0.5, 0.5),
        "centerright": (1, 0.5),
        "bottomleft": (0, 1),
        "bottomcenter": (0.5, 1),
        "bottomright": (1, 1),
    }

    pos_key = position.lower()

    if pos_key not in positions:
        await ctx.send(
            "❌ Invalid position.\nUse: topleft, topcenter, topright, centerleft, center, centerright, bottomleft, bottomcenter, bottomright"
        )
        return

    # 📥 LOAD IMAGE
    try:
        img_bytes = await image.read()
        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    except:
        await ctx.send("❌ Could not read the image.")
        return

    draw = ImageDraw.Draw(img)
    width, height = img.size

    # ================= AUTO TEXT HANDLING =================
    import textwrap

    max_width = int(width * 0.9)

    # wrap text (prevents insane shrinking)
    wrapped_text = text
    max_chars = 25
    lines = textwrap.wrap(text, width=max_chars)
    wrapped_text = "\n".join(lines)

    # 🔤 AUTO FONT SIZE
    font_size = int(width / 8)
    max_font_size = 120
    font_size = min(font_size, max_font_size)

    while font_size > 10:
        try:
            font = ImageFont.truetype("Roboto-Regular.ttf", font_size)
        except:
            font = ImageFont.load_default()

        bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font)
        text_width = bbox[2] - bbox[0]

        if text_width <= max_width:
            break

        font_size -= 2

    # final text size
    bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # 📍 POSITION
    rel_x, rel_y = positions[pos_key]
    x = int((width - text_width) * rel_x)
    y = int((height - text_height) * rel_y)

    # ✨ OUTLINE (scales with font)
    outline_thickness = max(2, font_size // 15)

    for dx in range(-outline_thickness, outline_thickness + 1):
        for dy in range(-outline_thickness, outline_thickness + 1):
            if dx != 0 or dy != 0:
                draw.multiline_text(
                    (x + dx, y + dy),
                    wrapped_text,
                    font=font,
                    fill="black",
                    align="center"
                )

    # 🎯 MAIN TEXT
    draw.multiline_text(
        (x, y),
        wrapped_text,
        font=font,
        fill="white",
        align="center"
    )

    # 📤 SEND
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    await ctx.send(file=discord.File(fp=buffer, filename="edited.png"))

@bot.hybrid_command(name="yuta", description="Put your text in Yuta's speech bubble")
async def yuta(ctx, *, text: str):
    await ctx.defer()

    import io
    from PIL import Image, ImageDraw, ImageFont

    # ===== LOAD TEMPLATE =====
    image = Image.open("yuta.png").convert("RGBA")
    draw = ImageDraw.Draw(image)

    # ===== TOP-RIGHT BUBBLE BOX (LIKE /IMEDIT) =====
    margin_x = int(image.width * 0.05)
    margin_y = int(image.height * 0.05)

    bubble_w = int(image.width * 0.38)
    bubble_h = int(image.height * 0.38)

    bubble_x = image.width - bubble_w - margin_x
    bubble_y = margin_y

    # ===== TEXT WRAP FUNCTION =====
    def wrap_text(text, font, max_width):
        lines = []
        words = text.split()
        current = ""

        for word in words:
            test = current + word + " "
            if draw.textlength(test, font=font) <= max_width:
                current = test
            else:
                lines.append(current)
                current = word + " "

        if current:
            lines.append(current)

        return lines

    # ===== AUTO FONT SCALING =====
    font_size = 42
    min_font_size = 18

    while font_size >= min_font_size:
        font = ImageFont.truetype("Roboto-Regular.ttf", font_size)

        lines = wrap_text(text, font, bubble_w - 20)

        total_height = len(lines) * (font_size + 5)

        if total_height <= bubble_h - 20:
            break

        font_size -= 2  # shrink until it fits

    # ===== CENTER TEXT INSIDE BUBBLE =====
    y_offset = bubble_y + (bubble_h - total_height) // 2

    for line in lines:
        line_width = draw.textlength(line, font=font)

        x = bubble_x + (bubble_w - line_width) // 2 + 50  # 50px padding from bubble edge

        draw.text(
            (x, y_offset),
            line.strip(),
            font=font,
            fill="black"
        )

        y_offset += font_size + 5

    # ===== SEND =====
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    file = discord.File(fp=buffer, filename="yuta.png")
    await ctx.send(file=file)


@bot.hybrid_command(name="invite", description="Invite someone to the island")
async def invite(ctx, member: discord.Member):
    import io
    import aiohttp
    from PIL import Image, ImageDraw, ImageFont

    # Load template
    image = Image.open("invite.jpg").convert("RGBA")
    draw = ImageDraw.Draw(image)

    # Load font
    font = ImageFont.truetype("Roboto-Regular.ttf", 40)

    # ================== GET AVATAR ==================
    avatar_url = member.display_avatar.url

    async with aiohttp.ClientSession() as session:
        async with session.get(avatar_url) as resp:
            avatar_bytes = await resp.read()

    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")

    # Resize avatar
    avatar_size = 120
    avatar = avatar.resize((avatar_size, avatar_size))

    # Make avatar circular (cleaner look)
    mask = Image.new("L", (avatar_size, avatar_size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
    avatar.putalpha(mask)

    # ================== POSITIONS ==================
    width, height = image.size

    # Avatar position (top center-ish)
    avatar_x = (width // 2) - 200  # 200px left of center
    avatar_y = int(height * 0.03)  # 3% from top

    image.paste(avatar, (avatar_x, avatar_y), avatar)

    # ================== NAME ==================
    text = member.display_name  # 🔥 better than member.name

    text_width = draw.textlength(text, font=font)

    text_x = avatar_x + avatar_size + 20   # 20px gap from avatar
    text_y = avatar_y + (avatar_size // 4) # vertical alignment tweak

    # Optional outline (makes text readable on bright bg)
    draw.text((text_x-2, text_y-2), text, font=font, fill="black")
    draw.text((text_x+2, text_y-2), text, font=font, fill="black")
    draw.text((text_x-2, text_y+2), text, font=font, fill="black")
    draw.text((text_x+2, text_y+2), text, font=font, fill="black")

    draw.text((text_x, text_y), text, font=font, fill="white")

    # ================== SEND ==================
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    file = discord.File(fp=buffer, filename="invite.png")
    await ctx.send(file=file)

@bot.hybrid_command(name="coinflip", description="Flip a coin")
async def coinflip(ctx):
    await ctx.send("🪙 Flipping the coin...")

    await asyncio.sleep(1.2)  # dramatic pause

    result = random.choice(["Heads", "Tails"])
    await ctx.send(f"👉 **{result}**!")

@bot.hybrid_command(name="gamble", description="Gamble your coins")
async def gamble(ctx, amount: int):
    stats = get_user_stats(ctx.guild.id, ctx.author.id)

    if amount <= 0:
        await ctx.send("❌ Enter a valid amount.")
        return

    if stats["coins"] < amount:
        await ctx.send("❌ You don't have enough coins.")
        return

    await ctx.send("🎰 Rolling...")
    await asyncio.sleep(1.2)

    roll = random.random()

    # ================= RESULTS =================
    if roll < 0.45:
        stats["coins"] += amount
        result = f"You WON {amount} coins!"
        outcome = "win"

    elif roll < 0.75:
        loss = int(amount * 0.5)
        stats["coins"] -= loss
        result = f"You lost {loss} coins..."
        outcome = "loss"

    elif roll > 0.98:
        win = amount * 5
        stats["coins"] += win
        result = f"JACKPOT! You won {win} coins!"
        outcome = "win"

    else:
        stats["coins"] -= amount
        result = f"You LOST everything ({amount})!"
        outcome = "loss"

    save_stats(user_stats)

    # ================= CHAOS =================
    chaos_line = ""

    if random.random() < 0.15:
        if outcome == "win":
            chaos_line = "\nGAMBLE AGAIN YOU CAN WIN IT BACK"
        else:
            chaos_line = "\n's'okay man keep gambling, statistically youre gonna win atleast once"

    # ✅ ALWAYS SEND (outside the if)
    await ctx.send(
        f"{result}{chaos_line}\nNew Balance: {stats['coins']}"
    )

# This command generates a custom profile card image showing the user's stats and rank in the server.
@bot.hybrid_command(name="profile", description="View your profile")
async def profile(ctx, member: discord.Member = None):
    await ctx.defer()

    if member is None:
        member = ctx.author

    stats = get_user_stats(ctx.guild.id, member.id)

    import aiohttp
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    import io

    # ================= BASE =================
    width, height = 900, 360  # 🔥 increased height
    img = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(img)

    # 🌈 Gradient background (kept)
    for y in range(height):
        r = int(30 + (y / height) * 40)
        g = int(30 + (y / height) * 20)
        b = int(50 + (y / height) * 60)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # ================= FONTS =================
    font_big = ImageFont.truetype("Roboto-Regular.ttf", 48)
    font_mid = ImageFont.truetype("Roboto-Regular.ttf", 26)
    font_small = ImageFont.truetype("Roboto-Regular.ttf", 22)

    # ================= AVATAR =================
    async with aiohttp.ClientSession() as session:
        async with session.get(member.display_avatar.url) as resp:
            avatar_bytes = await resp.read()

    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")

    avatar_size = 170
    avatar = avatar.resize((avatar_size, avatar_size))

    # Circle mask
    mask = Image.new("L", (avatar_size, avatar_size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
    avatar.putalpha(mask)

    # Glow
    glow_size = avatar_size + 20
    glow = Image.new("RGBA", (glow_size, glow_size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((0, 0, glow_size, glow_size), fill=(120, 80, 255, 120))
    glow = glow.filter(ImageFilter.GaussianBlur(15))

    img.paste(glow, (60 - 10, 75 - 10), glow)
    img.paste(avatar, (60, 75), avatar)

    # ================= NAME =================
    draw.text((260, 70), member.display_name, font=font_big, fill="white")

    # ================= RANK =================
    guild_data = user_stats.get(str(ctx.guild.id), {})

    sorted_users = sorted(
        guild_data.items(),
        key=lambda x: x[1]["messages"],
        reverse=True
    )

    rank = next((i for i, (uid, _) in enumerate(sorted_users, 1) if uid == str(member.id)), "?")

    draw.text((260, 130), f"Rank #{rank}", font=font_mid, fill=(255, 215, 0))

    # ================= STATS =================
    draw.text((260, 180), f"Coins: {stats['coins']}", font=font_small, fill="white")
    draw.text((260, 210), f"Messages: {stats['messages']}", font=font_small, fill="white")
    draw.text((260, 240), f"Commands: {stats['commands']}", font=font_small, fill="white")

    # ================= PROGRESS BAR =================
    level = stats["messages"] // 100
    progress = stats["messages"] % 100

    bar_x, bar_y = 260, 300   # 🔥 moved down
    bar_width, bar_height = 500, 22

    def draw_rounded_bar(draw, x, y, w, h, radius, fill):
        draw.rounded_rectangle((x, y, x + w, y + h), radius=radius, fill=fill)

    # Background bar
    draw_rounded_bar(draw, bar_x, bar_y, bar_width, bar_height, 12, (60, 60, 80))

    # Progress fill
    fill_width = int((progress / 100) * bar_width)
    draw_rounded_bar(draw, bar_x, bar_y, fill_width, bar_height, 12, (120, 80, 255))

    # Level text (moved up cleanly)
    draw.text(
        (bar_x, bar_y - 35),
        f"Level {level} ({progress}/100)",
        font=font_small,
        fill="white"
    )

    # ================= SAVE =================
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    file = discord.File(fp=buffer, filename="profile.png")
    await ctx.send(file=file)

# This command shows overall server stats and highlights the top chatter.
@bot.hybrid_command(name="serverstats", description="Show server statistics")
async def serverstats(ctx):
    guild_data = user_stats.get(str(ctx.guild.id), {})

    if not guild_data:
        await ctx.send("📊 No data for this server yet.")
        return

    total_messages = sum(user["messages"] for user in guild_data.values())
    total_commands = sum(user["commands"] for user in guild_data.values())
    total_coins = sum(user["coins"] for user in guild_data.values())

    # 🏆 Top user
    top_user_id, top_data = max(
        guild_data.items(),
        key=lambda x: x[1]["messages"]
    )

    top_user = await bot.fetch_user(int(top_user_id))

    embed = discord.Embed(
        title=f"📊 Server Stats - {ctx.guild.name}",
        color=0x00ffcc
    )

    embed.add_field(name="💬 Total Messages", value=total_messages)
    embed.add_field(name="⚙️ Total Commands", value=total_commands)
    embed.add_field(name="💰 Total Coins", value=total_coins)

    embed.add_field(
        name="🏆 Top User",
        value=f"{top_user.name} ({top_data['messages']} msgs) | ({top_data['coins']} coins)",
        inline=False
    )

    await ctx.send(embed=embed)

# This command simulates a magic 8ball response with a fun API and adds flavor based on the mood of the answer.
@bot.hybrid_command(name="8ball", description="Ask the magic 8ball a question")
async def eightball(ctx, *, question: str):
    await ctx.defer()

    url = "https://eightballapi.com/api?locale=en"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
    except Exception:
        await ctx.send("❌ The 8ball is currently asleep. Try again later.")
        return

    answer = data.get("reading", "No answer...")
    # mood = data.get("category", "neutral")  # ✅ FIXED

    # if mood == "positive":
    #     emoji = "🟢"
    # elif mood == "negative":
    #     emoji = "🔴"
    # else:
    #     emoji = "🟡"

    await ctx.send(
        f"🎱 **Question:** {question}\n"
        #f"{emoji} **Answer:** {answer}"
        f"**Answer:** {answer}"
    )

# ==================== ON READY ====================
@bot.event
async def on_ready():
    print(f"{bot.user} is online and ready!")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"Failed to sync: {e}")

bot.run(os.getenv("DISCORD_TOKEN"))