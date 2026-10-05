import asyncio
import websockets
import json

async def test():
    async with websockets.connect('wss://fstream.binance.com/ws/btcusdt@depth') as ws:
        for _ in range(2):
            print(await ws.recv())

asyncio.run(test())
