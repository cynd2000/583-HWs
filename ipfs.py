import requests
import json

def pin_to_ipfs(data):
	assert isinstance(data,dict), f"Error pin_to_ipfs expects a dictionary"
	json_data = json.dumps(data)

	response = requests.post(
		"https://ipfs.infura.io:5001/api/v0/add", files={"file": ("data.json", json_data)}  
	)

	response.raise_for_status()
	result = response.json()

	cid = result["Hash"]
	return cid


def get_from_ipfs(cid,content_type="json"):
	assert isinstance(cid,str), f"get_from_ipfs accepts a cid in the form of a string"

	response = requests.post(
		"https://ipfs.infura.io:5001/api/v0/cat", params={"arg": cid}}  
	)

	response.raise_for_status()
	data = response.json()

	assert isinstance(data,dict), f"get_from_ipfs should return a dict"
	return data
