import requests

TOKEN = "8071395009:AAH-7P6Cys3hncbQdaJYB2paoK7sVeh884s"
url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"

resp = requests.get(url).json()
print("hello world")
print(resp)



#TELEGRAM_TOKEN = "8145377930:AAHQC83rZtxg0KD7kqzhIJCqr4RUpSRdeI8"
#TELEGRAM_CHAT_ID = "-4966623716"