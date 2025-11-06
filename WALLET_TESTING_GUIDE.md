# Multi-Wallet Testing Guide

This guide explains how to test the new multi-wallet provider functionality in OM1.

## 🎯 Features Implemented

- ✅ **EVM Wallet Support**: MetaMask, Coinbase Wallet, and other Web3-compatible wallets
- ✅ **Solana Wallet Support**: Phantom, Solflare, and other Solana-compatible wallets
- ✅ **Connect Functionality**: Seamless wallet connection with network switching
- ✅ **Sign Message**: Message signing for wallet ownership verification
- ✅ **Transfer Tokens**: Native token transfers (ETH on Base Sepolia, SOL on Devnet)
- ✅ **Real-time Updates**: WebSocket-based state synchronization
- ✅ **Multi-chain Support**: Simultaneous connections to both EVM and Solana wallets

## 🚀 Quick Start - Standalone Test Server

The easiest way to test the wallet functionality without the full OM1 stack:

### 1. Install Dependencies

```bash
pip install fastapi uvicorn websockets
```

### 2. Run the Test Server

```bash
python3 test_wallet_server.py
```

### 3. Open in Browser

Navigate to: **http://localhost:8000**

The server will display a beautiful multi-wallet interface where you can test all functionality.

## 🔧 Testing with Full OM1 Stack

If you have the full OM1 environment set up:

### 1. Install System Dependencies (if needed)

```bash
# Ubuntu/Debian
sudo apt-get install portaudio19-dev

# macOS
brew install portaudio
```

### 2. Sync Dependencies

```bash
uv sync
```

### 3. Run with Wallet Config

```bash
uv run python -m src.run start test_multi_wallet
```

This will start the full OM1 runtime with:
- Multi-wallet provider plugin active
- WebSim UI with wallet interface
- LLM integration for wallet event responses

## 💰 Getting Testnet Funds

### Base Sepolia (EVM)

1. **Official Base Faucet**: https://www.base.org/faucet
   - Requires GitHub account with some activity
   - Provides 0.05 ETH per 24 hours

2. **Alternative Faucets**:
   - Alchemy Sepolia Faucet: https://www.alchemy.com/faucets/base-sepolia
   - QuickNode Faucet: https://faucet.quicknode.com/base/sepolia

### Solana Devnet

1. **Official Solana Faucet**: https://faucet.solana.com/
   - Simply enter your wallet address
   - Provides 2 SOL per request

2. **Via Solana CLI** (if installed):
   ```bash
   solana airdrop 2 YOUR_WALLET_ADDRESS --url devnet
   ```

## 🧪 Testing Checklist

### EVM Wallet Tests

- [ ] **Install Wallet**: Install MetaMask or Coinbase Wallet browser extension
- [ ] **Connect Wallet**: Click "Connect EVM Wallet" button
- [ ] **Network Switch**: Verify automatic switch to Base Sepolia (Chain ID: 84532)
- [ ] **Display Address**: Confirm wallet address is displayed correctly
- [ ] **Sign Message**: Test message signing functionality
- [ ] **Transfer Tokens**: Send test ETH to another address
- [ ] **Verify Transaction**: Check transaction on https://sepolia.basescan.org
- [ ] **Disconnect**: Test wallet disconnection

### Solana Wallet Tests

- [ ] **Install Wallet**: Install Phantom wallet browser extension
- [ ] **Switch to Devnet**: In Phantom settings, switch network to Devnet
- [ ] **Connect Wallet**: Click "Connect Solana Wallet" button
- [ ] **Display Address**: Confirm wallet address is displayed correctly
- [ ] **Sign Message**: Test message signing functionality
- [ ] **Transfer Tokens**: Send test SOL to another address
- [ ] **Verify Transaction**: Check transaction on https://solscan.io (Devnet)
- [ ] **Disconnect**: Test wallet disconnection

### Multi-Wallet Tests

- [ ] **Simultaneous Connection**: Connect both EVM and Solana wallets at the same time
- [ ] **Independent Operations**: Perform operations on both chains
- [ ] **State Persistence**: Refresh page and verify connections persist (depending on wallet settings)
- [ ] **Error Handling**: Test with insufficient funds, invalid addresses, etc.

## 📂 File Structure

```
OM1/
├── src/
│   ├── inputs/
│   │   └── plugins/
│   │       └── wallet_multi_provider.py    # Multi-chain wallet provider plugin
│   └── simulators/
│       └── plugins/
│           └── WebSim.py                    # Updated WebSim with wallet UI
├── config/
│   └── test_multi_wallet.json5              # Test configuration
├── test_wallet_server.py                    # Standalone test server
└── WALLET_TESTING_GUIDE.md                  # This file
```

## 🔍 Implementation Details

### WalletMultiProvider Plugin

Location: `src/inputs/plugins/wallet_multi_provider.py`

**Features**:
- Handles wallet connection events for EVM and Solana
- Tracks transaction history
- Provides formatted output for LLM integration
- Supports both polling and event-driven updates

**Key Methods**:
- `handle_wallet_connect()`: Process wallet connection
- `handle_wallet_disconnect()`: Process wallet disconnection
- `handle_transaction()`: Record and track transactions
- `get_wallet_state()`: Get current state of all wallets

### WebSim Wallet UI

Location: `src/simulators/plugins/WebSim.py`

**Features**:
- Beautiful gradient wallet cards
- Real-time connection status
- Activity logging
- Transaction confirmations with explorer links
- Responsive design

**Supported Operations**:
- **Connect**: Browser extension detection and connection
- **Sign**: Message signing for verification
- **Transfer**: Native token transfers
- **Disconnect**: Wallet disconnection

### Network Configuration

**EVM (Base Sepolia)**:
- Chain ID: `0x14a34` (84532 decimal)
- RPC URL: `https://sepolia.base.org`
- Explorer: `https://sepolia.basescan.org`
- Native Token: ETH

**Solana (Devnet)**:
- Cluster: `devnet`
- RPC URL: Via `@solana/web3.js` library
- Explorer: `https://solscan.io/?cluster=devnet`
- Native Token: SOL

## 🐛 Troubleshooting

### "No wallet detected"

**Solution**: Install the appropriate browser extension:
- **EVM**: [MetaMask](https://metamask.io/) or [Coinbase Wallet](https://www.coinbase.com/wallet)
- **Solana**: [Phantom](https://phantom.app/)

### "Insufficient funds for transaction"

**Solution**: Get testnet funds from the faucets listed above.

### "Wrong network" error

**Solution**:
- For EVM: The UI will automatically prompt to add/switch to Base Sepolia
- For Solana: Manually switch to Devnet in Phantom settings (Settings → Developer Settings → Testnet Mode)

### Transaction fails

**Possible causes**:
- Insufficient gas/fees
- Invalid recipient address
- Network congestion (retry after a few seconds)

### WebSocket connection fails

**Solution**:
- Ensure the server is running
- Check firewall settings
- Try refreshing the page

## 📊 Testing Scenarios

### Scenario 1: Basic Connection Test

1. Start test server
2. Open browser to http://localhost:8000
3. Install and connect MetaMask
4. Verify connection status shows "Connected"
5. Check that address is displayed correctly

### Scenario 2: Cross-Chain Operations

1. Connect both MetaMask (EVM) and Phantom (Solana)
2. Sign a message with MetaMask
3. Sign a message with Phantom
4. Verify both operations complete successfully

### Scenario 3: Token Transfer

1. Ensure you have testnet funds
2. Connect wallet
3. Click "Transfer" button
4. Enter valid recipient address
5. Enter amount (e.g., "0.001" ETH or SOL)
6. Approve transaction in wallet
7. Verify transaction hash is displayed
8. Check transaction on block explorer

### Scenario 4: Error Handling

1. Try to transfer without connecting wallet → Should show error
2. Try to transfer more than balance → Should fail gracefully
3. Enter invalid recipient address → Should show error
4. Disconnect wallet mid-operation → Should handle gracefully

## 🎥 Demo Video Requirements

For the OM1 Bounty submission, record a video showing:

1. ✅ **Server Startup**: Show the test server starting
2. ✅ **UI Overview**: Show the wallet interface
3. ✅ **EVM Connection**: Connect MetaMask to Base Sepolia
4. ✅ **EVM Sign**: Sign a message with MetaMask
5. ✅ **EVM Transfer**: Send test ETH and show transaction on BaseScan
6. ✅ **Solana Connection**: Connect Phantom to Devnet
7. ✅ **Solana Sign**: Sign a message with Phantom
8. ✅ **Solana Transfer**: Send test SOL and show transaction on Solscan
9. ✅ **Simultaneous**: Show both wallets connected at the same time
10. ✅ **Activity Log**: Show the activity log tracking all operations

## 📝 Notes

- The standalone test server (`test_wallet_server.py`) is perfect for quick testing and demonstrations
- The full OM1 integration allows the LLM to react to wallet events
- All wallet operations are client-side for security
- Private keys never leave the browser wallet extensions
- The implementation follows OM1's modular plugin architecture

## 🔐 Security Considerations

- ✅ Wallet operations use official wallet extension APIs
- ✅ No private keys are stored or transmitted
- ✅ All transactions require user approval in wallet
- ✅ Testnet networks only (no mainnet exposure)
- ✅ WebSocket state synchronization is read-only

## 🚀 Next Steps

After testing, you can:

1. Integrate with other OM1 actions (speak, move, etc.)
2. Add support for additional wallet types
3. Implement token balance tracking
4. Add NFT support
5. Integrate with DeFi protocols
6. Add multi-signature wallet support

## 📞 Support

For issues or questions:
- GitHub Issues: https://github.com/OpenmindAGI/OM1/issues
- Discord: Check OM1 Discord for the bounty channel

---

**Built with ❤️ for the OM1 Bounty Program**
