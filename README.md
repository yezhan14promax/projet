# 💬 Système de demande de prêt intelligent piloté par l'IA

Ce projet est une plateforme de service de prêt intelligent basée sur une architecture de microservices et des grands modèles de langage (LLM). Les utilisateurs soumettent leur demande de prêt en interagissant avec un Chatbot, et le système procède automatiquement à la vérification, à l’évaluation, à la génération et à l’envoi du contrat.

---

## 🧰 Dépendances du système

- Python 3.9+
- Kafka + Zookeeper
- Redis
- Celery
- FastAPI
- Uvicorn
- Gmail SMTP (mot de passe spécifique)
- Clé API OpenAI

---

## 🚀 Guide de démarrage rapide

### 🔧 Environnement Linux
1. **Modifier la configuration**  
   Veuillez ajuster vos fichiers de configuration Kafka et Zookeeper (server.properties et zookeeper.properties) selon vos besoins.

2. **Démarrer Zookeeper**
   ```bash
   sudo bin/zookeeper-server-start.sh config/zookeeper.properties
   ```

3. **Démarrer Kafka**
   ```bash
   sudo bin/kafka-server-start.sh config/server.properties
   ```

4. **Créer les Topics Kafka**
   ```bash
   bin/kafka-topics.sh --create --topic validated_requests --bootstrap-server localhost:9092
   bin/kafka-topics.sh --create --topic acceptation --bootstrap-server localhost:9092
   bin/kafka-topics.sh --create --topic plan --bootstrap-server localhost:9092
   ```

5. **Démarrer Redis**
   ```bash
   sudo service redis-server start
   ```

---

### 🖥️ Environnement Windows

1. **Démarrer le Worker Celery**
   ```bash
   celery -A assurance3.celery_app worker --loglevel=info --pool=solo
   ```

2. **Optionnel : Démarrer Flower pour surveiller (localhost:5555)**
   ```bash
   celery -A assurance3.celery_app flower --port=5555
   ```

3. **Démarrer les quatre microservices**

   ```bash
   uvicorn validation1.main:app --reload --port 8001
   uvicorn evaluation2.main:app --reload --port 8002
   uvicorn assurance3.main:app --reload --port 8003
   uvicorn verification4.main:app --reload --port 8004
   ```

---

## 🧪 Tester les messages Kafka

Remplacez `172.20.225.146` par l’adresse IP privée de votre serveur Linux (vous pouvez l’obtenir avec la commande `hostname -I`) :

```bash
bin/kafka-console-consumer.sh --topic validated_requests --from-beginning --bootstrap-server 172.20.225.146:9092
bin/kafka-console-consumer.sh --topic acceptation --from-beginning --bootstrap-server 172.20.225.146:9092
bin/kafka-console-consumer.sh --topic plan --from-beginning --bootstrap-server 172.20.225.146:9092
```

---

## 🔑 Configuration de l'environnement (.env)

Créez un fichier `.env` à la racine du projet avec le contenu suivant :

```env
OPENAI_API_KEY=Votre_clé_openai
KAFKA_BROKER=votre_ip.146:9092
GMAIL_USER=Votre_adresse_email
GMAIL_PASS=Votre_mot_de_passe_spécifique
```

---

## 💬 Exemples de conversation utilisateur

Vous pouvez dialoguer naturellement avec le Chatbot ou copier-coller l’un des exemples suivants pour tester :

### ❌ Non éligible au prêt

```text
Je m'appelle Ye Zhan, homme, né le 9 septembre 1999, numéro d'identification 1234567890, adresse Versailles, je souhaite emprunter 8 000 000 pour un prêt automobile, actif total 500, revenu annuel 5 000, dette 8 000, je souhaite un prêt sur 36 mois et souscrire une assurance
```

### ✅ Éligible + Assurance souscrite

```text
Je m'appelle wangsongyang, homme, né le 9 septembre 1999, numéro de carte d'identité 1234, adresse Versailles, je souhaite emprunter 80 pour un prêt automobile, actif total 500, revenu annuel 5000, dette 0, je souhaite un prêt sur 36 mois et souscrire une assurance
```

### ✅ Éligible + Sans assurance

```text
Je m'appelle wangsongyang, homme, né le 9 septembre 1999, numéro de carte d'identité 5644869, adresse Versailles, je souhaite emprunter 80 pour un prêt automobile, actif total 500, revenu annuel 5000, dette 0, je souhaite un prêt sur 36 mois, pas d'assurance
```

---

## 📁 Stockage des données et contrats

- Les données des clients sont stockées dans le dossier `dataset/`, nommées avec le numéro d'identification, par exemple : `1234567890.json`
- Les contrats sont enregistrés dans les dossiers `contrat/pret/` et `contrat/assurance/`, nommés avec le numéro du contrat, par exemple : `987654321.txt`

---

## 🙋 Questions fréquentes

- **Erreur de connexion à Kafka ?**  
  Vérifiez que l’adresse IP et le port sont corrects, et que Zookeeper et Kafka sont bien démarrés.
- **Impossible d’envoyer des emails ?**  
  Assurez-vous que le fichier `.env` contient bien le mot de passe spécifique de Gmail.

---

## 📌 Points forts du projet

- Dialogue en langage naturel piloté par un LLM
- Communication asynchrone entre microservices via Kafka + Redis
- Génération automatique des contrats de prêt et d’assurance
- Notification via email et WebSocket

---

💡 *Vos retours et suggestions sont les bienvenus via Issues ou Pull Requests !*