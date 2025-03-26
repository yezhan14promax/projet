from .celery_app import celery_app
import asyncio
import json
from aiokafka import AIOKafkaProducer
import logging
import os
from datetime import datetime
import random
from pathlib import Path

# Kafka 配置
KAFKA_BROKER = "localhost:9092"
KAFKA_TOPIC = "plan"

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 设置路径（自动获取项目根目录）
PRET_PATH = Path("contrat/pret")
ASSURANCE_PATH = Path("contrat/assurance")

# 确保目录存在
PRET_PATH.mkdir(parents=True, exist_ok=True)
ASSURANCE_PATH.mkdir(parents=True, exist_ok=True)

# 异步发送 Kafka 消息
async def send_to_kafka(message):
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

    logger.info(f"[Celery] Processing loan data: {data}")

    # 提取关键信息
    name = data.get("name")
    id_number = data.get("id_number")
    email = data.get("email", "")
    address = data.get("address", "")
    loan_type = data.get("loan_type")  # 'f' or 'c'
    usage = "achat d'une maison" if loan_type == "f" else "achat d'une voiture"
    amount = data.get("loan_amount")
    duration = data.get("duree", 12)  # 默认贷款期限 12 个月

    now = datetime.now()
    today_str = now.strftime("%d/%m/%Y")

    # ✅ 生成贷款合同
    num_pret = str(random.randint(10**17, 10**18 - 1))
    contrat_pret = f"""Contrat de prêt 
Numéro du contrat : {num_pret}
Prêteur (Partie A) : {name}
Numéro d'identité : {id_number}
Coordonnées : {email}
Adresse : {address}
Emprunteur (Partie B) : chatbot
Étant donné que la Partie B a besoin d'un prêt pour {usage}, elle a demandé un prêt à la Partie A, qui a accepté de lui en fournir un. Afin de clarifier les droits et obligations des deux parties, elles ont conclu le présent contrat par consensus mutuel.
I. Montant du prêt
La Partie A accepte de fournir un prêt de {amount} euros à la Partie B.
II. Usage du prêt
Ce prêt sera utilisé pour {usage}. Sans l'accord écrit de la Partie A, la Partie B ne peut utiliser le prêt à d'autres fins.
III. Durée du prêt
La durée du prêt est de {duration} mois.
IV. Taux d'intérêt et mode de paiement des intérêts
Le taux d'intérêt annuel de ce prêt est de 1 %, calculé mensuellement.
Le mode de paiement des intérêts est le remboursement égal des intérêts et du capital.
V. Mode de remboursement
La Partie B doit rembourser le prêt selon le mode suivant : remboursement égal des intérêts et du capital.
La Partie B doit déposer les fonds de remboursement sur le compte désigné par la Partie A.
VI. Responsabilité en cas de violation du contrat
Si la Partie B n'utilise pas le prêt conformément à l'usage prévu, la Partie A a le droit de demander le remboursement anticipé du prêt et de réclamer une indemnité pour violation de contrat.
Si la Partie B rembourse le prêt en retard, la Partie A a le droit d'exiger des pénalités de retard.
Si la Partie A ne fournit pas le prêt conformément à l'accord, elle doit assumer la responsabilité de la violation du contrat.
VII. Résolution des litiges
Les litiges survenant lors de l'exécution du présent contrat doivent être résolus par négociation amiable entre les deux parties. En cas d'échec des négociations, une action en justice peut être intentée devant le tribunal populaire local où se trouve la Partie A.
VIII. Autres dispositions
Le présent contrat prend effet à partir de la date de signature ou de la signature au sceau des deux parties et se termine à la date de remboursement intégral du prêt et des intérêts.
Le présent contrat est établi en deux exemplaires, chacune des parties en conserve un, ayant la même force juridique.
Partie A (signature ou signature au sceau) : {name}
Date : {today_str}
Partie B (signature ou signature au sceau) : chatbot
Date : {today_str}
"""

    pret_path = PRET_PATH / f"{num_pret}.txt"
    with open(pret_path, "w", encoding="utf-8") as f:
        f.write(contrat_pret)
    logger.info(f"✅ Loan contract saved to: {pret_path}")

    data["num_pret"] = num_pret

    # ✅ 如果需要保险
    if data.get("assurances"):
        num_assurance = str(random.randint(10**9, 10**10 - 1))
        prime = round(amount * 0.01, 2)

        contrat_assurance = f"""Contrat d'assurance
Numéro du contrat : {num_assurance}
Assuré (Partie A) : {name}
Numéro d'identité : {id_number}
Coordonnées : {email}
Adresse : {address}
Assureur (Partie B) : chatbot
Étant donné que la Partie A souhaite souscrire une assurance pour un prêt à l'{usage}, la Partie B accepte de fournir les services d'assurance conformément aux dispositions du présent contrat. Les deux parties concluent le présent contrat par consensus mutuel.
I. Montant de l'assurance
Le montant de l'assurance est de {amount} euros.
II. Durée de l'assurance
La période de validité de l'assurance est de {duration} mois.
III. Prime d'assurance
La prime d'assurance que la Partie A doit payer est de {prime} euros.
IV. Clause d'exclusion de responsabilité
La Partie B n'assume pas la responsabilité d'assurance dans les cas suivants :
Les pertes causées par des actes intentionnels de la Partie A ;
Les pertes causées par des événements de force majeure.
V. Procédure de sinistre
En cas de sinistre, la Partie A doit notifier la Partie B dans les 90 jours et fournir les documents de preuve pertinents.
La Partie B doit examiner la demande de sinistre dans les 90 jours ouvrables après réception et indemniser conformément aux dispositions du contrat.
VI. Responsabilité en cas de violation du contrat
Si la Partie A ne paie pas la prime d'assurance à temps, la Partie B a le droit de résilier le contrat.
Si la Partie B ne procède pas à l'indemnisation à temps, elle doit assumer la responsabilité de la violation du contrat.
VII. Résolution des litiges
Les litiges survenant lors de l'exécution du présent contrat doivent être résolus par négociation amiable entre les deux parties. En cas d'échec des négociations, une action en justice peut être intentée devant le tribunal compétent du lieu où se trouve la Partie B.
VIII. Autres dispositions
Le présent contrat prend effet à partir de la date de signature ou de la signature au sceau des deux parties et se termine à l'expiration de la période d'assurance.
Le présent contrat est établi en deux exemplaires, chacune des parties en conserve un, ayant la même force juridique.
Partie A (signature ou signature au sceau) : {name}
Date : {today_str}
Partie B (signature ou signature au sceau) : chatbot
Date : {today_str}
"""
        assurance_path = ASSURANCE_PATH / f"{num_assurance}.txt"
        with open(assurance_path, "w", encoding="utf-8") as f:
            f.write(contrat_assurance)
        logger.info(f"✅ Assurance contract saved to: {assurance_path}")
        data["num_assurance"] = num_assurance
    else:
        data["num_assurance"] = None

    # ✅ 保存数据副本到 dataset 文件夹
    dataset_path = Path("dataset")
    dataset_path.mkdir(parents=True, exist_ok=True)
    dataset_file = dataset_path / f"{id_number}.json"
    with open(dataset_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"📁 Data record saved to: {dataset_file}")

    # ✅ 推送消息到 Kafka
    asyncio.run(send_to_kafka(data))
    return {
        "status": "success",
        "message": "Contracts created, saved, and sent to Kafka",
        "data": data
    }
