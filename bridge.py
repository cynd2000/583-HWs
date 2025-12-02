# bridge.py
from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware
from datetime import datetime
import json
import pandas as pd
import time
import csv
import os


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
        
        # 扫描事件
        try:
            # 尝试一次性扫描所有区块
            event_filter = event_obj.create_filter(
                from_block=from_block,
                to_block=to_block,
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
            
            print(f"✅ Found {len(all_events)} {event_name} events")
            
        except Exception as e:
            print(f"⚠️  Could not scan events: {e}")
            return []
        
        # 处理事件（调用相应的函数）
        if all_events:
            process_events(chain, all_events, contract_info)
        
    except Exception as e:
        print(f"❌ Error in scan_blocks: {e}")
        import traceback
        traceback.print_exc()
        return []
    
    return all_events


def get_warden_account():
    """
    获取warden的账户
    从文件中读取私钥
    """
    try:
        # 尝试从文件读取私钥
        key_file = "warden_key.txt"
        if os.path.exists(key_file):
            with open(key_file, "r") as f:
                private_key = f.read().strip()
                if private_key and private_key.startswith('0x'):
                    # 创建账户对象
                    from eth_account import Account
                    return Account.from_key(private_key)
    except Exception as e:
        print(f"⚠️  Could not read warden key: {e}")
    
    return None


def process_events(chain, events, contract_info="contract_info.json"):
    """
    处理扫描到的事件，调用相应的跨链函数
    """
    if not events:
        return
    
    print(f"🎯 Processing {len(events)} events from {chain} chain")
    
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
    
    # 获取warden账户
    account = get_warden_account()
    if not account:
        print("❌ No warden account found")
        print("   Create a file named 'warden_key.txt' with your private key (0x...)")
        return
    
    # 处理每个事件
    for i, event in enumerate(events):
        if chain == 'source' and event['event'] == 'Deposit':
            print(f"   [{i+1}/{len(events)}] Processing Deposit event...")
            handle_deposit_event(event, destination_w3, destination_contract, account)
            # 添加延迟避免nonce冲突
            time.sleep(1)
        
        elif chain == 'destination' and event['event'] == 'Unwrap':
            print(f"   [{i+1}/{len(events)}] Processing Unwrap event...")
            handle_unwrap_event(event, source_w3, source_contract, account)
            # 添加延迟避免nonce冲突
            time.sleep(1)


def handle_deposit_event(event, destination_w3, destination_contract, account):
    """
    处理Deposit事件 - 调用Destination合约的wrap()函数
    """
    try:
        # 解析事件参数 - 根据错误输出，参数有：token, recipient, amount
        token_address = event['args']['token']
        recipient = event['args']['recipient']
        amount = event['args']['amount']
        
        # 获取nonce - 从事件参数获取
        if 'nonce' in event['args']:
            nonce = event['args']['nonce']
        else:
            # 如果没有nonce，尝试其他字段或使用默认
            nonce = 0
            for key in event['args']:
                if 'nonce' in key.lower():
                    nonce = event['args'][key]
                    break
        
        print(f"   Token: {token_address}")
        print(f"   Recipient: {recipient}")
        print(f"   Amount: {amount}")
        print(f"   Using nonce: {nonce}")
        
        # 检查wrapped token
        try:
            # 尝试获取wrapped token地址
            wrapped_token = destination_contract.functions.wrapped_tokens(token_address).call()
            if wrapped_token and wrapped_token != "0x0000000000000000000000000000000000000000":
                print(f"   Wrapped token: {wrapped_token}")
        except:
            pass  # 如果查询失败，继续执行
        
        # 获取交易nonce
        tx_nonce = destination_w3.eth.get_transaction_count(account.address, 'pending')
        gas_price = destination_w3.eth.gas_price
        
        print(f"   Transaction nonce: {tx_nonce}")
        
        try:
            # 构建wrap交易 - 根据错误输出，wrap函数需要4个参数
            wrap_txn = destination_contract.functions.wrap(
                token_address,  # token
                recipient,      # recipient
                amount,         # amount
                nonce           # nonce (从事件获取)
            ).build_transaction({
                'from': account.address,
                'nonce': tx_nonce,
                'gasPrice': gas_price,
                'gas': 200000,
                'chainId': destination_w3.eth.chain_id
            })
            
            # 签名并发送
            signed_txn = account.sign_transaction(wrap_txn)
            tx_hash = destination_w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            
            print(f"📤 Wrap transaction sent: {tx_hash.hex()}")
            
            # 等待确认
            print("⏳ Waiting for confirmation...")
            receipt = destination_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt.status == 1:
                print("✅ Wrap transaction successful!")
                # 可以记录成功的交易
                log_transaction('wrap', tx_hash.hex(), event)
            else:
                print("❌ Wrap transaction failed")
                
        except Exception as e:
            print(f"❌ Error building/sending wrap transaction: {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        print(f"❌ Error handling deposit event: {e}")
        import traceback
        traceback.print_exc()


def handle_unwrap_event(event, source_w3, source_contract, account):
    """
    处理Unwrap事件 - 调用Source合约的withdraw()函数
    """
    try:
        # 解析Unwrap事件参数
        # 从错误输出看：underlying_token, wrapped_token, to, amount
        args = event['args']
        
        # 尝试不同的参数名
        token_address = args.get('underlying_token') or args.get('wrapped_token') or args.get('token')
        recipient = args.get('to') or args.get('recipient')
        amount = args.get('amount')
        
        # 获取nonce
        nonce = args.get('nonce') or 0
        for key in args:
            if 'nonce' in key.lower():
                nonce = args[key]
                break
        
        if not token_address or not recipient or not amount:
            print("❌ Cannot parse Unwrap event arguments")
            print(f"   Available args: {args}")
            return
        
        print(f"   Token: {token_address}")
        print(f"   Recipient: {recipient}")
        print(f"   Amount: {amount}")
        print(f"   Using nonce: {nonce}")
        
        # 获取交易nonce
        tx_nonce = source_w3.eth.get_transaction_count(account.address, 'pending')
        gas_price = source_w3.eth.gas_price
        
        print(f"   Transaction nonce: {tx_nonce}")
        
        try:
            # 构建withdraw交易 - 根据错误输出，withdraw函数需要4个参数
            withdraw_txn = source_contract.functions.withdraw(
                token_address,  # token
                recipient,      # recipient
                amount,         # amount
                nonce           # nonce (从事件获取)
            ).build_transaction({
                'from': account.address,
                'nonce': tx_nonce,
                'gasPrice': gas_price,
                'gas': 200000,
                'chainId': source_w3.eth.chain_id
            })
            
            # 签名并发送
            signed_txn = account.sign_transaction(withdraw_txn)
            tx_hash = source_w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            
            print(f"📤 Withdraw transaction sent: {tx_hash.hex()}")
            
            # 等待确认
            print("⏳ Waiting for confirmation...")
            receipt = source_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt.status == 1:
                print("✅ Withdraw transaction successful!")
                # 可以记录成功的交易
                log_transaction('withdraw', tx_hash.hex(), event)
            else:
                print("❌ Withdraw transaction failed")
                
        except Exception as e:
            print(f"❌ Error building/sending withdraw transaction: {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        print(f"❌ Error handling unwrap event: {e}")
        import traceback
        traceback.print_exc()


def log_transaction(action, tx_hash, event):
    """
    记录交易日志
    """
    try:
        log_file = "bridge_transactions.csv"
        file_exists = os.path.exists(log_file)
        
        with open(log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['timestamp', 'action', 'tx_hash', 'event', 'chain', 'block', 'args'])
            
            writer.writerow([
                datetime.now().isoformat(),
                action,
                tx_hash,
                event['event'],
                event['chain'],
                event['blockNumber'],
                str(event['args'])
            ])
    except:
        pass


def start_bridge_monitoring(contract_info="contract_info.json", interval=10):
    """
    启动跨链桥监控，定期扫描两个链的事件
    """
    print("🌉 Starting bridge monitoring...")
    print("="*50)
    
    # 检查warden账户
    account = get_warden_account()
    if not account:
        print("❌ No warden account found")
        print("   Please create a file named 'warden_key.txt' with your private key (0x...)")
        return
    
    print(f"✅ Using warden account: {account.address}")
    
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
        print(f"⚠️ {contract_info_file} not found")
        return
    
    # 启动跨链桥监控
    start_bridge_monitoring(contract_info_file, interval=15)


if __name__ == "__main__":
    main()
