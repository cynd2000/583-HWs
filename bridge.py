# bridge.py
from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware
from datetime import datetime
import json
import pandas as pd
import time
import csv


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
    print(f"🔍 Scanning blocks on {chain} chain using {contract_info}")
    
    # 连接到对应链
    w3 = connect_to(chain)
    
    # 获取合约信息
    contract_data = get_contract_info(chain, contract_info)
    if not contract_data:
        print(f"❌ Failed to get contract info for {chain}")
        return []
    
    contract_address = contract_data['address']
    contract_abi = contract_data['abi']
    
    # 创建合约实例
    contract = w3.eth.contract(address=contract_address, abi=contract_abi)
    
    # 获取当前区块
    current_block = w3.eth.block_number
    from_block = max(0, current_block - 5)  # 扫描最近5个区块
    to_block = current_block
    
    print(f"   Contract: {contract_address}")
    print(f"   Scanning blocks: {from_block} to {to_block}")
    
    # 根据链选择要监听的事件
    if chain == 'source':
        event_name = 'Deposit'
    elif chain == 'destination':
        event_name = 'Unwrap'
    else:
        print(f"❌ Unknown chain: {chain}")
        return []
    
    all_events = []
    
    try:
        # 获取事件对象
        event_obj = getattr(contract.events, event_name)
        
        # 使用与Assignment IV兼容的方法扫描事件
        # 分批扫描，每次最多30个区块
        batch_size = 30
        current_scan_block = from_block
        
        while current_scan_block <= to_block:
            batch_end = min(current_scan_block + batch_size - 1, to_block)
            
            if batch_end == current_scan_block:
                print(f"   Scanning block {current_scan_block}...")
            else:
                print(f"   Scanning blocks {current_scan_block}-{batch_end}...")
            
            try:
                # 使用create_filter方法（与Assignment IV兼容）
                event_filter = event_obj.create_filter(
                    from_block=current_scan_block,
                    to_block=batch_end,
                    argument_filters={}
                )
                events = event_filter.get_all_entries()
                
                for ev in events:
                    formatted_event = {
                        'blockNumber': ev['blockNumber'],
                        'transactionHash': ev['transactionHash'].hex(),
                        'address': ev['address'],
                        'args': dict(ev['args']),
                        'event': event_name,
                        'chain': chain
                    }
                    all_events.append(formatted_event)
                
                if events:
                    print(f"      Found {len(events)} events")
                
            except Exception as e:
                print(f"      Error scanning blocks {current_scan_block}-{batch_end}: {e}")
                # 如果失败，尝试更小的批次
                if batch_size > 5:
                    batch_size = batch_size // 2
                    continue
            
            current_scan_block = batch_end + 1
        
        print(f"✅ Found {len(all_events)} {event_name} events in total")
        
        # 处理事件（调用相应的函数）
        process_events(chain, all_events, contract_info)
        
    except Exception as e:
        print(f"❌ Error scanning events: {e}")
        import traceback
        traceback.print_exc()
    
    return all_events

    
def process_events(chain, events, contract_info="contract_info.json"):
    """
    处理扫描到的事件，调用相应的跨链函数
    """
    if not events:
        return
    
    # 加载合约信息
    source_contract_data = get_contract_info('source', contract_info)
    destination_contract_data = get_contract_info('destination', contract_info)
    
    if not source_contract_data or not destination_contract_data:
        print("❌ Failed to load contract info")
        return
    
    # 连接到两个链
    source_w3 = connect_to('source')
    destination_w3 = connect_to('destination')
    
    # 创建合约实例
    source_contract = source_w3.eth.contract(
        address=source_contract_data['address'],
        abi=source_contract_data['abi']
    )
    
    destination_contract = destination_w3.eth.contract(
        address=destination_contract_data['address'],
        abi=destination_contract_data['abi']
    )
    
    # 获取私钥（在实际使用中应该从安全的地方获取）
    # 这里简化为从环境变量或配置文件获取
    private_key = get_warden_private_key()
    if not private_key:
        print("❌ No warden private key found")
        return
    
    # 处理每个事件
    for event in events:
        if chain == 'source' and event['event'] == 'Deposit':
            print(f"🎯 Processing Deposit event on source chain")
            handle_deposit_event(event, destination_w3, destination_contract, private_key)
        
        elif chain == 'destination' and event['event'] == 'Unwrap':
            print(f"🎯 Processing Unwrap event on destination chain")
            handle_unwrap_event(event, source_w3, source_contract, private_key)


def get_warden_private_key():
    """
    获取warden的私钥
    在实际部署中，应该从安全的地方获取，如环境变量或加密文件
    """
    try:
        # 尝试从文件读取
        with open("warden_key.txt", "r") as f:
            private_key = f.read().strip()
            if private_key.startswith('0x'):
                return private_key
    except FileNotFoundError:
        pass
    
    # 如果文件不存在，从用户输入获取
    private_key = input("🔑 Enter warden private key (0x...): ").strip()
    if private_key and private_key.startswith('0x'):
        # 保存到文件以便下次使用
        try:
            with open("warden_key.txt", "w") as f:
                f.write(private_key)
        except:
            pass
        return private_key
    
    return None


def handle_deposit_event(event, destination_w3, destination_contract, private_key):
    """
    处理Deposit事件 - 调用Destination合约的wrap()函数
    """
    try:
        token_address = event['args']['token']
        recipient = event['args']['recipient']
        amount = event['args']['amount']
        
        print(f"   Token: {token_address}")
        print(f"   Recipient: {recipient}")
        print(f"   Amount: {amount}")
        
        # 获取账户
        account = destination_w3.eth.account.from_key(private_key)
        
        # 检查wrapped token是否存在
        wrapped_token = destination_contract.functions.wrapped_tokens(token_address).call()
        if wrapped_token == "0x0000000000000000000000000000000000000000":
            print(f"❌ No wrapped token found for {token_address}")
            return
        
        print(f"   Wrapped token: {wrapped_token}")
        
        # 构建wrap交易
        nonce = destination_w3.eth.get_transaction_count(account.address)
        gas_price = destination_w3.eth.gas_price
        
        wrap_txn = destination_contract.functions.wrap(
            token_address,
            recipient,
            amount
        ).build_transaction({
            'from': account.address,
            'nonce': nonce,
            'gasPrice': gas_price,
            'gas': 200000
        })
        
        # 签名并发送
        signed_txn = destination_w3.eth.account.sign_transaction(wrap_txn, private_key)
        tx_hash = destination_w3.eth.send_raw_transaction(signed_txn.raw_transaction)
        
        print(f"📤 Wrap transaction sent: {tx_hash.hex()}")
        
        # 等待确认
        print("⏳ Waiting for confirmation...")
        receipt = destination_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        if receipt.status == 1:
            print("✅ Wrap transaction successful!")
        else:
            print("❌ Wrap transaction failed")
            
    except Exception as e:
        print(f"❌ Error handling deposit event: {e}")


def handle_unwrap_event(event, source_w3, source_contract, private_key):
    """
    处理Unwrap事件 - 调用Source合约的withdraw()函数
    """
    try:
        # 解析Unwrap事件参数
        # 根据您的合约ABI，参数可能是: underlying_token, wrapped_token, frm, to, amount
        if 'underlying_token' in event['args']:
            token_address = event['args']['underlying_token']
            recipient = event['args']['to']
            amount = event['args']['amount']
        elif 'wrapped_token' in event['args']:
            # 需要查询底层代币，这里简化处理
            token_address = event['args']['wrapped_token']
            recipient = event['args']['recipient'] if 'recipient' in event['args'] else event['args']['to']
            amount = event['args']['amount']
        else:
            print("❌ Cannot parse Unwrap event arguments")
            return
        
        print(f"   Token: {token_address}")
        print(f"   Recipient: {recipient}")
        print(f"   Amount: {amount}")
        
        # 获取账户
        account = source_w3.eth.account.from_key(private_key)
        
        # 构建withdraw交易
        nonce = source_w3.eth.get_transaction_count(account.address)
        gas_price = source_w3.eth.gas_price
        
        withdraw_txn = source_contract.functions.withdraw(
            token_address,
            recipient,
            amount
        ).build_transaction({
            'from': account.address,
            'nonce': nonce,
            'gasPrice': gas_price,
            'gas': 200000
        })
        
        # 签名并发送
        signed_txn = source_w3.eth.account.sign_transaction(withdraw_txn, private_key)
        tx_hash = source_w3.eth.send_raw_transaction(signed_txn.raw_transaction)
        
        print(f"📤 Withdraw transaction sent: {tx_hash.hex()}")
        
        # 等待确认
        print("⏳ Waiting for confirmation...")
        receipt = source_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        if receipt.status == 1:
            print("✅ Withdraw transaction successful!")
        else:
            print("❌ Withdraw transaction failed")
            
    except Exception as e:
        print(f"❌ Error handling unwrap event: {e}")


def start_bridge_monitoring(contract_info="contract_info.json", interval=10):
    """
    启动跨链桥监控，定期扫描两个链的事件
    """
    print("🌉 Starting bridge monitoring...")
    print("="*50)
    
    while True:
        try:
            print(f"\n🔄 Scanning at {datetime.now().strftime('%H:%M:%S')}")
            
            # 扫描Source链的Deposit事件
            print("\n🔵 Scanning source chain for Deposit events...")
            source_events = scan_blocks('source', contract_info)
            
            # 扫描Destination链的Unwrap事件
            print("\n🟡 Scanning destination chain for Unwrap events...")
            dest_events = scan_blocks('destination', contract_info)
            
            print(f"\n📊 Summary: Found {len(source_events)} Deposit events, {len(dest_events)} Unwrap events")
            
            # 等待下一次扫描
            print(f"⏳ Next scan in {interval} seconds...", end='\r')
            time.sleep(interval)
            
        except KeyboardInterrupt:
            print("\n\n🛑 Bridge monitoring stopped")
            break
        except Exception as e:
            print(f"\n⚠️ Error in bridge monitoring: {e}")
            time.sleep(interval)


def main():
    """
    主函数
    """
    print("🚀 Cross-Chain Bridge System")
    print("="*50)
    
    # 检查合约信息文件是否存在
    contract_info_file = "contract_info.json"
    
    try:
        with open(contract_info_file, "r") as f:
            contracts = json.load(f)
            print(f"✅ Loaded contract info from {contract_info_file}")
            print(f"   Source contract: {contracts['source']['address']}")
            print(f"   Destination contract: {contracts['destination']['address']}")
    except FileNotFoundError:
        print(f"⚠️ {contract_info_file} not found, using default contract_info.json")
        contract_info_file = "contract_info.json"
    
    # 启动跨链桥监控
    start_bridge_monitoring(contract_info_file, interval=15)


if __name__ == "__main__":
    main()
