# How to Run SmartTrade AI (Free APIs Only)

## 1. Install Python packages

```
pip install -r requirements.txt
```

## 2. Start the server

```
python run.py
```

## 3. Open browser

Go to: http://127.0.0.1:5000/login

## 4. Login with demo account

Email:    admin@smarttradeai.com
Password: Admin@123

## Free APIs used (NO keys needed)

| Market         | Source              | Key Required? |
|----------------|---------------------|---------------|
| Crypto         | Binance Public API  | NO            |
| Forex          | Yahoo Finance       | NO            |
| Gold / Silver  | Yahoo Finance       | NO            |
| Indian Stocks  | Yahoo Finance       | NO            |
| Indices        | Yahoo Finance       | NO            |

## Notes

- Market data may take 5-10 seconds to load on first visit
- Signal generation runs every hour automatically in background
- To generate a signal manually: go to any market page → click the refresh button on an asset
- The heatmap and ticker load from live market data
