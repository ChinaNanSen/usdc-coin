import asyncio
from src.config import load_config
from src.adapters.okx_adapter import OKXRestClient

async def main():
    config = load_config('config/config.yaml')
    rest = OKXRestClient(config.exchange)
    await rest.start()
    instruments = await rest.get('/api/v5/public/instruments', {'instType': 'SPOT'})
    zero_fee_pairs = []
    
    print('Checking fees using configured credentials...')
    for inst in instruments['data']:
        try:
            # OKX zero fee pairs are typically fiat or stablecoin pairs. To avoid hitting 500 requests, let's filter for stablecoins or major fiat first
            if not ('USDT' in inst['instId'] or 'USDC' in inst['instId'] or 'EUR' in inst['instId']):
                continue
            fee = await rest.fetch_trade_fee('SPOT', inst['instId'])
            maker = float(fee['maker'])
            taker = float(fee['taker'])
            if maker == 0 and taker == 0:
                zero_fee_pairs.append(inst['instId'])
                print(f"Zero fee match: {inst['instId']}")
            await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Error auth for {inst['instId']}: {e}")
            break
    print(f"Final Zero fee pairs found: {zero_fee_pairs}")
    await rest.close()

if __name__ == '__main__':
    asyncio.run(main())
