import requests

def fetch_dynamic(url):
	response = requests.get(url)
	response.raise_for_status()
	return response.text

html = fetch_dynamic("https://portaldecompras.fiesc.com.br/Portal/Mural.aspx")
print(html[:10000])  # mostra os primeiros 1000 caracteres
