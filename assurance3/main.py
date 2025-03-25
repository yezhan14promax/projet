import os
import json
import asyncio
import logging
from fastapi import FastAPI
from aiokafka import AIOKafkaConsumer
from assurance3.tasks import process_plan_task

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# FastAPI application
app = FastAPI(title="Loan Plan Service")

# Kafka configuration
KAFKA_BROKER = "172.20.225.146:9092"
ACCEPTED_TOPIC = "acceptation"

# Kafka Consumer
consumer = None
consumer_task = None
consumer_status = {"running": False, "error": None}


async def consume_kafka():
    """Kafka consumer listens to `acceptation` topic"""
    global consumer, consumer_status

    while True:
        try:
            consumer = AIOKafkaConsumer(
                ACCEPTED_TOPIC,
                bootstrap_servers=KAFKA_BROKER,
                auto_offset_reset="earliest",
                enable_auto_commit=False,
                group_id="loan_plan_service",
            )

            await consumer.start()
            consumer_status["running"] = True
            consumer_status["error"] = None
            logger.info("Kafka consumer started successfully")

            async for msg in consumer:
                try:
                    data = json.loads(msg.value.decode("utf-8"))

                    if not isinstance(data, dict):
                        logger.error(f"Invalid message format from Kafka: {data}")
                        continue

                    logger.info(f"Received approved loan: {data}")

                    # ✅ 使用 apply_async + kwargs
                    process_plan_task.apply_async(kwargs={"data": data})

                    await consumer.commit()
                    logger.info(f"Committed offset for message: {msg.offset}")

                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON message received from Kafka: {msg.value}")
                except Exception as e:
                    logger.error(f"Error processing Kafka message: {str(e)}")

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


@app.on_event("startup")
async def startup_event():
    """Start Kafka consumer when application starts"""
    global consumer_task
    consumer_task = asyncio.create_task(consume_kafka())


@app.get("/health/")
def health_check():
    """API endpoint to check Kafka consumer status"""
    return {"status": "running", "kafka_consumer": consumer_status}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)


    # sudo service redis-server start
    # celery -A assurance.celery_app worker --loglevel=info --pool=solo
    # celery -A assurance.celery_app flower --port=5555
    # bin/kafka-topics.sh --create --topic plan --bootstrap-server localhost:9092
    # E:\anaconda3\python.exe f:/DataScale/OP/BPMN/projet/3_assurance/main.py
    # http://localhost:5555/