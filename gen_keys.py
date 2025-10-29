from web3 import Web3
from eth_account.messages import encode_defunct
import eth_account
from eth_account import Account
import os


Verifying signatures
To verify a signature, you can use
eth_account.Account.recover_message()
or w3.eth.account.recover_message(), which has the same syntax
Assignment
Modify the file gen_keys.py to complete the function "get_keys()"
The autograder will call get_keys() with a random challenge. Your function must sign the challenge, and return the signature as well as the address associated with the signature.
The autograder will check two things:
Does the signature verify using the address provided?
Does the address provided have a nonzero token balance on both BSC and Avalanche?


def sign_message(challenge, filename="secret_key.txt"):
    """
    challenge - byte string
    filename - filename of the file that contains your account secret key
    To pass the tests, your signature must verify, and the account you use
    must have testnet funds on both the bsc and avalanche test networks.
    """
    # This code will read your "sk.txt" file
    # If the file is empty, it will raise an exception
    with open(filename, "r") as f:
        key = f.readlines()
    assert(len(key) > 0), "Your account secret_key.txt is empty"

    private_key = key[0].strip()
    w3 = Web3()
    message = encode_defunct(challenge)

    # TODO recover your account information for your private key and sign the given challenge
    # Use the code from the signatures assignment to sign the given challenge
    account = Account.from_key(private_key)
    signed_message = account.sign_message(message)
    eth_addr = account.address

    assert Account.recover_message(message,signature=signed_message.signature) == eth_addr, f"Failed to sign message properly"

    #return signed_message, account associated with the private key
    return signed_message, eth_addr


if __name__ == "__main__":
    for i in range(4):
        challenge = os.urandom(64)
        sig, addr= sign_message(challenge=challenge)
        print( addr )


