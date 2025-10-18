import requests
import json

PINATA_API_KEY = "4b5abe769c0043a1c92c"
PINATA_API_SECRET = "89d3118f2dd90d867235ec423cc94e274789dcc0add5c3cce4c5bdc9255c8e71"

def pin_to_ipfs(data):
	assert isinstance(data,dict), f"Error pin_to_ipfs expects a dictionary"
	json_data = json.dumps(data)

	headers = {
		"pinata_api_key": PINATA_API_KEY,
		"pinata_secret_api_key": PINATA_API_SECRET
	}
	
	response = requests.post(
		"https://api.pinata.cloud/pinning/pinFileToIPFS", files={"file": ("data.json", json_data), headers=headers}  
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
