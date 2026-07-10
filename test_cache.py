import requests
import time
import concurrent.futures

url = "http://localhost:8000/risk/hormuz"

def fetch():
    try:
        response = requests.get(url, timeout=5)
        return response.status_code, response.text
    except Exception as e:
        return 0, str(e)

print("Sending 20 rapid requests to /risk/hormuz to test caching...")
start = time.time()

with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    results = list(executor.map(lambda _: fetch(), range(20)))

end = time.time()

successes = sum(1 for status, _ in results if status == 200)
failures = [ (status, text) for status, text in results if status != 200 ]

print(f"Completed in {end - start:.2f} seconds.")
print(f"Successes: {successes}/20")
if failures:
    print(f"Failures: {failures[0]}") # just print the first failure

