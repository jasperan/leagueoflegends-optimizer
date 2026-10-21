# Legacy 2023 script, kept for reference. The maintained path is lol-ml-26ai/ (README there).
# Copyright (c) 2022 Oracle and/or its affiliates.

'''
@author jasperan
This file uses web sockets to communicate Live Client API data from one endpoint to the other. You can virtually put your consumer 
wherever you want, and let it process the incoming data from the producer.
''' 

import time
from pathlib import Path
import requests
import pandas as pd
import datetime
import argparse
import json 
import websockets
import asyncio
from rich import print


cli_parser = argparse.ArgumentParser()
cli_parser.add_argument('-i', '--ip', type=str, help='address to listen on (default 127.0.0.1, loopback only)',
                        default='127.0.0.1')
args = cli_parser.parse_args()

MIN_INTERVAL = 1.0  # seconds: never ask the local game API more often than this, serve the cached answer instead
_last_fetch = 0.0
_last_content = {}

def build_object(content):
    global _last_fetch, _last_content
    try:
        assert type(content) == type(str())
    except AssertionError:
        return {}
    if time.monotonic() - _last_fetch < MIN_INTERVAL:
        return _last_content
    _last_fetch = time.monotonic()
    try:
        response = requests.get('https://127.0.0.1:2999/liveclientdata/allgamedata', verify=False, timeout=5)
    except requests.exceptions.RequestException:
        print('{} | Currently not in game'.format(datetime.datetime.now()))
        _last_content = {}
        return _last_content
    if response.status_code != 200:
        _last_content = {}
        return _last_content
    # We convert to JSON format
    content = response.json()
    for x in content['allPlayers']:
        x.pop('items', None) # delete items to avoid quotation marks

    _last_content = content
    return content



async def handler(websocket):
    while True:
        message = await websocket.recv()
        print('{} | request: {}'.format(datetime.datetime.now(), message))  # logged once per request

        if message == 'get_liveclient_data':
            result = build_object(message)
        else:
            result = {}

        await websocket.send(json.dumps(result))




async def main():
    # bind to loopback by default: the Live Client data should not be exposed to the whole network
    async with websockets.serve(handler, args.ip, 8001):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
