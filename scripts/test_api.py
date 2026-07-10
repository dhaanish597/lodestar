import requests
import time

start = time.time()
try:
    resp = requests.get('http://localhost:8000/risk/hormuz', timeout=20)
    print("RISK:", resp.text)
except Exception as e:
    print("RISK Error:", e)
print("Time taken:", time.time() - start)
