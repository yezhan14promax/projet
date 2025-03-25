import asyncio
import websockets

async def test_websocket():
    uri = "ws://localhost:8004/ws/1"  # loan_id = 1
    async with websockets.connect(uri) as websocket:
        print("Connected to WebSocket")
        while True:
            message = await websocket.recv()
            print(f"Received message: {message}")

asyncio.run(test_websocket())
