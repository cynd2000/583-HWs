# bridge.py
from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware
import json
import pandas as pd
import time
import csv
import os


def connect_to(chain):
    """
    连接到指定的区块链网络
    """
    if chain == 'source' or chain == 'avax':  # Source合约在Avalanche
        api_url = "https://api.avax-test.network/ext/bc/C/rpc"
        w3 = Web3(Web3.HTTPProvider(api_url))
        # Avalanche需要POA中间件
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        
    elif chain == 'destination' or chain == 'bsc':  # Destination合约在BNB
        api_url = "https://data-seed-prebsc-1-s1.binance.org:8545/"
        w3 = Web3(Web3.HTTPProvider(api_url))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    else:
        raise ValueError(f"不支持的链: {chain}")
    
    return w3


def load_contract_info():
    """
    加载contract_info_new.json文件
    """
    try:
        with open("contract_info_new.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ contract_info_new.json 文件不存在")
        print("   请先运行 deploy_all_contracts.py")
        return None


def load_erc20_mapping():
    """
    加载erc20s.csv文件，创建代币映射
    """
    try:
        with open("erc20s.csv", "r") as f:
            reader = csv.reader(f)
            next(reader)  # 跳过标题行
            
            mapping = {'avax': [], 'bsc': []}
            for row in reader:
                if len(row) >= 2:
                    chain = row[0].strip().lower()
                    address = row[1].strip()
                    if chain in mapping:
                        mapping[chain].append(address)
            
            print(f"📄 加载代币映射: {len(mapping['avax'])}个Avalanche, {len(mapping['bsc'])}个BNB")
            return mapping
    except FileNotFoundError:
        print("❌ erc20s.csv 文件不存在")
        return None


def get_private_key():
    """
    从用户输入获取私钥
    """
    private_key = input("请输入warden的私钥 (0x开头): ").strip()
    if not private_key or not private_key.startswith('0x'):
        print("❌ 无效的私钥格式")
        return None
    return private_key


def scan_blocks(chain, start_block, end_block, contract_address, event_name='Deposit'):
    """
    基于Assignment IV的scan_blocks函数，但支持不同事件
    
    chain - string (Either 'source' or 'destination')
    start_block - integer first block to scan
    end_block - integer last block to scan
    contract_address - the address of the deployed contract
    event_name - string (Either 'Deposit' or 'Unwrap')
    
    Returns: 事件列表
    """
    if chain == 'source':
        api_url = "https://api.avax-test.network/ext/bc/C/rpc"
        w3 = Web3(Web3.HTTPProvider(api_url))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    elif chain == 'destination':
        api_url = "https://data-seed-prebsc-1-s1.binance.org:8545/"
        w3 = Web3(Web3.HTTPProvider(api_url))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    else:
        raise ValueError(f"不支持的链: {chain}")
    
    # 加载合约ABI
    contract_info = load_contract_info()
    if not contract_info:
        return []
    
    # 根据链和事件类型选择ABI
    if chain == 'source':
        contract_abi = contract_info['source']['abi']
    elif chain == 'destination':
        contract_abi = contract_info['destination']['abi']
    
    # 创建合约实例
    contract = w3.eth.contract(address=contract_address, abi=contract_abi)
    
    if start_block == "latest":
        start_block = w3.eth.get_block_number()
    if end_block == "latest":
        end_block = w3.eth.get_block_number()
    
    if end_block < start_block:
        print(f"错误: end_block < start_block!")
        return []
    
    if start_block == end_block:
        print(f"扫描 {chain} 链区块 {start_block} 的 {event_name} 事件")
    else:
        print(f"扫描 {chain} 链区块 {start_block} - {end_block} 的 {event_name} 事件")
    
    all_events = []
    
    # 根据事件名称获取事件对象
    try:
        event_obj = getattr(contract.events, event_name)
    except AttributeError:
        print(f"❌ 合约没有 {event_name} 事件")
        return []
    
    # 分批扫描
    batch_size = 30
    current_block = start_block
    
    while current_block <= end_block:
        batch_end = min(current_block + batch_size - 1, end_block)
        
        try:
            # 创建事件过滤器
            event_filter = event_obj.create_filter(
                from_block=current_block,
                to_block=batch_end,
                argument_filters={}
            )
            events = event_filter.get_all_entries()
            
            for ev in events:
                # 格式化事件数据
                event_data = {
                    'blockNumber': ev['blockNumber'],
                    'transactionHash': ev['transactionHash'].hex(),
                    'address': ev['address'],
                    'args': dict(ev['args']),
                    'event': event_name,
                    'chain': chain
                }
                all_events.append(event_data)
            
            print(f"  区块 {current_block}-{batch_end}: 找到 {len(events)} 个事件")
            
        except Exception as e:
            print(f"  区块 {current_block}-{batch_end} 扫描失败: {e}")
        
        current_block = batch_end + 1
    
    print(f"✅ 总计找到 {len(all_events)} 个 {event_name} 事件")
    return all_events


def handle_deposit_event(event, destination_w3, destination_contract, private_key):
    """
    处理Deposit事件 - 调用Destination合约的wrap()函数
    """
    print(f"🎯 处理Deposit事件:")
    print(f"   代币: {event['args']['token']}")
    print(f"   接收者: {event['args']['recipient']}")
    print(f"   数量: {event['args']['amount']}")
    
    try:
        # 获取账户
        account = destination_w3.eth.account.from_key(private_key)
        
        # 检查wrapped token是否存在
        wrapped_token = destination_contract.functions.wrapped_tokens(event['args']['token']).call()
        
        if wrapped_token == "0x0000000000000000000000000000000000000000":
            print(f"❌ 代币 {event['args']['token']} 没有对应的包装代币")
            return
        
        print(f"   找到包装代币: {wrapped_token}")
        
        # 构建wrap交易
        nonce = destination_w3.eth.get_transaction_count(account.address)
        gas_price = destination_w3.eth.gas_price
        
        wrap_txn = destination_contract.functions.wrap(
            event['args']['token'],      # _underlying_token
            event['args']['recipient'],  # _recipient
            event['args']['amount']      # _amount
        ).build_transaction({
            'from': account.address,
            'nonce': nonce,
            'gasPrice': gas_price,
            'gas': 200000
        })
        
        # 签名并发送
        signed_txn = destination_w3.eth.account.sign_transaction(wrap_txn, private_key)
        tx_hash = destination_w3.eth.send_raw_transaction(signed_txn.raw_transaction)
        
        print(f"📤 Wrap交易已发送: {tx_hash.hex()}")
        
        # 等待确认
        print("⏳ 等待交易确认...")
        receipt = destination_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        if receipt.status == 1:
            print("✅ Wrap交易成功!")
        else:
            print("❌ Wrap交易失败")
            
    except Exception as e:
        print(f"❌ 处理Deposit事件失败: {e}")


def handle_unwrap_event(event, source_w3, source_contract, private_key):
    """
    处理Unwrap事件 - 调用Source合约的withdraw()函数
    """
    print(f"🎯 处理Unwrap事件:")
    
    # 根据您的合约ABI，Unwrap事件可能有不同的参数结构
    # 假设参数是: underlying_token, wrapped_token, frm, to, amount
    if 'underlying_token' in event['args']:
        token_address = event['args']['underlying_token']
        recipient = event['args']['to']
        amount = event['args']['amount']
    elif 'wrapped_token' in event['args']:
        # 需要查询底层代币
        # 这里简化处理，实际需要查询合约
        token_address = event['args']['wrapped_token']  # 临时使用
        recipient = event['args']['recipient'] if 'recipient' in event['args'] else event['args']['to']
        amount = event['args']['amount']
    else:
        print("❌ 无法解析Unwrap事件参数")
        return
    
    print(f"   代币: {token_address}")
    print(f"   接收者: {recipient}")
    print(f"   数量: {amount}")
    
    try:
        # 获取账户
        account = source_w3.eth.account.from_key(private_key)
        
        # 构建withdraw交易
        nonce = source_w3.eth.get_transaction_count(account.address)
        gas_price = source_w3.eth.gas_price
        
        withdraw_txn = source_contract.functions.withdraw(
            token_address,  # _token
            recipient,      # _recipient
            amount          # _amount
        ).build_transaction({
            'from': account.address,
            'nonce': nonce,
            'gasPrice': gas_price,
            'gas': 200000
        })
        
        # 签名并发送
        signed_txn = source_w3.eth.account.sign_transaction(withdraw_txn, private_key)
        tx_hash = source_w3.eth.send_raw_transaction(signed_txn.raw_transaction)
        
        print(f"📤 Withdraw交易已发送: {tx_hash.hex()}")
        
        # 等待确认
        print("⏳ 等待交易确认...")
        receipt = source_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        if receipt.status == 1:
            print("✅ Withdraw交易成功!")
        else:
            print("❌ Withdraw交易失败")
            
    except Exception as e:
        print(f"❌ 处理Unwrap事件失败: {e}")


def listen_for_events(chain, contract_address, callback_function, private_key, other_chain_info, 
                     event_name='Deposit', poll_interval=5):
    """
    持续监听指定合约的事件
    
    基于Assignment IV的监听逻辑，但添加了回调处理
    """
    print(f"👂 开始监听{chain}链的{event_name}事件...")
    
    # 连接到当前链
    w3 = connect_to(chain)
    
    # 加载合约ABI
    contract_info = load_contract_info()
    if not contract_info:
        return
    
    if chain == 'source':
        contract_abi = contract_info['source']['abi']
    elif chain == 'destination':
        contract_abi = contract_info['destination']['abi']
    
    # 创建合约实例
    contract = w3.eth.contract(address=contract_address, abi=contract_abi)
    
    # 获取起始区块
    last_block = w3.eth.block_number
    print(f"📊 起始区块: {last_block}")
    
    while True:
        try:
            current_block = w3.eth.block_number
            
            if current_block > last_block:
                print(f"🔄 发现新区块: {last_block + 1} - {current_block}")
                
                # 扫描新区块中的事件
                events = scan_blocks(
                    chain=chain,
                    start_block=last_block + 1,
                    end_block=current_block,
                    contract_address=contract_address,
                    event_name=event_name
                )
                
                # 处理事件
                for event in events:
                    print(f"📥 处理事件: {event['transactionHash']}")
                    
                    # 调用回调函数
                    # 回调函数应该接受事件数据和所需的参数
                    callback_function(event, *other_chain_info, private_key)
                
                last_block = current_block
            
            # 显示监听状态
            current_time = time.strftime("%H:%M:%S")
            print(f"⏰ {current_time} - 监听{chain}链中... 区块: {current_block}", end='\r')
            
            time.sleep(poll_interval)
            
        except KeyboardInterrupt:
            print(f"\n🛑 停止监听{chain}链")
            break
        except Exception as e:
            print(f"\n⚠️ 监听错误: {e}")
            time.sleep(poll_interval)


def main():
    """
    主函数 - 启动双向跨链桥
    """
    print("🌉 启动双向跨链桥...")
    print("="*50)
    
    # 1. 加载配置
    contract_info = load_contract_info()
    if not contract_info:
        return
    
    erc20_mapping = load_erc20_mapping()
    if not erc20_mapping:
        return
    
    private_key = get_private_key()
    if not private_key:
        return
    
    # 2. 连接到网络
    print("\n🔗 连接到区块链网络...")
    source_w3 = connect_to('source')
    destination_w3 = connect_to('destination')
    
    print(f"✅ Avalanche连接: {source_w3.is_connected()}")
    print(f"✅ BNB连接: {destination_w3.is_connected()}")
    
    # 3. 获取合约地址
    source_address = contract_info['source']['address']
    destination_address = contract_info['destination']['address']
    
    # 4. 创建合约实例（用于处理事件）
    source_contract = source_w3.eth.contract(
        address=source_address,
        abi=contract_info['source']['abi']
    )
    
    destination_contract = destination_w3.eth.contract(
        address=destination_address,
        abi=contract_info['destination']['abi']
    )
    
    print(f"📄 Source合约地址: {source_address}")
    print(f"📄 Destination合约地址: {destination_address}")
    
    # 5. 先扫描历史事件
    print("\n📜 扫描历史事件...")
    
    # 扫描Source合约的历史Deposit事件
    deposit_events = scan_blocks(
        chain='source',
        start_block=max(0, source_w3.eth.block_number - 100),
        end_block='latest',
        contract_address=source_address,
        event_name='Deposit'
    )
    
    # 处理历史Deposit事件
    for event in deposit_events:
        handle_deposit_event(event, destination_w3, destination_contract, private_key)
    
    # 扫描Destination合约的历史Unwrap事件
    unwrap_events = scan_blocks(
        chain='destination',
        start_block=max(0, destination_w3.eth.block_number - 100),
        end_block='latest',
        contract_address=destination_address,
        event_name='Unwrap'
    )
    
    # 处理历史Unwrap事件
    for event in unwrap_events:
        handle_unwrap_event(event, source_w3, source_contract, private_key)
    
    print("\n" + "="*50)
    print("🚀 跨链桥已启动! 开始双向监听...")
    print("="*50)
    
    # 6. 启动双向监听（这里简化，实际应该用多线程）
    print("📢 注意: 实际部署时应该使用多线程同时监听两个链")
    print("🔧 当前版本将监听Avalanche链的Deposit事件")
    
    # 监听Source合约的Deposit事件
    try:
        listen_for_events(
            chain='source',
            contract_address=source_address,
            callback_function=handle_deposit_event,
            private_key=private_key,
            other_chain_info=(destination_w3, destination_contract),  # 传递给回调函数的额外参数
            event_name='Deposit',
            poll_interval=5
        )
    except KeyboardInterrupt:
        print("\n🛑 跨链桥已停止")


if __name__ == "__main__":
    main()
