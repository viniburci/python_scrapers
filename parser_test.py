import requests

def fetch_dynamic(url):
	response = requests.get(url)
	response.raise_for_status()
	return response.text

html = fetch_dynamic("https://www.sanesul.ms.gov.br/licitacao/tipolicitacao/licitacao")
print(html[:1000])  # mostra os primeiros 1000 caracteres
