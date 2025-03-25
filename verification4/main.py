import os
import json
import asyncio
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from aiokafka import AIOKafkaConsumer

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# FastAPI application
app = FastAPI(title="Loan Verification Service")

# Kafka Configuration
KAFKA_BROKER = "172.20.225.146:9092" # os.getenv("kafka:9092")  # Supports Docker
PLAN_TOPIC = "plan"  # Input: Received loan repayment plans

# Kafka Consumer
consumer = None
consumer_task = None
consumer_status = {"running": False, "error": None}

# WebSocket Connection Manager
class ConnectionManager:
    """Manages active WebSocket connections for id subscribers"""
    def __init__(self):
        self.active_connections: dict[int, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, id: int):
        """Accept WebSocket connection and register id"""
        await websocket.accept()
        if id not in self.active_connections:
            self.active_connections[id] = []
        self.active_connections[id].append(websocket)
        logger.info(f"New WebSocket connection for id {id}")

    def disconnect(self, websocket: WebSocket, id: int):
        """Remove WebSocket connection on disconnect"""
        if id in self.active_connections:
            self.active_connections[id].remove(websocket)
            if not self.active_connections[id]:  # Remove if empty
                del self.active_connections[id]
            logger.info(f"WebSocket disconnected for id {id}")

    async def send_message(self, id: int, message: str):
        """Send message to all clients subscribed to the given id"""
        if id in self.active_connections:
            for connection in self.active_connections[id]:
                await connection.send_text(message)
            logger.info(f"Sent message to {len(self.active_connections[id])} clients for id {id}")

# Create WebSocket connection manager
manager = ConnectionManager()

@app.websocket("/ws/{id}")
async def websocket_endpoint(websocket: WebSocket, id: int):
    """WebSocket endpoint for clients to subscribe to a specific id"""
    await manager.connect(websocket, id)
    try:
        while True:
            await websocket.receive_text()  # Keep connection alive
    except WebSocketDisconnect:
        manager.disconnect(websocket, id)

async def consume_kafka():
    """Kafka consumer that listens to the 'plan' topic with manual offset commit"""
    global consumer, consumer_status

    while True:  # Auto-reconnect if Kafka disconnects
        try:
            consumer = AIOKafkaConsumer(
                PLAN_TOPIC,
                bootstrap_servers=KAFKA_BROKER,
                auto_offset_reset="earliest",
                enable_auto_commit=False,
                group_id="loan_verification_service",
            )

            await consumer.start()
            consumer_status["running"] = True
            consumer_status["error"] = None
            logger.info("Kafka consumer started successfully")

            async for msg in consumer:
                data = json.loads(msg.value.decode("utf-8"))
                logger.info(f"Received repayment plan: {data}")

                try:
                    await process_verification(data)
                    await consumer.commit()  # Commit offset only if no error
                    logger.info(f"Committed offset for message: {msg.offset}")

                except Exception as e:
                    logger.error(f"Error processing verification, message NOT committed: {str(e)}")

        except Exception as e:
            consumer_status["running"] = False
            consumer_status["error"] = str(e)
            logger.error(f"Kafka consumer error: {str(e)}")

        finally:
            if consumer:
                await consumer.stop()
                consumer_status["running"] = False
                logger.info("Kafka consumer stopped")

            logger.info("Restarting Kafka consumer in 5 seconds...")
            await asyncio.sleep(5)

async def process_verification(data):
    """Process the loan repayment plan and notify the corresponding WebSocket clients"""
    id = data["id"]
    message = json.dumps(data)

    try:
        await manager.send_message(id, message)
        logger.info(f"Sent WebSocket notification for id {id}")
    except Exception as e:
        logger.error(f"Error sending WebSocket message: {str(e)}")
        raise

@app.get("/health/")
def health_check():
    """API endpoint to check Kafka consumer status"""
    return {"status": "running", "kafka_consumer": consumer_status}

@app.on_event("startup")
async def startup_event():
    """Automatically starts the Kafka consumer when the application starts"""
    global consumer_task
    try:
        consumer_task = asyncio.create_task(consume_kafka())
        logger.info("Loan Verification Service started successfully")
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Handle application shutdown"""
    global consumer_task
    logger.info("Shutting down Loan Verification Service...")
    if consumer_task:
        consumer_task.cancel()
        logger.info("Kafka consumer task canceled")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)

    # E:\anaconda3\python.exe f:/DataScale/OP/BPMN/projet/4_verification/main.py
    # wscat -c ws://172.20.225.146:8004/ws/1
