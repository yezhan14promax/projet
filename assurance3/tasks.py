from .celery_app import celery_app
import asyncio
import json
from aiokafka import AIOKafkaProducer
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Kafka 配置
KAFKA_BROKER = "localhost:9092"
KAFKA_TOPIC = "plan"

# 发送 Kafka 消息（异步）
async def send_to_kafka(message):
    """异步发送消息到 Kafka"""
    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        value_serializer=lambda v: json.dumps(v).encode("utf-8")
    )
    await producer.start()
    try:
        logger.info(f"[Kafka] Sending message: {message}")
        await producer.send(KAFKA_TOPIC, message)
    finally:
        await producer.stop()

@celery_app.task(name="tasks.process_plan_task", bind=True)
def process_plan_task(self, *args, **kwargs):
    logger.info(f"[DEBUG] Received task args: {args}, kwargs: {kwargs}")

    data = kwargs.get("data", args[0] if args else None)

    if not data:
        raise ValueError("Missing required parameter: data")

    logger.info(f"[Celery] Processing data: {data}")


    # ✅ 发送到 Kafka 的 "plan" topic
    asyncio.run(send_to_kafka(data))

    return {"status": "success", "processed_data": data}

