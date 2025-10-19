import requests
import json
import io

PINATA_API_KEY = "b1c8c5542c984e1c5ff4"
PINATA_API_SECRET = "cb692f00a1d60f0979e796b51386d2371bd1ae21ae497659e7eca0d71bc38f9b"

def pin_to_ipfs(data):
	assert isinstance(data,dict), f"Error pin_to_ipfs expects a dictionary"
	json_bytes = io.BytesIO(json.dumps(data).encode("utf-8"))

	headers = {
		"pinata_api_key": PINATA_API_KEY,
		"pinata_secret_api_key": PINATA_API_SECRET
	}
	
	r = requests.get("https://api.pinata.cloud/data/testAuthentication", headers=headers)
	print(r.status_code, r.text)
	
	response = requests.post(
		"https://api.pinata.cloud/pinning/pinJSONToIPFS", files={"file": ("data.json", json_bytes)}, headers=headers
	)

	response.raise_for_status()
	result = response.json()

	cid = result["Hash"]
	return cid


def get_from_ipfs(cid,content_type="json"):
	assert isinstance(cid,str), f"get_from_ipfs accepts a cid in the form of a string"

	url = f"https://gateway.pinata.cloud/ipfs/{cid}"
	response = requests.get(url)

	response.raise_for_status()
	data = response.json()

	assert isinstance(data,dict), f"get_from_ipfs should return a dict"
	return data
