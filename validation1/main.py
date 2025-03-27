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
            "content": ("""Vous êtes un assistant intelligent pour les prêts. Veuillez extraire les champs suivants à partir du langage naturel de l'utilisateur et les formater en JSON standard. Notez que l'utilisateur peut poser des questions en anglais, en français ou en chinois :
    - name : Nom, conservez tel quel.
    - gender : Sexe, homme remplissez "m", femme remplissez "f".
    - birth_date : Date de naissance, format "JJMMAAAA", par exemple, le 29 septembre 1999 → "29091999". Si la réponse de l'utilisateur ne respecte pas ce format, veuillez la convertir dans ce format.
    - id_number : Numéro d'identité, type numérique, longueur illimitée.
    - address : Adresse.
    - email : Adresse e-mail.
    - loan_type : Type de prêt, prêt immobilier remplissez "f", prêt automobile remplissez "c".
      Si l'utilisateur dit "Je veux acheter une maison", "Demander un prêt immobilier", "Prêt pour une maison", etc., reconnaissez automatiquement comme "f".
      Si l'utilisateur dit "Je veux acheter une voiture", "Demander un prêt automobile", "Prêt pour une voiture", reconnaissez comme "c".
    - loan_amount : Montant du prêt demandé (en unités monétaires).
    - assets : Montant des actifs (chiffres uniquement, en unités monétaires), si aucun actif, remplissez 0. Les dépôts, actions, fonds, etc., sont considérés comme des actifs. Si c'est un objet, comme une maison, demandez à l'utilisateur une estimation.
    - annual_income : Revenu annuel (chiffres uniquement, en unités monétaires).
    - debt : Montant de la dette (si aucune dette, remplissez 0).
    - duree : Durée du prêt, en mois. Convertissez automatiquement le temps mentionné par l'utilisateur en mois entiers, arrondissez au plus proche, par exemple, "trois ans" → 36 mois, "deux ans et demi" → 30 mois.
    - assurances : Vous devez demander à l'utilisateur s'il souhaite souscrire une assurance et l'informer que le prix de l'assurance est de 0,5 % du montant du prêt demandé. Si oui, remplissez cette ligne par True, sinon par False.
              
    Comprenez le langage ambigu et produisez un JSON complet. Une fois les informations collectées, informez l'utilisateur que la demande a été soumise.
    Ne posez pas de questions répétées sur les champs déjà fournis clairement par l'utilisateur. À chaque réponse, ne posez des questions que sur les informations manquantes, de préférence une à la fois.
    Utilisez un ton poli pour communiquer avec le client, guidez-le pour fournir les informations nécessaires, et interagissez avec lui en langage naturel. Une fois toutes les informations collectées, demandez à l'utilisateur de confirmer si les informations sont correctes, et soumettez-les uniquement après avoir reçu une réponse positive.""")
        })

    conversation_history[user_id].append({"role": "user", "content": user_message})

    current_data = user_collected_data.get(user_id, {})
    if current_data:
        collected_prompt = f"Les champs actuellement collectés sont les suivants : {json.dumps(current_data, ensure_ascii=False)}. Veuillez ne pas poser de questions répétées sur ces champs, mais uniquement sur les champs restants."
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
            logging.info(f"✅ Informations de prêt soumises avec succès : {loan_json}")

            natural_summary = f"Merci d'avoir soumis votre demande, voici les informations que nous avons enregistrées pour vous :\n"
            natural_summary += f"Nom : {current['name']}, Sexe : {'Homme' if current['gender']=='m' else 'Femme'}, Date de naissance : {current['birth_date']}, Numéro d'identité : {current['id_number']}.\n"
            natural_summary += f"Adresse : {current['address']}, Type de prêt : {'Prêt immobilier' if current['loan_type']=='f' else 'Prêt automobile'}, Montant demandé : {current['loan_amount']} unités monétaires.\n"
            natural_summary += f"Montant des actifs : {current['assets']} unités monétaires, Revenu annuel : {current['annual_income']} unités monétaires, Montant de la dette : {current['debt']} unités monétaires.\n"
            natural_summary += "✅ Votre demande de prêt a été soumise avec succès, nous vous contacterons dès que possible. Si vous souhaitez soumettre une nouvelle demande, vous pouvez continuer à remplir le formulaire."

            user_collected_data[user_id] = {}
            conversation_history[user_id] = []

            return {"reply": natural_summary}
        else:
            logging.info(f"ℹ️ L'utilisateur actuel {user_id} a fourni des informations partielles : {current}, champs manquants : {missing}")
            return {"reply": f"Vous n'avez pas encore fourni les informations suivantes : {', '.join(missing)}, veuillez les compléter."}

    logging.warning(f"⚠️ Impossible d'extraire le JSON de la réponse de l'IA. Réponse originale : {ai_reply}")
    return {"reply": ai_reply}

def extract_json(text: str):
    try:
        start = text.index('{')
        end = text.rindex('}') + 1
        json_part = text[start:end]
        return json.loads(json_part)
    except:
        return None

