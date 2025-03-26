import os
import json
import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from dotenv import load_dotenv
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from aiokafka import AIOKafkaConsumer

# Load environment variables
load_dotenv()
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_PASS")

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(title="Loan Verification Service")

# Kafka config
KAFKA_BROKER = "172.20.225.146:9092"
PLAN_TOPIC = "plan"

# Kafka Consumer
consumer = None
consumer_task = None
consumer_status = {"running": False, "error": None}

# WebSocket Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, id_number: str):
        await websocket.accept()
        if id_number not in self.active_connections:
            self.active_connections[id_number] = []
        self.active_connections[id_number].append(websocket)
        logger.info(f"New WebSocket connection for id_number {id_number}")

    def disconnect(self, websocket: WebSocket, id_number: str):
        if id_number in self.active_connections:
            self.active_connections[id_number].remove(websocket)
            if not self.active_connections[id_number]:
                del self.active_connections[id_number]
            logger.info(f"WebSocket disconnected for id_number {id_number}")

    async def send_message(self, id_number: str, message: str):
        if id_number in self.active_connections:
            for connection in self.active_connections[id_number]:
                await connection.send_text(message)
            logger.info(f"Sent message to {len(self.active_connections[id_number])} clients for id_number {id_number}")

manager = ConnectionManager()

@app.websocket("/ws/{id_number}")
async def websocket_endpoint(websocket: WebSocket, id_number: str):
    await manager.connect(websocket, id_number)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, id_number)

async def consume_kafka():
    global consumer, consumer_status

    while True:
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
                    await consumer.commit()
                    logger.info(f"Committed offset for message: {msg.offset}")
                except Exception as e:
                    logger.error(f"Error processing verification: {e}")

        except Exception as e:
            consumer_status["running"] = False
            consumer_status["error"] = str(e)
            logger.error(f"Kafka consumer error: {str(e)}")
        finally:
            if consumer:
                await consumer.stop()
                consumer_status["running"] = False
                logger.info("Kafka consumer stopped")
            await asyncio.sleep(5)

async def process_verification(data):
    """Process plan message: notify websocket + send email with contracts"""
    id_number = data.get("id_number", "anonymous")
    message = json.dumps(data)

    try:
        await manager.send_message(id_number, message)
        logger.info(f"Sent WebSocket notification for id_number {id_number}")
    except Exception as e:
        logger.warning(f"WebSocket failed (can be skipped if not used): {e}")

    try:
        await send_email_with_contracts(data)
    except Exception as e:
        logger.error(f"Email sending failed: {e}")

    # ✅ 保存数据副本到 ./dataset
    try:
        dataset_dir = Path("./dataset")
        dataset_dir.mkdir(parents=True, exist_ok=True)
        dataset_file = dataset_dir / f"{id_number}.json"
        with open(dataset_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"📁 Plan data saved to: {dataset_file}")
    except Exception as e:
        logger.error(f"❌ Failed to write dataset file: {e}")


async def send_email_with_contracts(data):
    recipient = data.get("email")
    num_pret = data.get("num_pret")
    num_assurance = data.get("num_assurance")

    if not recipient or not num_pret:
        logger.warning("Missing email or loan contract number")
        return

    message = MIMEMultipart()
    message["From"] = GMAIL_USER
    message["To"] = recipient
    message["Subject"] = "📄 Vos contrats de prêt"

    body = f"Bonjour {data.get('name', '')},\n\nVeuillez trouver ci-joint votre contrat de prêt"
    if num_assurance:
        body += " ainsi que le contrat d’assurance."
    body += "\n\nCordialement,\nL'équipe de validation des prêts"

    message.attach(MIMEText(body, "plain"))

    # 添加贷款合同附件
    try:
        pret_path = Path(f"./contrat/pret/{num_pret}.txt")
        with open(pret_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="txt")
            part.add_header("Content-Disposition", "attachment", filename=f"Contrat_Pret_{num_pret}.txt")
            message.attach(part)
        logger.info(f"📎 Contrat de prêt attaché：{pret_path}")
    except Exception as e:
        logger.error(f"❌ Erreur lecture contrat prêt: {e}")

    # 添加保险合同附件（可选）
    if num_assurance:
        try:
            assurance_path = Path(f"./contrat/assurance/{num_assurance}.txt")
            with open(assurance_path, "rb") as f:
                part = MIMEApplication(f.read(), _subtype="txt")
                part.add_header("Content-Disposition", "attachment", filename=f"Contrat_Assurance_{num_assurance}.txt")
                message.attach(part)
            logger.info(f"📎 Contrat d'assurance attaché：{assurance_path}")
        except Exception as e:
            logger.warning(f"⚠️ Erreur lecture contrat assurance: {e}")

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_PASS)
            server.send_message(message)
        logger.info(f"📧 Email envoyé à {recipient}")
    except Exception as e:
        logger.error(f"❌ Échec d'envoi d'email: {e}")

@app.get("/health/")
def health_check():
    return {"status": "running", "kafka_consumer": consumer_status}

@app.on_event("startup")
async def startup_event():
    global consumer_task
    consumer_task = asyncio.create_task(consume_kafka())
    logger.info("Loan Verification Service started successfully")

@app.on_event("shutdown")
async def shutdown_event():
    global consumer_task
    logger.info("Shutting down Loan Verification Service...")
    if consumer_task:
        consumer_task.cancel()
        logger.info("Kafka consumer task canceled")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
