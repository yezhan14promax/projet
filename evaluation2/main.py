import os
import json
import asyncio
import logging
import smtplib
from fastapi import FastAPI
from datetime import datetime
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi.responses import StreamingResponse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).resolve().parents[1] / '.env'
load_dotenv(dotenv_path=env_path)

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_PASS")
print(f"GMAIL_USER = {GMAIL_USER}")
print(f"GMAIL_PASS = {'***' if GMAIL_PASS else None}")


# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# FastAPI application
app = FastAPI(title="Loan Evaluation Service")

# Kafka Configuration
KAFKA_BROKER = "172.20.225.146:9092"
VALIDATED_TOPIC = "validated_requests"
ACCEPTED_TOPIC = "acceptation"

# Kafka Producer & Consumer
consumer = None
producer = None
consumer_task = None
consumer_status = {"running": False, "error": None}

# Asset file storage path
ASSET_FOLDER = "./asset"

# Store active clients for SSE
event_clients = set()

async def get_kafka_producer():
    global producer
    if producer is None:
        producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BROKER)
        await producer.start()
    return producer

async def consume_kafka():
    global consumer, consumer_status

    while True:
        try:
            consumer = AIOKafkaConsumer(
                VALIDATED_TOPIC,
                bootstrap_servers=KAFKA_BROKER,
                auto_offset_reset="earliest",
                enable_auto_commit=False,
                group_id="loan_evaluation_service",
            )

            await consumer.start()
            consumer_status["running"] = True
            consumer_status["error"] = None
            logger.info("Kafka consumer started successfully")

            async for msg in consumer:
                data = json.loads(msg.value.decode("utf-8"))
                logger.info(f"Received validated loan request: {data}")

                try:
                    await evaluate_loan(data)
                    await consumer.commit()
                    logger.info(f"Committed offset for message: {msg.offset}")

                except Exception as e:
                    logger.error(f"Error during evaluation, message NOT committed: {str(e)}")

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

async def evaluate_loan(data):
    id_number = data["id_number"]
    annual_income = data["annual_income"]
    debt = data["debt"]
    assets = data["assets"]
    loan_amount = data["loan_amount"]

    # 计算 max_loan
    max_loan = (annual_income * 5) - debt + (assets * 0.5)
    data["max_loan"] = max_loan

    # 保存到 dataset 文件夹
    dataset_folder = "./dataset"
    os.makedirs(dataset_folder, exist_ok=True)
    dataset_file = os.path.join(dataset_folder, f"{id_number}.json")
    with open(dataset_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ Data stored to dataset: {dataset_file}")

    # 判定是否接受贷款
    if loan_amount <= max_loan:
        producer = await get_kafka_producer()
        await producer.send_and_wait(ACCEPTED_TOPIC, json.dumps(data, ensure_ascii=False).encode("utf-8"))
        logger.info(f"✅ Loan request accepted and sent to {ACCEPTED_TOPIC}")
        result = {"id_number": id_number, "status": "accepted", "max_loan": max_loan}
    else:
        result = {
            "id_number": id_number,
            "status": "rejected",
            "reason": f"Requested {loan_amount} exceeds maximum allowable loan {max_loan}"
        }
        await send_rejection_email(data["email"], data["name"], loan_amount, max_loan)
        logger.info(f"❌ Loan request rejected for ID {id_number}")

    await send_sse_event(json.dumps(result))

async def send_rejection_email(recipient_email, name, requested, maximum):
    print(f"GMAIL_USER = {GMAIL_USER}")
    print(f"GMAIL_PASS = {'OK' if GMAIL_PASS else 'None'}")
    try:
        msg = MIMEMultipart()
        msg["From"] = formataddr(("Loan Service", GMAIL_USER))
        msg["To"] = recipient_email
        msg["Subject"] = "[Loan Application] Request Rejected"

        body = f"""
Bonjour {name},

Nous avons bien reçu votre demande de prêt de {requested} euros.
Cependant, après évaluation de votre profil, le montant maximum auquel vous êtes éligible est de {maximum} euros.

Nous sommes désolés de ne pas pouvoir répondre favorablement à votre demande actuelle.

Cordialement,
L’équipe de service des prêts
"""
        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, recipient_email, msg.as_string())
        server.quit()
        logger.info(f"Rejection email sent to {recipient_email}")

    except Exception as e:
        logger.error(f"Failed to send rejection email: {str(e)}")

@app.get("/health/")
def health_check():
    return {"status": "running", "kafka_consumer": consumer_status}

@app.get("/events/")
async def event_stream():
    async def event_generator():
        queue = asyncio.Queue()
        event_clients.add(queue)

        try:
            while True:
                event_data = await queue.get()
                yield f"data: {event_data}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            event_clients.remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

async def send_sse_event(data: str):
    for queue in event_clients:
        await queue.put(data)

@app.on_event("startup")
async def startup_event():
    global consumer_task
    try:
        consumer_task = asyncio.create_task(consume_kafka())
        logger.info("Loan Evaluation Service started successfully")
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")
        raise

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
