import os
import json
import asyncio
import logging
from fastapi import FastAPI
from datetime import datetime
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi.responses import StreamingResponse

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# FastAPI application
app = FastAPI(title="Loan Evaluation Service")

# Kafka Configuration
KAFKA_BROKER = "172.20.225.146:9092"  # os.getenv("kafka:9092")  # Supports Docker
VALIDATED_TOPIC = "validated_requests"
ACCEPTED_TOPIC = "acceptation"

# Kafka Producer & Consumer
consumer = None
producer = None
consumer_task = None
consumer_status = {"running": False, "error": None}

# Asset file storage path
ASSET_FOLDER = "./asset"  # os.getenv("/app/asset")  # Supports Docker

# Store active clients for SSE
event_clients = set()


async def get_kafka_producer():
    """Get or create a Kafka producer instance"""
    global producer
    if producer is None:
        producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BROKER)
        await producer.start()
    return producer


async def consume_kafka():
    """Kafka consumer that listens to the 'validated_requests' topic with manual offset commit"""
    global consumer, consumer_status

    while True:  # Auto-reconnect if Kafka disconnects
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
                    await aggregate_evaluation(data)
                    await consumer.commit()  # Commit offset only if no error
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


async def aggregate_evaluation(data):
    """Aggregates asset and risk evaluation results."""
    loan_id = data["id"]
    amount = data["amount"]
    repayment_date = data["repayment_date"]

    try:
        asset_result, risk_result = await asyncio.gather(
            evaluate_asset(loan_id),
            evaluate_risk(amount, repayment_date)
        )

        if asset_result and risk_result:
            producer = await get_kafka_producer()
            await producer.send(ACCEPTED_TOPIC, json.dumps(data).encode("utf-8"))
            logger.info(f"Loan request {loan_id} accepted and sent to {ACCEPTED_TOPIC}")

            result = {"loan_id": loan_id, "status": "accepted"}
        else:
            reasons = []
            if not asset_result:
                reasons.append("Asset evaluation failed")
            if not risk_result:
                reasons.append("Risk evaluation failed")

            logger.info(f"Loan request {loan_id} rejected: {', '.join(reasons)}")
            result = {"loan_id": loan_id, "status": "rejected", "reasons": reasons}

        # Send result to SSE clients
        await send_sse_event(json.dumps(result))

    except Exception as e:
        logger.error(f"Error in loan evaluation: {str(e)}")
        raise


async def evaluate_risk(amount: float, repayment_date: str) -> bool:
    """Simulates risk evaluation"""
    await asyncio.sleep(1)
    repayment_dt = datetime.strptime(repayment_date, "%Y-%m-%d")
    return amount < 5000 and (repayment_dt - datetime.today()).days <= 365


async def evaluate_asset(loan_id: int) -> bool:
    """Evaluate asset based on stored file data."""
    asset_file = os.path.join(ASSET_FOLDER, f"{loan_id}.json")

    if not os.path.exists(asset_file):
        logger.error(f"Asset data for loan ID {loan_id} not found.")
        raise FileNotFoundError(f"Asset file {asset_file} not found")

    try:
        with open(asset_file, "r") as f:
            asset_data = json.load(f)

        return asset_data["credit_score"] > 650 and asset_data["total_assets"] > asset_data["liabilities"]

    except Exception as e:
        logger.error(f"Error reading asset file {asset_file}: {str(e)}")
        raise


@app.get("/health/")
def health_check():
    """API endpoint to check Kafka consumer status"""
    return {"status": "running", "kafka_consumer": consumer_status}


@app.get("/events/")
async def event_stream():
    """SSE endpoint to stream loan evaluation results"""
    async def event_generator():
        """Generate server-sent events for each new evaluation result"""
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
    """Broadcasts data to all SSE clients"""
    for queue in event_clients:
        await queue.put(data)


@app.on_event("startup")
async def startup_event():
    """Automatically starts the Kafka consumer when the application starts"""
    global consumer_task
    try:
        consumer_task = asyncio.create_task(consume_kafka())
        logger.info("Loan Evaluation Service started successfully")
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")
        raise


# Run FastAPI application
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)


    # E:\anaconda3\python.exe f:/DataScale/OP/BPMN/projet/2_evaluation/main.py
    # bin/kafka-topics.sh --create --topic acceptation --bootstrap-server localhost:9092
    # bin/kafka-console-consumer.sh --topic acceptation --from-beginning --bootstrap-server 172.20.225.146:9092