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
    print(f"🔍 Scanning blocks on {chain} chain using {contract_info}")
    
    w3 = connect_to(chain)
    
    contract_data = get_contract_info(chain, contract_info)
    if not contract_data:
        print(f"❌ Failed to get contract info for {chain}")
        return []
    
    contract_address = contract_data['address']
    contract_abi = contract_data['abi']
    
    contract = w3.eth.contract(address=contract_address, abi=contract_abi)
    
    current_block = w3.eth.block_number
    # 大大增加扫描范围
    from_block = max(0, current_block - 100)  # 扫描最近100个区块
    to_block = current_block
    
    print(f"   Contract: {contract_address}")
    print(f"   Scanning blocks: {from_block} to {to_block} (total: {to_block - from_block + 1} blocks)")
    
    if chain == 'source':
        event_name = 'Deposit'
    elif chain == 'destination':
        event_name = 'Unwrap'
    else:
        print(f"❌ Unknown chain: {chain}")
        return []
    
    all_events = []
    
    try:
        event_obj = getattr(contract.events, event_name)
        
        # 方法1：尝试批量扫描
        try:
            print("   Method 1: Bulk scan...")
            events = event_obj.get_logs(fromBlock=from_block, toBlock=to_block)
            print(f"   Found {len(events)} events via bulk scan")
            
            for ev in events:
                args_dict = dict(ev['args'])
                formatted_event = {
                    'blockNumber': ev['blockNumber'],
                    'transactionHash': ev['transactionHash'].hex(),
                    'address': ev['address'],
                    'args': args_dict,
                    'event': event_name,
                    'chain': chain
                }
                all_events.append(formatted_event)
                
        except Exception as e:
            print(f"   Bulk scan failed: {e}")
            
            # 方法2：逐个区块扫描
            print("   Method 2: Scanning block by block...")
            for block_num in range(from_block, to_block + 1):
                try:
                    block_events = event_obj.get_logs(fromBlock=block_num, toBlock=block_num)
                    for ev in block_events:
                        args_dict = dict(ev['args'])
                        formatted_event = {
                            'blockNumber': ev['blockNumber'],
                            'transactionHash': ev['transactionHash'].hex(),
                            'address': ev['address'],
                            'args': args_dict,
                            'event': event_name,
                            'chain': chain
                        }
                        all_events.append(formatted_event)
                except:
                    continue
        
        print(f"✅ Total found: {len(all_events)} {event_name} events")
        
        # 按区块号排序
        all_events.sort(key=lambda x: x['blockNumber'])
        
        # 打印事件详情
        for i, event in enumerate(all_events):
            print(f"   Event {i+1}: Block {event['blockNumber']}, TX: {event['transactionHash'][:20]}...")
            if event_name == 'Deposit':
                print(f"     Token: {event['args'].get('token')}, Amount: {event['args'].get('amount')}")
            elif event_name == 'Unwrap':
                print(f"     Token: {event['args'].get('underlying_token')}, Amount: {event['args'].get('amount')}")
        
        # 处理事件
        if all_events:
            process_events(chain, all_events, contract_info)
        
    except Exception as e:
        print(f"❌ Error in scan_blocks: {e}")
        import traceback
        traceback.print_exc()
        return []
    
    return all_events

def process_events(chain, events, contract_info="contract_info.json"):
    """
    处理扫描到的事件，调用相应的跨链函数
    """
    if not events:
        print("   No events to process")
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
    
    # 获取私钥
    private_key = get_warden_private_key()
    if not private_key:
        print("❌ No warden private key found")
        return
    
    # 读取测试代币地址
    test_tokens = []
    try:
        with open("erc20s.csv", "r") as f:
            reader = csv.reader(f)
            next(reader)  # 跳过标题行
            for row in reader:
                if len(row) >= 2:
                    token_addr = row[1].strip()
                    if token_addr.startswith('0x'):
                        test_tokens.append(token_addr.lower())
        print(f"   Loaded {len(test_tokens)} test tokens")
    except Exception as e:
        print(f"❌ Could not read test tokens from erc20s.csv: {e}")
        test_tokens = []
    
    # 处理每个事件
    for event in events:
        if chain == 'source' and event['event'] == 'Deposit':
            # 处理Deposit事件
            args = event['args']
            print(f"   Processing Deposit event: {args}")
            
            # 获取参数
            if 'token' not in args or 'recipient' not in args or 'amount' not in args:
                print(f"   Missing required parameters in Deposit event")
                continue
            
            token_address = args['token']
            recipient = args['recipient']
            amount = args['amount']
            
            # 转换为小写比较
            token_lower = token_address.lower()
            
            # 只处理测试代币
            if token_lower not in test_tokens:
                print(f"   Skipping non-test token: {token_address}")
                continue
                
            print(f"   ✅ Processing Deposit for test token: {token_address}")
            print(f"   Recipient: {recipient}, Amount: {amount}")
            
            # 调用handle_deposit_event函数
            handle_deposit_event(event, destination_w3, destination_contract, private_key)
        
        elif chain == 'destination' and event['event'] == 'Unwrap':
            # 解析Unwrap事件
            args = event['args']
            print(f"   Processing Unwrap event: {args}")
            
            # 获取参数 - 根据你的ABI
            required_keys = ['underlying_token', 'to', 'amount']
            missing_keys = [key for key in required_keys if key not in args]
            if missing_keys:
                print(f"   Missing keys in Unwrap event: {missing_keys}")
                print(f"   Available keys: {args.keys()}")
                continue
            
            token_address = args['underlying_token']
            recipient = args['to']
            amount = args['amount']
            
            # 转换为小写比较
            token_lower = token_address.lower()
            
            # 只处理测试代币
            if token_lower not in test_tokens:
                print(f"   Skipping non-test token: {token_address}")
                continue
                
            print(f"   ✅ Processing Unwrap for test token: {token_address}")
            print(f"   Recipient: {recipient}, Amount: {amount}")
            
            # 调用handle_unwrap_event函数
            handle_unwrap_event(event, source_w3, source_contract, private_key)
        
        else:
            print(f"   Skipping event type: {event['event']} on {chain} chain")

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
        # 新的nonce获取方式 - 使用'pending'状态
        nonce = destination_w3.eth.get_transaction_count(account.address, 'pending')
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
        import traceback
        traceback.print_exc()


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
