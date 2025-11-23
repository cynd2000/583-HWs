from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware #Necessary for POA chains
from datetime import datetime
import json
import pandas as pd


def connect_to(chain):
    if chain == 'source':  # The source contract chain is avax
        api_url = f"https://api.avax-test.network/ext/bc/C/rpc" #AVAX C-chain testnet

    if chain == 'destination':  # The destination contract chain is bsc
        api_url = f"https://data-seed-prebsc-1-s1.binance.org:8545/" #BSC testnet

    if chain in ['source','destination']:
        w3 = Web3(Web3.HTTPProvider(api_url))
        # inject the poa compatibility middleware to the innermost layer
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def get_contract_info(chain, contract_info):
    """
        Load the contract_info file into a dictionary
        This function is used by the autograder and will likely be useful to you
    """
    try:
        with open(contract_info, 'r')  as f:
            contracts = json.load(f)
    except Exception as e:
        print( f"Failed to read contract info\nPlease contact your instructor\n{e}" )
        return 0
    return contracts[chain]



def scan_blocks(chain, contract_info="contract_info.json"):
    """
        chain - (string) should be either "source" or "destination"
        Scan the last 5 blocks of the source and destination chains
        Look for 'Deposit' events on the source chain and 'Unwrap' events on the destination chain
        When Deposit events are found on the source chain, call the 'wrap' function the destination chain
        When Unwrap events are found on the destination chain, call the 'withdraw' function on the source chain
    """

    # This is different from Bridge IV where chain was "avax" or "bsc"
    if chain not in ['source','destination']:
        print( f"Invalid chain: {chain}" )
        return 0
    
        # 加载合约信息
    contracts = get_contract_info(chain, contract_info)
    if not contracts:
        return 0
    
    # 获取私钥
    warden_private_key = contracts['warden']['private_key']
    
    # 连接到两个网络
    source_w3 = connect_to('source')
    destination_w3 = connect_to('destination')
    
    # 创建账户
    warden_account = source_w3.eth.account.from_key(warden_private_key)
    
    # 获取合约地址和ABI
    source_address = contracts['source']['address']
    source_abi = contracts['source']['abi']
    
    destination_address = contracts['destination']['address']
    destination_abi = contracts['destination']['abi']
    
    # 创建合约实例
    source_contract = source_w3.eth.contract(address=source_address, abi=source_abi)
    destination_contract = destination_w3.eth.contract(address=destination_address, abi=destination_abi)
    
    # 扫描最近5个区块
    latest_block_source = source_w3.eth.block_number
    latest_block_destination = destination_w3.eth.block_number
    
    start_block_source = max(0, latest_block_source - 5)
    start_block_destination = max(0, latest_block_destination - 5)
    
    print(f"扫描源链区块 {start_block_source} 到 {latest_block_source}")
    print(f"扫描目标链区块 {start_block_destination} 到 {latest_block_destination}")
    
    # 1. 监听源链的Deposit事件，然后在目标链调用wrap
    deposit_events_found = 0
    unwrap_events_found = 0
    
    # 扫描源链的Deposit事件（基于listener.py的逻辑）
    try:
        if latest_block_source - start_block_source < 30:
            event_filter = source_contract.events.Deposit.create_filter(
                from_block=start_block_source, 
                to_block=latest_block_source
            )
            deposit_events = event_filter.get_all_entries()
        else:
            deposit_events = []
            for block_num in range(start_block_source, latest_block_source + 1):
                event_filter = source_contract.events.Deposit.create_filter(
                    from_block=block_num, 
                    to_block=block_num
                )
                deposit_events.extend(event_filter.get_all_entries())
        
        deposit_events_found = len(deposit_events)
        print(f"找到 {deposit_events_found} 个Deposit事件")
        
        for event in deposit_events:
            print(f"发现Deposit事件: token={event.args.token}, recipient={event.args.recipient}, amount={event.args.amount}")
            
            # 在目标链调用wrap函数
            try:
                wrap_tx = destination_contract.functions.wrap(
                    event.args.token,       # _underlying_token
                    event.args.recipient,   # _recipient  
                    event.args.amount       # _amount
                ).build_transaction({
                    'from': warden_account.address,
                    'nonce': destination_w3.eth.get_transaction_count(warden_account.address),
                    'gas': 200000,
                    'gasPrice': destination_w3.eth.gas_price
                })
                
                signed_wrap_tx = destination_w3.eth.account.sign_transaction(wrap_tx, warden_private_key)
                wrap_tx_hash = destination_w3.eth.send_raw_transaction(signed_wrap_tx.raw_transaction)
                wrap_receipt = destination_w3.eth.wait_for_transaction_receipt(wrap_tx_hash)
                
                if wrap_receipt.status == 1:
                    print(f"✅ 成功在目标链调用wrap: {wrap_tx_hash.hex()}")
                else:
                    print(f"❌ wrap调用失败")
                    
            except Exception as e:
                print(f"❌ 调用wrap失败: {e}")
                
    except Exception as e:
        print(f"❌ 获取Deposit事件失败: {e}")
    
    # 2. 监听目标链的Unwrap事件，然后在源链调用withdraw
    try:
        if latest_block_destination - start_block_destination < 30:
            event_filter = destination_contract.events.Unwrap.create_filter(
                from_block=start_block_destination, 
                to_block=latest_block_destination
            )
            unwrap_events = event_filter.get_all_entries()
        else:
            unwrap_events = []
            for block_num in range(start_block_destination, latest_block_destination + 1):
                event_filter = destination_contract.events.Unwrap.create_filter(
                    from_block=block_num, 
                    to_block=block_num
                )
                unwrap_events.extend(event_filter.get_all_entries())
        
        unwrap_events_found = len(unwrap_events)
        print(f"找到 {unwrap_events_found} 个Unwrap事件")
        
        for event in unwrap_events:
            print(f"发现Unwrap事件: underlying_token={event.args.underlying_token}, to={event.args.to}, amount={event.args.amount}")
            
            # 在源链调用withdraw函数
            try:
                withdraw_tx = source_contract.functions.withdraw(
                    event.args.underlying_token,  # _token
                    event.args.to,                # _recipient
                    event.args.amount             # _amount
                ).build_transaction({
                    'from': warden_account.address,
                    'nonce': source_w3.eth.get_transaction_count(warden_account.address),
                    'gas': 200000,
                    'gasPrice': source_w3.eth.gas_price
                })
                
                signed_withdraw_tx = source_w3.eth.account.sign_transaction(withdraw_tx, warden_private_key)
                withdraw_tx_hash = source_w3.eth.send_raw_transaction(signed_withdraw_tx.raw_transaction)
                withdraw_receipt = source_w3.eth.wait_for_transaction_receipt(withdraw_tx_hash)
                
                if withdraw_receipt.status == 1:
                    print(f"✅ 成功在源链调用withdraw: {withdraw_tx_hash.hex()}")
                else:
                    print(f"❌ withdraw调用失败")
                    
            except Exception as e:
                print(f"❌ 调用withdraw失败: {e}")
                
    except Exception as e:
        print(f"❌ 获取Unwrap事件失败: {e}")
    
    print(f"处理完成: {deposit_events_found} 个Deposit事件, {unwrap_events_found} 个Unwrap事件")
    return 1
