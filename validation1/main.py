from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from openai import OpenAI
import os
import json
from pathlib import Path
from dotenv import load_dotenv
import asyncio
from aiokafka import AIOKafkaProducer
import logging

# Logging setup
logging.basicConfig(
    filename="loan_submission.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Load env
env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=env_path)

# Kafka setup
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
producer: AIOKafkaProducer = None

# Allowed Kafka topics
ALLOWED_TOPICS = {"validated_requests", "acceptation", "plan"}

# OpenAI client
client = OpenAI()

# FastAPI setup
app = FastAPI()
app.mount("/static", StaticFiles(directory="validation1/static"), name="static")

REQUIRED_FIELDS = [
    "name", "gender", "birth_date", "id_number",
    "address", "loan_type", "assets", "annual_income", "debt", "loan_amount"
]

conversation_history = {}
user_collected_data = {}

@app.on_event("startup")
async def startup_event():
    global producer
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BROKER)
    await producer.start()

@app.on_event("shutdown")
async def shutdown_event():
    if producer:
        await producer.stop()

@app.get("/", response_class=HTMLResponse)
async def get_chat():
    with open("validation1/static/index.html", encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), status_code=200)

class ChatRequest(BaseModel):
    user_id: str
    message: str
    topic: str = "validated_requests"

@app.post("/chat")
async def chat_endpoint(chat: ChatRequest):
    user_id = chat.user_id
    user_message = chat.message
    kafka_topic = chat.topic.strip()

    if kafka_topic not in ALLOWED_TOPICS:
        raise HTTPException(status_code=400, detail=f"非法的 Kafka topic: {kafka_topic}")

    if user_id not in conversation_history:
        conversation_history[user_id] = []
        user_collected_data[user_id] = {}

    if not any(msg['role'] == 'system' for msg in conversation_history[user_id]):
        conversation_history[user_id].insert(0, {
            "role": "system",
            "content": ("""你是一个智能贷款助理，请从用户的自然语言中提取以下字段，并用规范格式输出为 JSON，注意用户可能会用英语法语中文这三种语言问你：
- name：姓名，保留原样
- gender：性别，男填 \"m\"，女填 \"f\"
- birth_date：出生日期，格式为 \"DDMMYYYY\"，如 1999年9月29日 → \"29091999\"
- id_number：身份证号
- address：地址
- loan_type：贷款类型，房贷填 \"f\"，车贷填 \"c\"
  用户如果说“我要买房”、“申请房贷”、“房屋贷款”等同义词，应自动识别为 \"f\"；
  说“我要买车”、“申请车贷”、“车辆贷款”应识别为 \"c\"
- loan_amount：想要申请的贷款金额（单位元）
- assets：资产金额（纯数字，单位元），没有资产填 0，存款、股票、基金等都算资产。如果是物品，比如房子，你询问用户估价。
- annual_income：年收入（纯数字，单位元）
- debt：债务金额（没有债务填 0）
理解模糊语言并输出完整 JSON。当信息收集齐后，告诉用户申请已提交。
不要重复提问用户已经明确提供过的字段。每次回答时，只提问用户还未提供的信息，最好一次问一个。
注意用礼貌语气和客户交流，引导用户提供信息，用自然语言与客户交流。""")
        })

    conversation_history[user_id].append({"role": "user", "content": user_message})

    current_data = user_collected_data.get(user_id, {})
    if current_data:
        collected_prompt = f"当前已收集字段如下：{json.dumps(current_data, ensure_ascii=False)}，请不要重复提问这些字段，只提问剩余字段。"
        conversation_history[user_id].append({"role": "system", "content": collected_prompt})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=conversation_history[user_id],
        temperature=0.4
    )

    if current_data:
        conversation_history[user_id].pop()

    ai_reply = response.choices[0].message.content
    conversation_history[user_id].append({"role": "assistant", "content": ai_reply})

    json_data = extract_json(ai_reply)
    if json_data:
        user_collected_data[user_id].update(json_data)
        current = user_collected_data[user_id]
        missing = [f for f in REQUIRED_FIELDS if f not in current or current[f] in [None, ""]]

        if not missing:
            loan_json = json.dumps(current, ensure_ascii=False)
            await producer.send_and_wait(kafka_topic, loan_json.encode("utf-8"))
            logging.info(f"✅ 成功提交贷款信息：{loan_json}")

            natural_summary = f"感谢您提交申请，以下是我们为您记录的信息：\n"
            natural_summary += f"姓名：{current['name']}，性别：{'男' if current['gender']=='m' else '女'}，出生日期：{current['birth_date']}，身份证号：{current['id_number']}。\n"
            natural_summary += f"地址：{current['address']}，贷款类型：{'房贷' if current['loan_type']=='f' else '车贷'}，申请金额：{current['loan_amount']}元。\n"
            natural_summary += f"资产金额：{current['assets']}元，年收入：{current['annual_income']}元，债务金额：{current['debt']}元。\n"
            natural_summary += "✅ 您的贷款申请已成功提交，我们将尽快与您联系。如需提交新申请，您可以继续填写。"

            user_collected_data[user_id] = {}
            conversation_history[user_id] = []

            return {"reply": natural_summary}
        else:
            logging.info(f"ℹ️ 当前用户 {user_id} 已提供部分信息：{current}，缺失字段：{missing}")
            return {"reply": f"您还未提供以下信息：{', '.join(missing)}，请补充。"}

    logging.warning(f"⚠️ 无法从 AI 回复中提取 JSON。原始回复：{ai_reply}")
    return {"reply": ai_reply}

def extract_json(text: str):
    try:
        start = text.index('{')
        end = text.rindex('}') + 1
        json_part = text[start:end]
        return json.loads(json_part)
    except:
        return None

