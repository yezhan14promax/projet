import os
import json
import asyncio
import logging
import smtplib
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from dotenv import load_dotenv

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from aiokafka import AIOKafkaConsumer

# Load env
load_dotenv()
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_PASS")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI setup
app = FastAPI(title="Loan Verification Service")

# Kafka
KAFKA_BROKER = "172.20.225.146:9092"
PLAN_TOPIC = "plan"

# Kafka Consumer
consumer = None
consumer_task = None
consumer_status = {"running": False, "error": None}

# Chatroom WebSocket pool
chatroom_clients = set()
last_data = None  # 最新一条合同数据

@app.websocket("/ws/chatroom")
async def chatroom_ws(websocket: WebSocket):
    await websocket.accept()
    chatroom_clients.add(websocket)
    logger.info("🔗 Client connected to /ws/chatroom")

    try:
        while True:
            msg = await websocket.receive_text()
            logger.info(f"📥 Received confirmation message: {msg}")
            if msg.strip().lower() in {"我同意", "yes", "确认", "accept", "ok", "好的",'oui',"Je suis d'accord"}:
                await send_email_with_last_data()
    except WebSocketDisconnect:
        chatroom_clients.remove(websocket)
        logger.info("❌ Client disconnected from /ws/chatroom")

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
            logger.info("Kafka consumer started successfully")

            async for msg in consumer:
                data = json.loads(msg.value.decode("utf-8"))
                logger.info(f"📥 Received plan: {data}")
                try:
                    await process_verification(data)
                    await consumer.commit()
                    logger.info(f"✅ Committed offset for message: {msg.offset}")
                except Exception as e:
                    logger.error(f"❌ Error processing verification: {e}")

        except Exception as e:
            consumer_status["running"] = False
            logger.error(f"Kafka error: {e}")
        finally:
            if consumer:
                await consumer.stop()
                consumer_status["running"] = False
                logger.info("Kafka consumer stopped")
            await asyncio.sleep(5)

async def process_verification(data):
    """Process plan message: send contracts to chatroom WebSocket"""
    global last_data
    last_data = data  # 保存用于后续确认

    id_number = data.get("id_number", "unknown")
    contrat_texts = []

    try:
        # 贷款合同
        num_pret = data.get("num_pret")
        pret_path = Path(f"./contrat/pret/{num_pret}.txt")
        if pret_path.exists():
            contrat_texts.append(pret_path.read_text(encoding="utf-8"))

        # 保险合同（可选）
        num_assurance = data.get("num_assurance")
        if num_assurance:
            assurance_path = Path(f"./contrat/assurance/{num_assurance}.txt")
            if assurance_path.exists():
                contrat_texts.append(assurance_path.read_text(encoding="utf-8"))

        full_text = "\n\n".join(contrat_texts)

        # ✅ 广播给所有 WebSocket 客户端
        for ws in chatroom_clients:
            await ws.send_text(full_text)

        logger.info("📤 Contract broadcasted to /ws/chatroom")

        # ✅ 保存数据副本
        dataset_dir = Path("dataset")
        dataset_dir.mkdir(exist_ok=True)
        with open(dataset_dir / f"{id_number}.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"📁 Data saved to dataset/{id_number}.json")

    except Exception as e:
        logger.error(f"❌ Error processing contract display: {e}")

async def send_email_with_last_data():
    if last_data is None:
        logger.warning("⚠️ No plan data cached yet.")
        return
    await send_email_with_contracts(last_data)

async def send_email_with_contracts(data):
    recipient = data.get("email")
    num_pret = data.get("num_pret")
    num_assurance = data.get("num_assurance")

    if not recipient or not num_pret:
        logger.warning("Missing email or contract number.")
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

    try:
        pret_path = Path(f"./contrat/pret/{num_pret}.txt")
        with open(pret_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="txt")
            part.add_header("Content-Disposition", "attachment", filename=f"Contrat_Pret_{num_pret}.txt")
            message.attach(part)
        logger.info(f"📎 Pret contract attached: {pret_path}")
    except Exception as e:
        logger.error(f"❌ Failed to attach pret contract: {e}")

    if num_assurance:
        try:
            assurance_path = Path(f"./contrat/assurance/{num_assurance}.txt")
            with open(assurance_path, "rb") as f:
                part = MIMEApplication(f.read(), _subtype="txt")
                part.add_header("Content-Disposition", "attachment", filename=f"Contrat_Assurance_{num_assurance}.txt")
                message.attach(part)
            logger.info(f"📎 Assurance contract attached: {assurance_path}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to attach assurance contract: {e}")

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_PASS)
            server.send_message(message)
        logger.info(f"📧 Email sent to {recipient}")
    except Exception as e:
        logger.error(f"❌ Failed to send email: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
