import pickle
import socket
import asyncio
import functools
import discord
import datetime
from subprocess import Popen
from os import getcwd
from sys import path, executable

parent_path = getcwd().replace('/discord', '')
path.append(parent_path)

from scripts.common import logger, config, register_signal_handler
logger.name = __file__

serverSocket = (config["listeners"]["discord"]["host"], config["listeners"]["discord"]["port"])
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind(serverSocket)
server.listen(1)
register_signal_handler(server, "discord")

TOKEN = config["listeners"]["discord"]["token"]
HOST = config["listeners"]["discord"]["host"]
PORT = config["listeners"]["discord"]["port"]
CHANNEL_ID = config["listeners"]["discord"]["channel_id"]

intents = discord.Intents.default()
client = discord.Client(intents=intents)
process = Popen([executable, "discord/bot.py"])


def embed_notification(stream : dict, streamer : dict) -> discord.Embed:
    username = streamer['USERNAME']
    title = stream['title']
    avatar_url = streamer['AVATAR_URL']
    heading = f"Streaming **__{stream['category']}__** with **{stream['view_count']}** viewers!"
    if len(stream['thumbnails']) > 0:
        thumbnail_url = stream['thumbnails'][-1].get('url')

    if stream['live_status'] == "is_live":
        if streamer['PLATFORM'] == 'yt':
            stream_url = f'https://youtube.com/{stream["id"]}'
        else:
            stream_url = f'https://twitch.tv/{stream["uploader_id"]}'

        embed_notif = discord.Embed(title=f'{username} has started a stream!', color=0x00ff00, url=stream_url)
        embed_notif.set_author(name=username, icon_url=avatar_url)
        embed_notif.set_image(url=thumbnail_url)
        embed_notif.add_field(name=heading, value=title)
        embed_notif.timestamp = datetime.datetime.now()
        
    else: # If scheduled notification
        stream_url = f'https://youtube.com/{stream["id"]}'
        hours_until_stream = round(((stream['scheduled_timestamp'] - datetime.datetime.now().timestamp()) / 3600), 1)
        if hours_until_stream < 0:
            heading = "**__Starting shortly!__**"
        else:
            heading = f"**__Starting in {hours_until_stream} hours!__**"

        embed_notif = discord.Embed(title=f'{username} has scheduled a stream!', color=0xff0000, url=stream_url)
        embed_notif.set_author(name=username, icon_url=avatar_url)
        embed_notif.set_image(url=thumbnail_url)
        embed_notif.add_field(name=heading, value=title)
        embed_notif.timestamp = datetime.datetime.now()

    return embed_notif


'''
With Discord, we'll constantly be re-connecting and disconnecting from the Socket.
Basically, we are trying to listen to two sockets at once: Discord's and the Detector.py client.
I have absolutely no clue how to do that so instead, we'll use this to_thread function I found on Stack Overflow. 
It basically offloads blocking functions to a separate thread. This utilizes asyncio.to_thread, which is only available in Python >= 3.9 (not tested).
'''


def to_thread(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)
    return wrapper


@to_thread
def start_listening(conn : socket.socket.accept = None):
    """
    On the first iteration we create a connection and pass it around to avoid re-establishing the connection unless an error occurs.
    If an error happens we re-create a connection which Detector.py will switch to while in it's handling of the broken connection.
    """
    logger.info(f"DISCORD currently listening on {HOST}:{PORT}")
    if conn == None:
        conn, addr = server.accept()

    try:
        packets = []
        while True:
            packet = conn.recv(4096)
            if not packet or packet[-3:] == b"END":
                packets.append(packet[:-3])
                break
            packets.append(packet)
        data = pickle.loads(b"".join(packets))

    except socket.error as e:
        logger.warning(e)
        return None, None # Should create a new connection as None is returned in place of a broken connection

    except EOFError:
        logger.warning("DISCORD connection shutdown. Will attempt to re-establish a connection")
        return None, None

    except Exception as e:
        logger.warning(e) # This will help catch exceptions that are not already handled and log it.

    return data, conn


@client.event
async def on_ready():
    channel = await client.fetch_channel(CHANNEL_ID)
    conn = None

    while True:
        streamer_data, conn = await start_listening(conn)

        if conn == None: # Connection error, nothing to do except hope for the best.
            continue
        elif streamer_data == None: # An error occured with the data received. Lets just say we're done so that Detector.py does not have to timeout.
            conn.sendall(b"DONE")
            continue

        for data in streamer_data:
            for stream in data['streams']:
                embed_notifi = embed_notification(stream, data['streamer'])
                await channel.send(embed=embed_notifi)
                logger.debug(f"Stream notification sent via Discord for {data['streamer']['USERNAME']}")
        # Send acknowledgement to the server
        conn.sendall(b"DONE")

client.run(TOKEN)