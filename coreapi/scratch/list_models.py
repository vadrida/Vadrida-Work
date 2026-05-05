import requests

api_key = "AIzaSyB9m159uZTlWI-R75j3wRRsponZc16BOW4"
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
resp = requests.get(url)
print(resp.status_code)
print(resp.text)
