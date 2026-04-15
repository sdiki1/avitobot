import time
import requests

PROXY_URL = "http://JYcALk:x7FhGB@185.60.44.112:3132"
PROXIES = {
    "http": PROXY_URL,
    "https": PROXY_URL,
}

TEST_URLS = [
    ("IP check", "https://httpbin.org/ip"),
    ("Avito", "https://www.avito.ru/"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

def check_proxy():
    for name, url in TEST_URLS:
        t0 = time.perf_counter()
        try:
            resp = requests.get(
                url,
                headers=HEADERS,
                proxies=PROXIES,
                timeout=20,
                allow_redirects=True,
            )
            dt = time.perf_counter() - t0
            print(f"[OK] {name}: status={resp.status_code}, time={dt:.2f}s, final_url={resp.url}")
            if "httpbin.org/ip" in url:
                print("     body:", resp.text.strip())
        except requests.RequestException as e:
            dt = time.perf_counter() - t0
            print(f"[ERR] {name}: {e} (time={dt:.2f}s)")

if __name__ == "__main__":
    check_proxy()
