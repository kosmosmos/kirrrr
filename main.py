

import os
import json
import shutil
from config import config
from core.song import Song
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pytgcalls import filters as fl
from pyrogram import Client, filters
from pytgcalls.types import Update, ChatUpdate
from pytgcalls.types.stream import StreamAudioEnded, StreamVideoEnded
from core.decorators import language, register, only_admins, handle_error
from pyrogram.enums import ChatMemberStatus
from pytgcalls.exceptions import (
    NotInCallError, GroupCallNotFound, NoActiveGroupCall)
from core import (
    app, ytdl, safone, search, is_sudo, is_admin, get_group, get_queue,
    pytgcalls, set_group, set_title, all_groups, clear_queue, check_yt_url,
    extract_args, start_stream, shuffle_queue, delete_messages,
    get_spotify_playlist, get_youtube_playlist)
from pyrogram.errors import PeerIdInvalid, UserNotParticipant
from collections import defaultdict
import logging
from threading import Lock
telegraph_url = "https://telegra.ph/Sylix-Music-Player-Help-07-29"

if config.BOT_TOKEN:
    bot = Client(
        "MusicPlayer",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.BOT_TOKEN,
        in_memory=True,
    )
    client = bot
else:
    client = app




logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


vote_counter = {}
playback_users = {}

async def update_vote(chat_id):
    global vote_counter
    vote_counter[chat_id] = 0



vote_counter = {}

async def update_vote(chat_id):
    global vote_counter
    vote_counter[chat_id] = 0

async def is_member(client, user_id, channel):
    try:
        member = await client.get_chat_member(channel, user_id)
        print(f"User {user_id} membership status in {channel}: {member.status}")
        is_member_status = member.status in ["member", "administrator", "creator", "owner"]
        print(f"is_member_status for user {user_id}: {is_member_status}")
        return True
    except UserNotParticipant:
        print(f"User {user_id} is not a participant in {channel}.")
        return False
    except PeerIdInvalid:
        print(f"Channel {channel} is invalid or the bot has no access.")
        return False
    except Exception as e:
        print(f"Error checking membership for user {user_id} in {channel}: {e}")
        return False

async def l_admin(user_id, chat_id):
    try:
        member: ChatMember = await client.get_chat_member(chat_id, user_id)
        print(f"User {user_id} is {member.status} in chat {chat_id}")  # Debug print
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        print(f"Error checking admin status for user {user_id} in chat {chat_id}: {e}")
        return False


@client.on_message(filters.command("ping", config.PREFIXES) & ~filters.bot)
@handle_error
async def ping(_, message: Message):
    await message.reply_text(f"🤖 **Pong!**\n{pytgcalls.ping} ms")

@client.on_message(filters.command("start", config.PREFIXES) & ~filters.bot)
@language
@handle_error
async def start(_, message: Message, lang):
    await message.reply_text(lang["startText"] % message.from_user.mention)

@client.on_message(filters.command("help", config.PREFIXES) & ~filters.bot)
@language
@handle_error
async def help(client, message: Message, lang):
    help_button = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("راهنمای کامل", url=telegraph_url)]
        ]
    )
    await message.reply_text(
        "help",
        reply_markup=help_button
    )

@client.on_message(filters.command("menu", config.PREFIXES) & ~filters.private)
@only_admins
@handle_error
async def menu(client, message: Message, is_auto_call=False):
    chat_id = message.chat.id
    if not is_auto_call:
        update_vote(chat_id)  # Reset votes for new menu
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Resume", callback_data="resume"), InlineKeyboardButton("Pause", callback_data="pause")],
        [InlineKeyboardButton("Skip", callback_data="skip"), InlineKeyboardButton("Stop", callback_data="stop")],
        [InlineKeyboardButton("Queue", callback_data="queue")],
        [InlineKeyboardButton("Vote to Skip (0/3)", callback_data="vote_skip")]
    ])
    if is_auto_call:
        await client.send_message(chat_id, "Choose an option:", reply_markup=keyboard)
    else:
        await message.reply("Choose an option:", reply_markup=keyboard)

@client.on_callback_query()
async def callback_query_handler(client, query):
    data = query.data
    message = query.message
    chat_id = message.chat.id
    user_id = query.from_user.id

    # Check if the user is allowed to use the menu
    if data != "vote_skip":
        member: ChatMember = await client.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await query.answer("You are not allowed to use these controls.", show_alert=True)
            return

    if data == "resume":
        await resume_vc(client, message)
        await query.answer("Resumed...", show_alert=True)
    elif data == "pause":
        await pause_vc(client, message)
        await query.answer("Paused...", show_alert=True)
    elif data == "skip":
        await skip_track(client, message)
        await query.answer("Skipped...", show_alert=True)
    elif data == "stop":
        await leave_vc(client, message)
        await query.answer("Stopped...", show_alert=True)
    elif data == "queue":
        await queue_list(client, message)
        await query.answer("Queue:", show_alert=True)
    elif data == "vote_skip":
        await handle_vote_skip(query)


async def handle_vote_skip(query):
    chat_id = query.message.chat.id
    user_id = query.from_user.id

    if chat_id not in vote_counter:
        vote_counter[chat_id] = set()

    if user_id not in vote_counter[chat_id]:
        vote_counter[chat_id].add(user_id)
        votes = len(vote_counter[chat_id])
        await query.answer(f"Voted! {votes}/3 votes", show_alert=True)

        if votes >= 3:
            await skip_track(client, query.message)
            vote_counter[chat_id] = set()
        else:
            await update_vote_button(query.message, votes)
    else:
        await query.answer("You already voted!", show_alert=True)

async def update_vote_button(message, votes):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Resume", callback_data="resume"), InlineKeyboardButton("Pause", callback_data="pause")],
        [InlineKeyboardButton("Skip", callback_data="skip"), InlineKeyboardButton("Stop", callback_data="stop")],
        [InlineKeyboardButton("Queue", callback_data="queue")],
        [InlineKeyboardButton(f"Vote to Skip ({votes}/3)", callback_data="vote_skip")]
    ])
    await message.edit_reply_markup(reply_markup=keyboard)

@client.on_message(filters.command(["p", "play"], config.PREFIXES) & ~filters.private)
@register
@language
@handle_error
async def play_stream(_, message: Message, lang):
    user_id = message.from_user.id
    required_channel = config.REQUIRED_CHANNEL

    if required_channel and not await is_member(client, user_id, required_channel):
       join_message = f"برای استفاده از ربات باید عضو [این کانال](https://t.me/{required_channel[1:]}) شوید."
       await message.reply_text(join_message, disable_web_page_preview=True)
       return

    chat_id = message.chat.id
    group = get_group(chat_id)
    song = await search(message)
    if song is None:
        k = await message.reply_text(lang["notFound"])
        return await delete_messages([message, k])
    ok, status = await song.parse()
    if not ok:
        raise Exception(status)
    if not group["is_playing"]:
        set_group(chat_id, is_playing=True, now_playing=song)
        await start_stream(song, lang)
        await menu(client, message, True)  # Add this line to open the menu after starting the stream
        await delete_messages([message])
    else:
        queue = get_queue(chat_id)
        await queue.put(song)
        k = await message.reply_text(
            lang["addedToQueue"] % (song.title, song.source, len(queue)),
            disable_web_page_preview=True,
        )
        await delete_messages([message, k])




@client.on_message(
    filters.command(["radio", "stream"], config.PREFIXES) & ~filters.private
)
@register
@language
@handle_error
async def live_stream(_, message: Message, lang):
    user_id = message.from_user.id
    required_channel = config.REQUIRED_CHANNEL

    if required_channel and not await is_member(client, user_id, required_channel):
       join_message = f"برای استفاده از ربات باید عضو [این کانال](https://t.me/{required_channel[1:]}) شوید."
       await message.reply_text(join_message, disable_web_page_preview=True)
       return
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["admins_only"]:
        check = await is_admin(message)
        if not check:
            k = await message.reply_text(lang["notAllowed"])
            return await delete_messages([message, k])
    args = extract_args(message.text)
    if args is None:
        k = await message.reply_text(lang["notFound"])
        return await delete_messages([message, k])
    if " " in args and args.count(" ") == 1 and args[-5:] == "parse":
        song = Song({"source": args.split(" ")[0], "parsed": False}, message)
    else:
        is_yt_url, url = check_yt_url(args)
        if is_yt_url:
            meta = ytdl.extract_info(url, download=False)
            formats = meta.get("formats", [meta])
            for f in formats:
                ytstreamlink = f["url"]
            link = ytstreamlink
            song = Song(
                {"title": "YouTube Stream", "source": link, "remote": link}, message
            )
        else:
            song = Song(
                {"title": "Live Stream", "source": args, "remote": args}, message
            )
    ok, status = await song.parse()
    if not ok:
        raise Exception(status)
    if not group["is_playing"]:
        set_group(chat_id, is_playing=True, now_playing=song)
        await start_stream(song, lang)
        await delete_messages([message])
    else:
        queue = get_queue(chat_id)
        await queue.put(song)
        k = await message.reply_text(
            lang["addedToQueue"] % (song.title, song.source, len(queue)),
            disable_web_page_preview=True,
        )
        await delete_messages([message, k])


@client.on_message(
    filters.command(["skip", "next"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def skip_track(_, message: Message, lang):
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["loop"]:
        await start_stream(group["now_playing"], lang)
        await menu(client, message, True)  # Add this line to open the menu after starting the stream
    else:
        queue = get_queue(chat_id)
        if len(queue) > 0:
            next_song = await queue.get()
            if not next_song.parsed:
                ok, status = await next_song.parse()
                if not ok:
                    raise Exception(status)
            set_group(chat_id, now_playing=next_song)
            await start_stream(next_song, lang)
            await menu(client, message, True)  # Add this line to open the menu after starting the stream
            await delete_messages([message])
        else:
            set_group(chat_id, is_playing=False, now_playing=None)
            await set_title(message, "")
            try:
                await pytgcalls.leave_call(chat_id)
                k = await message.reply_text(lang["queueEmpty"])
            except (NoActiveGroupCall, GroupCallNotFound, NotInCallError):
                k = await message.reply_text(lang["notActive"])
            await delete_messages([message, k])


@client.on_message(filters.command(["m", "mute"], config.PREFIXES) & ~filters.private)
@register
@language
@only_admins
@handle_error
async def mute_vc(_, message: Message, lang):
    chat_id = message.chat.id
    try:
        await pytgcalls.mute_stream(chat_id)
        k = await message.reply_text(lang["muted"])
    except (NoActiveGroupCall, GroupCallNotFound, NotInCallError):
        k = await message.reply_text(lang["notActive"])
    await delete_messages([message, k])


@client.on_message(
    filters.command(["um", "unmute"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def unmute_vc(_, message: Message, lang):
    chat_id = message.chat.id
    try:
        await pytgcalls.unmute_stream(chat_id)
        k = await message.reply_text(lang["unmuted"])
    except (NoActiveGroupCall, GroupCallNotFound, NotInCallError):
        k = await message.reply_text(lang["notActive"])
    await delete_messages([message, k])


@client.on_message(filters.command(["ps", "pause"], config.PREFIXES) & ~filters.private)
@register
@language
@only_admins
@handle_error
async def pause_vc(_, message: Message, lang):
    chat_id = message.chat.id
    try:
        await pytgcalls.pause_stream(chat_id)
        k = await message.reply_text(lang["paused"])
    except (NoActiveGroupCall, GroupCallNotFound, NotInCallError):
        k = await message.reply_text(lang["notActive"])
    await delete_messages([message, k])


@client.on_message(
    filters.command(["rs", "resume"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def resume_vc(_, message: Message, lang):
    chat_id = message.chat.id
    try:
        await pytgcalls.resume_stream(chat_id)
        k = await message.reply_text(lang["resumed"])
    except (NoActiveGroupCall, GroupCallNotFound, NotInCallError):
        k = await message.reply_text(lang["notActive"])
    await delete_messages([message, k])


@client.on_message(
    filters.command(["stop", "leave"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def leave_vc(_, message: Message, lang):
    chat_id = message.chat.id
    set_group(chat_id, is_playing=False, now_playing=None)
    await set_title(message, "")
    clear_queue(chat_id)
    try:
        await pytgcalls.leave_call(chat_id)
        k = await message.reply_text(lang["leaveVC"])
    except (NoActiveGroupCall, GroupCallNotFound, NotInCallError):
        k = await message.reply_text(lang["notActive"])
    await delete_messages([message, k])


@client.on_message(
    filters.command(["list", "queue"], config.PREFIXES) & ~filters.private
)
@register
@language
@handle_error
async def queue_list(_, message: Message, lang):
    chat_id = message.chat.id
    queue = get_queue(chat_id)
    if len(queue) > 0:
        k = await message.reply_text(str(queue), disable_web_page_preview=True)
    else:
        k = await message.reply_text(lang["queueEmpty"])
    await delete_messages([message, k])


@client.on_message(
    filters.command(["mix", "shuffle"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def shuffle_list(_, message: Message, lang):
    user_id = message.from_user.id
    required_channel = config.REQUIRED_CHANNEL

    if required_channel and not await is_member(client, user_id, required_channel):
       join_message = f"برای استفاده از ربات باید عضو [این کانال](https://t.me/{required_channel[1:]}) شوید."
       await message.reply_text(join_message, disable_web_page_preview=True)
       return
    chat_id = message.chat.id
    if len(get_queue(chat_id)) > 0:
        shuffled = shuffle_queue(chat_id)
        k = await message.reply_text(str(shuffled), disable_web_page_preview=True)
    else:
        k = await message.reply_text(lang["queueEmpty"])
    await delete_messages([message, k])


@client.on_message(
    filters.command(["loop", "repeat"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def loop_stream(_, message: Message, lang):
    user_id = message.from_user.id
    required_channel = config.REQUIRED_CHANNEL

    if required_channel and not await is_member(client, user_id, required_channel):
       join_message = f"برای استفاده از ربات باید عضو [این کانال](https://t.me/{required_channel[1:]}) شوید."
       await message.reply_text(join_message, disable_web_page_preview=True)
       return
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["loop"]:
        set_group(chat_id, loop=False)
        k = await message.reply_text(lang["loopMode"] % "Disabled")
    elif group["loop"] == False:
        set_group(chat_id, loop=True)
        k = await message.reply_text(lang["loopMode"] % "Enabled")
    await delete_messages([message, k])





@client.on_message(
    filters.command(["mode", "switch"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def switch_mode(_, message: Message, lang):
    user_id = message.from_user.id
    required_channel = config.REQUIRED_CHANNEL

    if required_channel and not await is_member(client, user_id, required_channel):
       join_message = f"برای استفاده از ربات باید عضو [این کانال](https://t.me/{required_channel[1:]}) شوید."
       await message.reply_text(join_message, disable_web_page_preview=True)
       return
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["stream_mode"] == "audio":
        set_group(chat_id, stream_mode="video")
        k = await message.reply_text(lang["videoMode"])
    else:
        set_group(chat_id, stream_mode="audio")
        k = await message.reply_text(lang["audioMode"])
    await delete_messages([message, k])


@client.on_message(
    filters.command(["admins", "adminsonly"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def admins_only(_, message: Message, lang):
    user_id = message.from_user.id
    required_channel = config.REQUIRED_CHANNEL

    if required_channel and not await is_member(client, user_id, required_channel):
       join_message = f"برای استفاده از ربات باید عضو [این کانال](https://t.me/{required_channel[1:]}) شوید."
       await message.reply_text(join_message, disable_web_page_preview=True)
       return
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["admins_only"]:
        set_group(chat_id, admins_only=False)
        k = await message.reply_text(lang["adminsOnly"] % "Disabled")
    else:
        set_group(chat_id, admins_only=True)
        k = await message.reply_text(lang["adminsOnly"] % "Enabled")
    await delete_messages([message, k])


@client.on_message(
    filters.command(["lang", "language"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def set_lang(_, message: Message, lang):
    chat_id = message.chat.id
    lng = extract_args(message.text)
    if lng != "":
        langs = [
            file.replace(".json", "")
            for file in os.listdir(f"{os.getcwd()}/lang/")
            if file.endswith(".json")
        ]
        if lng == "list":
            k = await message.reply_text("\n".join(langs))
        elif lng in langs:
            set_group(chat_id, lang=lng)
            k = await message.reply_text(lang["langSet"] % lng)
        else:
            k = await message.reply_text(lang["notFound"])
        await delete_messages([message, k])


@client.on_message(
    filters.command(["ep", "export"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def export_queue(_, message: Message, lang):
    chat_id = message.chat.id
    queue = get_queue(chat_id)
    if len(queue) > 0:
        data = json.dumps([song.to_dict() for song in queue], indent=2)
        filename = f"{message.chat.username or message.chat.id}.json"
        with open(filename, "w") as file:
            file.write(data)
        await message.reply_document(
            filename, caption=lang["queueExported"] % len(queue)
        )
        os.remove(filename)
        await delete_messages([message])
    else:
        k = await message.reply_text(lang["queueEmpty"])
        await delete_messages([message, k])


@client.on_message(
    filters.command(["ip", "import"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def import_queue(_, message: Message, lang):
    user_id = message.from_user.id
    required_channel = config.REQUIRED_CHANNEL

    if required_channel and not await is_member(client, user_id, required_channel):
       join_message = f"برای استفاده از ربات باید عضو [این کانال](https://t.me/{required_channel[1:]}) شوید."
       await message.reply_text(join_message, disable_web_page_preview=True)
       return
    if not message.reply_to_message or not message.reply_to_message.document:
        k = await message.reply_text(lang["replyToAFile"])
        return await delete_messages([message, k])
    chat_id = message.chat.id
    filename = await message.reply_to_message.download()
    data_str = None
    with open(filename, "r") as file:
        data_str = file.read()
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        k = await message.reply_text(lang["invalidFile"])
        return await delete_messages([message, k])
    try:
        temp_queue = []
        for song_dict in data:
            song = Song(song_dict["source"], message)
            song.title = song_dict["title"]
            temp_queue.append(song)
    except BaseException:
        k = await message.reply_text(lang["invalidFile"])
        return await delete_messages([message, k])
    group = get_group(chat_id)
    queue = get_queue(chat_id)
    if group["is_playing"]:
        for _song in temp_queue:
            await queue.put(_song)
    else:
        song = temp_queue[0]
        set_group(chat_id, is_playing=True, now_playing=song)
        ok, status = await song.parse()
        if not ok:
            raise Exception(status)
        await start_stream(song, lang)
        for _song in temp_queue[1:]:
            await queue.put(_song)
    k = await message.reply_text(lang["queueImported"] % len(temp_queue))
    await delete_messages([message, k])


@client.on_message(filters.command(["vol", "volume"], config.PREFIXES) & ~filters.private)
@register
@language
@only_admins
@handle_error
async def set_volume(_, message: Message, lang):
    user_id = message.from_user.id
    required_channel = config.REQUIRED_CHANNEL

    if required_channel and not await is_member(client, user_id, required_channel):
       join_message = f"برای استفاده از ربات باید عضو [این کانال](https://t.me/{required_channel[1:]}) شوید."
       await message.reply_text(join_message, disable_web_page_preview=True)
       return
    
    chat_id = message.chat.id
    group = get_group(chat_id)
    
    # Check if the bot is playing in the voice chat
    if not group["is_playing"]:
        response_message = await message.reply_text("❌ | **ربات در حال حاضر در چت صوتی نیست. لطفا ابتدا ربات را به چت صوتی اضافه کنید.**")
        await delete_messages([message, response_message])
        return

    volume_text = extract_args(message.text)
    
    # Validate the volume
    if volume_text.isdigit() and 0 <= int(volume_text) <= 200:
        volume = int(volume_text)
        try:
            # Change the volume of the call
            await pytgcalls.change_volume_call(chat_id, volume)
            response_message = await message.reply_text(f"🔊 | **حجم صدا به {volume}% تنظیم شد.**")
        except Exception as e:
            response_message = await message.reply_text(f"❌ | **تنظیم حجم صدا ناموفق بود: {str(e)}**")
    else:
        response_message = await message.reply_text("❌ | **حجم صدای نامعتبر. لطفا عددی بین 0 تا 100 وارد کنید.**")
    
    # Optionally delete the original message and the bot's response after some time
    await delete_messages([message, response_message])




@client.on_message(
    filters.command(["pl", "playlist"], config.PREFIXES) & ~filters.private
)
@register
@language
@handle_error
async def import_playlist(_, message: Message, lang):
    user_id = message.from_user.id
    required_channel = config.REQUIRED_CHANNEL

    if required_channel and not await is_member(client, user_id, required_channel):
       join_message = f"برای استفاده از ربات باید عضو [این کانال](https://t.me/{required_channel[1:]}) شوید."
       await message.reply_text(join_message, disable_web_page_preview=True)
       return
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["admins_only"]:
        check = await is_admin(message)
        if not check:
            k = await message.reply_text(lang["notAllowed"])
            return await delete_messages([message, k])
    if message.reply_to_message:
        text = message.reply_to_message.text
    else:
        text = extract_args(message.text)
    if text == "":
        k = await message.reply_text(lang["notFound"])
        return await delete_messages([message, k])
    if "youtube.com/playlist?list=" in text:
        try:
            temp_queue = get_youtube_playlist(text, message)
        except BaseException:
            k = await message.reply_text(lang["notFound"])
            return await delete_messages([message, k])
    elif "open.spotify.com/playlist/" in text:
        if not config.SPOTIFY:
            k = await message.reply_text(lang["spotifyNotEnabled"])
            return await delete_messages([message, k])
        try:
            temp_queue = get_spotify_playlist(text, message)
        except BaseException:
            k = await message.reply_text(lang["notFound"])
            return await delete_messages([message, k])
    else:
        k = await message.reply_text(lang["invalidFile"])
        return await delete_messages([message, k])
    queue = get_queue(chat_id)
    if not group["is_playing"]:
        song = await temp_queue.__anext__()
        set_group(chat_id, is_playing=True, now_playing=song)
        ok, status = await song.parse()
        if not ok:
            raise Exception(status)
        await start_stream(song, lang)
        async for _song in temp_queue:
            await queue.put(_song)
        queue.get_nowait()
    else:
        async for _song in temp_queue:
            await queue.put(_song)
    k = await message.reply_text(lang["queueImported"] % len(group["queue"]))
    await delete_messages([message, k])


@client.on_message(
    filters.command(["update", "restart"], config.PREFIXES) & ~filters.private
)
@language
@handle_error
async def update_restart(_, message: Message, lang):
    check = await is_sudo(message)
    if not check:
        k = await message.reply_text(lang["notAllowed"])
        return await delete_messages([message, k])
    chats = all_groups()
    stats = await message.reply_text(lang["update"])
    for chat in chats:
        try:
            await pytgcalls.leave_call(chat)
        except (NoActiveGroupCall, GroupCallNotFound, NotInCallError):
            pass
    await stats.edit_text(lang["restart"])
    shutil.rmtree("downloads", ignore_errors=True)
    os.system(f"kill -9 {os.getpid()} && bash startup.sh")


@pytgcalls.on_update(fl.stream_end)
@language
@handle_error
async def stream_end(_, update: Update, lang):
    if isinstance(update, StreamAudioEnded) or isinstance(update, StreamVideoEnded):
        chat_id = update.chat_id
        group = get_group(chat_id)
        if group["loop"]:
            await start_stream(group["now_playing"], lang)
            await menu(client, update, True)  # Add this line to open the menu after starting the stream
        else:
            queue = get_queue(chat_id)
            if len(queue) > 0:
                next_song = await queue.get()
                if not next_song.parsed:
                    ok, status = await next_song.parse()
                    if not ok:
                        raise Exception(status)
                set_group(chat_id, now_playing=next_song)
                await start_stream(next_song, lang)
                await menu(client, update, True)  # Add this line to open the menu after starting the stream
            else:
                if safone.get(chat_id) is not None:
                    try:
                        await safone[chat_id].delete()
                    except BaseException:
                        pass
                await set_title(chat_id, "", client=app)
                set_group(chat_id, is_playing=False, now_playing=None)
                try:
                    await pytgcalls.leave_call(chat_id)
                except (NoActiveGroupCall, GroupCallNotFound, NotInCallError):
                    pass




@pytgcalls.on_update(fl.chat_update(ChatUpdate.Status.LEFT_CALL))
@handle_error
async def closed_vc(_, update: Update):
    chat_id = update.chat_id
    if chat_id not in all_groups():
        if safone.get(chat_id) is not None:
            try:
                await safone[chat_id].delete()
            except BaseException:
                pass
        await set_title(chat_id, "", client=app)
        set_group(chat_id, now_playing=None, is_playing=False)
        clear_queue(chat_id)


client.start()
pytgcalls.run()
