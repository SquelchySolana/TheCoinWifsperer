# 🚀 TheCoinWifsperer

A machine learning-powered Solana trading bot that scans new coins via Dexscreener, analyzes on-chain data from Moralis, and (eventually) auto-trades promising SPL tokens.  
This project uses Python, is environment-agnostic, and is built for easy extension and transparency.

---

## 📁 Project Structure

```

/DEX Bot
/data       # Collected market data, features, and trading logs
/scripts    # Python scripts for data collection, ML, trading, etc.
/models     # Saved ML models
/logs       # Log files
requirements.txt
.env.example
ROADMAP.md  # Detailed build steps and task list
README.md   # This file!

````

---

## 🚦 Quickstart

1. **Clone the repository:**
   ```sh
   git clone https://github.com/SquelchySolana/TheCoinWifsperer.git
   cd TheCoinWifsperer
````

2. **Set up your Python environment (recommended):**

   ```sh
   python -m venv venv
   # Activate (Windows)
   .\venv\Scripts\activate
   # Activate (Mac/Linux)
   source venv/bin/activate
   ```

3. **Install dependencies:**

   ```sh
   pip install -r requirements.txt
   ```

4. **Configure your environment variables:**

   * Copy `.env.example` to `.env`:

     ```sh
     cp .env.example .env
     ```
   * Open `.env` and add your API keys and endpoints.

5. **Run your first script (example):**

   ```sh
   python scripts/fetch_dex_data.py
   ```

   *(Replace with whatever script you want to start with.)*

---

## 🔑 Environment Variables (`.env.example`)

**Set your API endpoints and keys here (never share your real keys!):**

```env
DEX_API_BASE=https://api.dexscreener.com
MORALIS_EVM_API_BASE=https://deep-index.moralis.io/api/v2.2
MORALIS_SOLANA_API_BASE=https://solana-gateway.moralis.io
MORALIS_API_KEY=your-moralis-api-key
PUMPFUN_API_BASE=https://api.pump.fun
PUMPFUN_API_KEY=your-pumpfun-api-key
SOLANA_RPC_URL=https://rpc.free.gsnode.io/
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
```

---

## 🛠️ Key APIs and Their Purpose

| Environment Variable       | Used For                                       | Docs Link                                                       |
| -------------------------- | ---------------------------------------------- | --------------------------------------------------------------- |
| DEX\_API\_BASE             | Dexscreener API (coins, pairs, profiles)       | [Dexscreener API](https://docs.dexscreener.com/api/reference)   |
| MORALIS\_EVM\_API\_BASE    | Moralis EVM API (ETH, BSC, etc.)               | [Moralis EVM](https://docs.moralis.com/web3-data-api/evm)       |
| MORALIS\_SOLANA\_API\_BASE | Moralis Solana API (token/price, etc.)         | [Moralis Solana](https://docs.moralis.com/web3-data-api/solana) |
| MORALIS\_API\_KEY          | API key for all Moralis endpoints              |                                                                 |
| PUMPFUN\_API\_BASE         | Pump.fun endpoints                             | [Pump.fun](https://www.pump.fun/) (no official public docs)     |
| PUMPFUN\_API\_KEY          | Pump.fun API key (if required)                 |                                                                 |
| SOLANA\_RPC\_URL           | Solana blockchain RPC (GSnode.io or QuickNode) | [Solana Docs](https://docs.solana.com/cluster/rpc-endpoints)    |
| TELEGRAM\_BOT\_TOKEN       | Telegram bot notifications                     | [Telegram Bots](https://core.telegram.org/bots)                 |

---

## 📖 Roadmap

See `ROADMAP.md` for a detailed, step-by-step build plan.
**Highlights:**

* Data collection from APIs
* Data preparation & feature engineering
* Exploratory data analysis (EDA)
* Machine learning model training & evaluation
* Paper (simulated) trading
* Real on-chain trading with wallet
* Logging, alerts, and deployment

---

## 🧑‍💻 Contributing

PRs and issues are welcome (if you open-source this later)!
All code and config should avoid storing or sharing real secrets—use `.env.example` for templates.

---

## ❗ Security Notice

* **Never commit your `.env` file or real API keys/secrets.**
* All sensitive files and large data should be listed in `.gitignore` (already included).

---

## 📚 References

* [Dexscreener API Docs](https://docs.dexscreener.com/api/reference)
* [Moralis Solana Docs](https://docs.moralis.com/web3-data-api/solana)
* [Pump.fun](https://www.pump.fun/)
* [Solana JSON-RPC Docs](https://docs.solana.com/cluster/rpc-endpoints)

---

## 🙏 Credits

* Built by SquelchySolana with lots of help from ChatGPT and a killer roadmap.

---

```

---

**Copy and paste the above as your `README.md`.**  
You can add, remove, or tweak sections as your project grows. This covers everything Codex, future you, or a new dev would need!

Let me know if you want a `ROADMAP.md` template, or help writing an intro for Codex at the top.
```
