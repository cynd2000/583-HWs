# bridge.py
from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware
from datetime import datetime
import json
import pandas as pd
import time
import csv
from web3.exceptions import TransactionNotFound
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def connect_to(chain):
    """
    连接到指定的区块链网络
    """
    if chain == 'source':  # Avalanche
        api_url = "https://api.avax-test.network/ext/bc/C/rpc"
        w3 = Web3(Web3.HTTPProvider(api_url))
        # Avalanche需要POA中间件
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        
    elif chain == 'destination':  # BNB
        api_url = "https://data-seed-prebsc-1-s1.binance.org:8545/"
        w3 = Web3(Web3.HTTPProvider(api_url))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    else:
        raise ValueError(f"不支持的链: {chain}")
    
    return w3

def get_contract_info(chain, contract_info):
    """
    从contract_info字典中获取指定链的合约信息
    """
    if chain == 'source':
        return {
            'address': contract_info['source']['address'],
            'abi': contract_info['source']['abi']
        }
    elif chain == 'destination':
        return {
            'address': contract_info['destination']['address'],
            'abi': contract_info['destination']['abi']
        }
    else:
        raise ValueError(f"不支持的链: {chain}")

def load_contract_info():
    """
    加载contract_info_new.json文件
    """
    try:
        with open("contract_info_new.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("❌ contract_info_new.json 文件不存在")
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
            
            logger.info(f"📄 加载代币映射: {len(mapping['avax'])}个Avalanche, {len(mapping['bsc'])}个BNB")
            return mapping
    except FileNotFoundError:
        logger.error("❌ erc20s.csv 文件不存在")
        return None

def get_private_key():
    """
    从用户输入获取私钥
    """
    private_key = input("请输入warden的私钥 (0x开头): ").strip()
    if not private_key or not private_key.startswith('0x'):
        logger.error("❌ 无效的私钥格式")
        return None
    return private_key

def get_contract_instance(w3, address, abi):
    """
    创建合约实例
    """
    return w3.eth.contract(address=address, abi=abi)

def parse_deposit_event_from_receipt(source_contract, receipt, tx):
    """
    从交易收据中解析Deposit事件
    """
    try:
        # 获取Deposit事件接口
        deposit_event = source_contract.events.Deposit()
        
        # 处理所有日志，找到Deposit事件
        for log in receipt.logs:
            try:
                # 尝试解析为Deposit事件
                event_data = deposit_event.process_log(log)
                
                # 验证事件参数
                if 'args' in event_data and 'token' in event_data['args']:
                    logger.info(f"✅ 成功解析Deposit事件")
                    return event_data
                    
            except Exception as e:
                # 不是Deposit事件，继续下一个
                continue
        
        logger.warning("⚠️ 未找到Deposit事件")
        return None
        
    except Exception as e:
        logger.error(f"❌ 解析事件失败: {e}")
        return None

def handle_deposit_event(event, destination_w3, destination_contract, private_key, erc20_mapping):
    """
    处理Deposit事件的回调函数
    """
    try:
        token_address = event['args']['token']
        recipient = event['args']['recipient']
        amount = event['args']['amount']
        
        logger.info(f"🎯 处理Deposit事件:")
        logger.info(f"   代币: {token_address}")
        logger.info(f"   接收者: {recipient}")
        logger.info(f"   数量: {amount}")
        
        # 获取账户
        account = destination_w3.eth.account.from_key(private_key)
        
        # 检查代币是否在erc20_mapping中
        if token_address not in erc20_mapping.get('avax', []):
            logger.warning(f"⚠️ 代币 {token_address} 不在erc20s.csv中")
            return
        
        # 检查wrapped token是否存在
        try:
            wrapped_token = destination_contract.functions.wrapped_tokens(token_address).call()
            
            if wrapped_token == "0x0000000000000000000000000000000000000000":
                logger.error(f"❌ 代币 {token_address} 尚未在Destination合约中创建wrapped token")
                logger.info(f"💡 请先在Destination合约调用createToken()创建包装代币")
                return
            
            logger.info(f"   找到wrapped token: {wrapped_token}")
            
            # 构建wrap交易
            nonce = destination_w3.eth.get_transaction_count(account.address)
            gas_price = destination_w3.eth.gas_price
            
            # 构建交易
            wrap_txn = destination_contract.functions.wrap(
                token_address,  # _underlying_token
                recipient,      # _recipient
                amount          # _amount
            ).build_transaction({
                'from': account.address,
                'nonce': nonce,
                'gasPrice': gas_price,
                'gas': 200000  # 固定gas，避免估算失败
            })
            
            # 签名并发送
            signed_txn = destination_w3.eth.account.sign_transaction(wrap_txn, private_key)
            tx_hash = destination_w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            
            logger.info(f"📤 Wrap交易已发送: {tx_hash.hex()}")
            
            # 等待确认
            logger.info("⏳ 等待交易确认...")
            receipt = destination_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt.status == 1:
                logger.info("✅ Wrap交易成功!")
                
                # 查找Wrap事件
                wrap_event = destination_contract.events.Wrap()
                for log in receipt.logs:
                    try:
                        event_data = wrap_event.process_log(log)
                        if event_data:
                            logger.info(f"🎉 成功mint {amount} 包装代币给 {recipient}")
                            break
                    except:
                        continue
            else:
                logger.error("❌ Wrap交易失败")
                
        except Exception as e:
            logger.error(f"❌ 处理Deposit事件失败: {e}")
            
    except Exception as e:
        logger.error(f"❌ 处理事件时发生错误: {e}")

def scan_blocks(chain, event_name, from_block, to_block):
    """
    扫描指定范围内的区块以查找事件
    
    Args:
        chain (str): 'source' 或 'destination'
        event_name (str): 事件名称，如'Deposit'或'Unwrap'
        from_block (int): 起始区块号
        to_block (int): 结束区块号
    
    Returns:
        list: 事件列表
    """
    logger.info(f"🔍 扫描{chain}链的{event_name}事件，区块 {from_block} 到 {to_block}")
    
    try:
        # 连接到对应链
        w3 = connect_to(chain)
        
        # 加载合约信息
        contract_info = load_contract_info()
        if not contract_info:
            return []
        
        # 获取合约信息
        if chain == 'source':
            contract_data = get_contract_info('source', contract_info)
        elif chain == 'destination':
            contract_data = get_contract_info('destination', contract_info)
        else:
            logger.error(f"❌ 不支持的链: {chain}")
            return []
        
        # 创建合约实例
        contract = get_contract_instance(w3, contract_data['address'], contract_data['abi'])
        
        # 获取事件对象
        try:
            event_obj = getattr(contract.events, event_name)()
        except AttributeError:
            logger.error(f"❌ 合约没有 {event_name} 事件")
            return []
        
        all_events = []
        
        # 分批扫描，避免请求太大
        batch_size = 1000
        current_block = from_block
        
        while current_block <= to_block:
            end_block = min(current_block + batch_size - 1, to_block)
            
            logger.debug(f"   扫描区块 {current_block} - {end_block}...")
            
            try:
                # 使用get_logs获取事件
                events = event_obj.get_logs(
                    fromBlock=current_block,
                    toBlock=end_block
                )
                
                if events:
                    logger.info(f"     找到 {len(events)} 个事件")
                    all_events.extend(events)
                
            except Exception as batch_error:
                logger.warning(f"     区块 {current_block}-{end_block} 扫描失败: {batch_error}")
                # 如果批量失败，尝试更小的批次
                if batch_size > 100:
                    batch_size = batch_size // 2
                    continue
            
            current_block = end_block + 1
        
        logger.info(f"✅ 总计找到 {len(all_events)} 个 {event_name} 事件")
        
        # 格式化返回结果
        formatted_events = []
        for event in all_events:
            formatted_event = {
                'blockNumber': event['blockNumber'],
                'transactionHash': event['transactionHash'].hex(),
                'args': dict(event['args'])
            }
            formatted_events.append(formatted_event)
        
        return formatted_events
        
    except Exception as e:
        logger.error(f"❌ 扫描事件失败: {e}")
        return []
def listen_for_events(source_w3, source_contract, callback_function, erc20_mapping):
    """
    监听Source合约的事件
    """
    logger.info("👂 开始监听Source合约事件...")
    
    # 记录已处理的交易
    processed_txs = set()
    last_block = source_w3.eth.block_number
    
    logger.info(f"📊 起始区块: {last_block}")
    
    while True:
        try:
            current_block = source_w3.eth.block_number
            
            if current_block > last_block:
                logger.info(f"🔄 发现 {current_block - last_block} 个新区块")
                
                # 扫描新区块中的事件
                events = scan_blocks(
                    source_w3,
                    source_contract,
                    'Deposit',
                    last_block + 1,
                    current_block
                )
                
                # 处理事件
                for event in events:
                    tx_hash = event['transactionHash'].hex()
                    
                    if tx_hash not in processed_txs:
                        logger.info(f"📥 处理新事件: {tx_hash}")
                        callback_function(event)
                        processed_txs.add(tx_hash)
                
                last_block = current_block
            else:
                # 显示监听状态
                current_time = time.strftime("%H:%M:%S")
                print(f"⏰ {current_time} - 监听中... 区块: {current_block}", end='\r')
            
            time.sleep(5)  # 5秒检查一次
            
        except KeyboardInterrupt:
            logger.info("\n🛑 停止监听")
            break
        except Exception as e:
            logger.error(f"⚠️ 监听错误: {e}")
            time.sleep(5)

def main():
    """
    主函数 - 启动跨链桥
    """
    print("🌉 启动跨链桥...")
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
    
    # 3. 获取账户
    account = source_w3.eth.account.from_key(private_key)
    print(f"👤 Warden地址: {account.address}")
    
    # 4. 获取合约信息
    source_info = get_contract_info('source', contract_info)
    destination_info = get_contract_info('destination', contract_info)
    
    # 5. 创建合约实例
    source_contract = get_contract_instance(
        source_w3, 
        source_info['address'], 
        source_info['abi']
    )
    
    destination_contract = get_contract_instance(
        destination_w3,
        destination_info['address'],
        destination_info['abi']
    )
    
    print(f"📄 Source合约地址: {source_info['address']}")
    print(f"📄 Destination合约地址: {destination_info['address']}")
    
    # 6. 先扫描历史事件（最近100个区块）
    print("\n📜 扫描历史事件...")
    historical_events = scan_blocks(
        source_w3,
        source_contract,
        'Deposit',
        max(0, source_w3.eth.block_number - 100),
        source_w3.eth.block_number
    )
    
    if historical_events:
        print(f"📦 找到 {len(historical_events)} 个历史事件")
        for event in historical_events:
            handle_deposit_event(
                event, 
                destination_w3, 
                destination_contract, 
                private_key, 
                erc20_mapping
            )
    
    # 7. 设置事件处理回调
    def deposit_callback(event):
        handle_deposit_event(
            event, 
            destination_w3, 
            destination_contract, 
            private_key, 
            erc20_mapping
        )
    
    # 8. 开始监听事件
    print("\n" + "="*50)
    print("🚀 跨链桥已启动!")
    print("="*50)
    
    listen_for_events(source_w3, source_contract, deposit_callback, erc20_mapping)

if __name__ == "__main__":
    main()
