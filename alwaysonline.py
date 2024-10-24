#!/usr/bin/python3
#
# alwaysonline.py
# Always Online implementation for Caterpillar Proxy
#
# Caterpillar Proxy - The simple web debugging proxy (formerly, php-httpproxy)
# Namyheon Go (Catswords Research) <gnh1201@gmail.com>
# https://github.com/gnh1201/caterpillar
# Created at: 2024-07-31
# Updated at: 2024-10-25
#
import re
import socket
import ssl
import requests
from decouple import config
from elasticsearch import Elasticsearch, NotFoundError
import hashlib
from datetime import datetime, UTC
from base import Extension, Logger

logger = Logger(name="wayback")

try:
    client_encoding = config("CLIENT_ENCODING")
    es_host = config("ES_HOST")
    es_index = config("ES_INDEX")
    librey_url = config("LIBREY_URL", default="https://serp.catswords.net")
    chatgpt_apikey = config("CHATGPT_APIKEY")
except Exception as e:
    logger.error("[*] Invalid configuration", exc_info=e)

es = Elasticsearch([es_host])

def generate_id(url: str):
    """Generate a unique ID for a URL by hashing it."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def fetch_cache_from_internet_archive(url: str):
    status_code, content = (0, b"")

    # Wayback Machine API URL
    wayback_api_url = "http://archive.org/wayback/available?url=" + url

    # Send a GET request to Wayback Machine API
    response = requests.get(wayback_api_url)

    # Check if the request was successful (status code 200)
    if response.status_code == 200:
        try:
            # Parse JSON response
            data = response.json()
            archived_snapshots = data.get("archived_snapshots", {})
            closest_snapshot = archived_snapshots.get("closest", {})

            # Check if the URL is available in the archive
            if closest_snapshot:
                archived_url = closest_snapshot.get("url", "")

                # If URL is available, fetch the content of the archived page
                if archived_url:
                    archived_page_response = requests.get(archived_url)
                    status_code = archived_page_response.status_code
                    if status_code == 200:
                        content = archived_page_response.content
                else:
                    status_code = 404
            else:
                status_code = 404
        except:
            status_code = 502
    else:
        status_code = response.status_code

    return status_code, content


def fetch_cache_from_elasticsearch(url: str):
    url_id = generate_id(url)
    try:
        result = es.get(index=es_index, id=url_id)
        logger.info(result["_source"])
        return 200, result["_source"]["content"].encode(client_encoding)
    except NotFoundError:
        return 404, b""
    except Exception as e:
        logger.error(f"Error fetching from Elasticsearch: {e}")
        return 502, b""


def push_cache_to_elasticsearch(url: str, data: bytes):
    url_id = generate_id(url)
    timestamp = datetime.now(UTC).timestamp()
    try:
        es.index(
            index=es_index,
            id=url_id,
            body={
                "url": url,
                "content": data.decode(client_encoding),
                "timestamp": timestamp,
            },
        )
    except Exception as e:
        logger.error(f"Error caching to Elasticsearch: {e}")


def fetch_origin_server(url: str):
    try:
        response = requests.get(url)
        return response.status_code, response.content
    except Exception as e:
        return 502, str(e).encode(client_encoding)


def query_to_serp(url: str):
    try:
        # Process both removal of http:// or https:// and replacement of special characters at once
        # ^https?:\/\/ removes http:// or https://, [^\w\s] removes special characters
        q = re.sub(r'^https?:\/\/|[^\w\s]', ' ', url)
`
        url = "%s/api.php?q=%s" % (librey_url, q)
        response = requests.get(url)
        if response.status_code != 200:
            return response.status_code, f"SERP API server returned status code {response.status_code}".encode(client_encoding)

        return 200, response.content
    except Exception as e:
        return 502, f"Error querying SERP API: {str(e)}".encode(client_encoding)


def query_to_llm(content: bytes):
    try:
        # ChatGPT API call
        headers = {
            "Authorization": f"Bearer {chatgpt_apikey}",
            "Content-Type": "application/json"
        }

        # Convert bytes to string
        content_str = content.decode(client_encoding)

        # Generate a prompt asking to infer the original user's search intent
        prompt = (
            "The following content was scraped from a search engine. Based on this data, "
            "please infer the most likely information the user was originally searching for "
            "and explain it as accurately as possible:\n\n"
            f"{content_str}"
        )

        data = {
            "model": "gpt-4",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]
        }

        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            json=data,
            headers=headers
        )

        if response.status_code == 200:
            response_data = response.json()
            llm_content = response_data['choices'][0]['message']['content']
            return 200, llm_content.encode(client_encoding)
        else:
            return response.status_code, f"ChatGPT API returned status code {response.status_code}".encode(client_encoding)

    except Exception as e:
        return 502, f"Error querying ChatGPT API: {str(e)}".encode(client_encoding)


class AlwaysOnline(Extension):
    def __init__(self):
        self.type = "connector"  # this is a connector
        self.connection_type = "alwaysonline"
        self.buffer_size = 8192

    def connect(self, conn: socket.socket, data: bytes, webserver: bytes, port: bytes, scheme: bytes, method: bytes, url: bytes):
        logger.info("[*] Connecting... Connecting...")

        connected = False

        is_ssl = scheme in [b"https", b"tls", b"ssl"]
        buffered = b""

        def sendall(_sock: socket.socket, _conn: socket.socket, _data: bytes):
            # send first chuck
            sock.send(_data)
            if len(_data) < self.buffer_size:
                return

            # send following chunks
            _conn.settimeout(1)
            while True:
                try:
                    chunk = _conn.recv(self.buffer_size)
                    if not chunk:
                        break
                    _sock.send(chunk)
                except:
                    break

        target_url = url.decode(client_encoding)
        target_scheme = scheme.decode(client_encoding)
        target_webserver = webserver.decode(client_encoding)

        if "://" not in target_url:
            target_url = f"{target_scheme}://{target_webserver}:{port}{target_url}"

        if method == b"GET":
            if not connected:
                logger.info("Trying get data from Elasticsearch...")
                status_code, content = fetch_cache_from_elasticsearch(target_url)
                if status_code == 200:
                    buffered += content
                    connected = True

            if not connected:
                logger.info("Trying get data from Wayback Machine...")
                status_code, content = fetch_cache_from_internet_archive(target_url)
                if status_code == 200:
                    buffered += content
                    connected = True

            if not connected:
                status_code, content = fetch_origin_server(target_url)
                if status_code == 200:
                    buffered += content
                    push_cache_to_elasticsearch(target_url, buffered)
                    connected = True

            if not connected:
                status_code, content = query_to_serp(target_url)
                if status_code == 200:
                    llm_status_code, llm_content = query_to_llm(content)
                    if status_code == 200:
                        buffered += llm_content
                    else:
                        buffered += content
                    connected = True

            conn.send(buffered)
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            if is_ssl:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE

                sock = context.wrap_socket(
                    sock, server_hostname=webserver.decode(client_encoding)
                )
                sock.connect((webserver, port))
                # sock.sendall(data)
                sendall(sock, conn, data)
            else:
                sock.connect((webserver, port))
                # sock.sendall(data)
                sendall(sock, conn, data)

        return connected
