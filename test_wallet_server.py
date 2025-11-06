#!/usr/bin/env python3
"""
Standalone test server for multi-wallet UI
Run this to test wallet connections without the full OM1 stack.

Usage: python test_wallet_server.py
Then open: http://localhost:8000
"""

import asyncio
import logging
import sys
from typing import Dict, List

# Add src to path
sys.path.insert(0, 'src')

try:
    from fastapi import FastAPI, WebSocket
    from fastapi.responses import HTMLResponse
    import uvicorn
except ImportError:
    print("Installing required packages...")
    import subprocess
    subprocess.check_call([
        sys.executable, "-m", "pip", "install",
        "fastapi", "uvicorn", "websockets"
    ])
    from fastapi import FastAPI, WebSocket
    from fastapi.responses import HTMLResponse
    import uvicorn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Multi-Wallet Test Server")

# Store active WebSocket connections
active_connections: List[WebSocket] = []

# Wallet state
wallet_state = {
    "evm": {"connected": False, "address": None, "chain_id": None},
    "solana": {"connected": False, "address": None, "cluster": None},
}


HTML_CONTENT = """
<!DOCTYPE html>
<html>
    <head>
        <title>OpenMind Multi-Wallet Test</title>
        <meta charset="utf-8">
        <script src="https://unpkg.com/react@17/umd/react.development.js"></script>
        <script src="https://unpkg.com/react-dom@17/umd/react-dom.development.js"></script>
        <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/ethers@5.7.2/dist/ethers.umd.min.js"></script>
        <script src="https://unpkg.com/@solana/web3.js@latest/lib/index.iife.min.js"></script>
        <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
        <style>
            .wallet-card {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                border-radius: 12px;
                padding: 20px;
                color: white;
                margin-bottom: 16px;
            }
            .wallet-card.solana {
                background: linear-gradient(135deg, #14F195 0%, #9945FF 100%);
            }
            .wallet-button {
                background: white;
                color: #667eea;
                padding: 10px 20px;
                border-radius: 8px;
                font-weight: 600;
                cursor: pointer;
                border: none;
                transition: all 0.2s;
            }
            .wallet-button:hover {
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            }
            .wallet-button:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }
            .status-badge {
                display: inline-block;
                padding: 4px 12px;
                border-radius: 12px;
                font-size: 0.75rem;
                font-weight: 600;
                margin-bottom: 8px;
            }
            .status-connected {
                background: #10b981;
                color: white;
            }
            .status-disconnected {
                background: #ef4444;
                color: white;
            }
            .log-entry {
                padding: 8px;
                margin: 4px 0;
                background: #f3f4f6;
                border-radius: 4px;
                font-family: monospace;
                font-size: 0.875rem;
            }
        </style>
    </head>
    <body class="bg-gray-50">
        <div id="root"></div>
        <script type="text/babel">
            const { useState, useEffect } = React;

            function App() {
                const [walletState, setWalletState] = useState({
                    evm: { connected: false, address: null, chain_id: null },
                    solana: { connected: false, address: null, cluster: null }
                });
                const [connected, setConnected] = useState(false);
                const [ws, setWs] = useState(null);
                const [evmProvider, setEvmProvider] = useState(null);
                const [solanaProvider, setSolanaProvider] = useState(null);
                const [logs, setLogs] = useState([]);

                const addLog = (message) => {
                    const timestamp = new Date().toLocaleTimeString();
                    setLogs(prev => [...prev, `[${timestamp}] ${message}`].slice(-10));
                };

                // Initialize WebSocket
                useEffect(() => {
                    const websocket = new WebSocket(`ws://${window.location.host}/ws`);

                    websocket.onopen = () => {
                        console.log('Connected to WebSocket');
                        setConnected(true);
                        setWs(websocket);
                        addLog('✅ Connected to server');
                    };

                    websocket.onmessage = (event) => {
                        const data = JSON.parse(event.data);
                        if (data.wallet_state) {
                            setWalletState(data.wallet_state);
                        }
                    };

                    websocket.onerror = (error) => {
                        console.error('WebSocket error:', error);
                        addLog('❌ Connection error');
                    };

                    websocket.onclose = () => {
                        setConnected(false);
                        addLog('⚠️ Connection lost. Reconnecting...');
                        setTimeout(() => window.location.reload(), 2000);
                    };

                    return () => websocket.close();
                }, []);

                // Initialize wallet providers
                useEffect(() => {
                    if (typeof window.ethereum !== 'undefined') {
                        setEvmProvider(window.ethereum);
                        addLog('🦊 MetaMask detected');
                    } else {
                        addLog('❌ No Ethereum wallet detected');
                    }

                    if (typeof window.solana !== 'undefined' && window.solana.isPhantom) {
                        setSolanaProvider(window.solana);
                        addLog('👻 Phantom wallet detected');
                    } else {
                        addLog('❌ No Solana wallet detected');
                    }
                }, []);

                // EVM Wallet Functions
                const connectEVM = async () => {
                    if (!evmProvider) {
                        alert('Please install MetaMask or another Ethereum wallet!');
                        return;
                    }

                    try {
                        addLog('🔄 Connecting EVM wallet...');
                        const accounts = await evmProvider.request({
                            method: 'eth_requestAccounts'
                        });
                        const chainId = await evmProvider.request({
                            method: 'eth_chainId'
                        });

                        const address = accounts[0];
                        addLog(`✅ EVM wallet connected: ${address.substring(0, 10)}...`);

                        // Try to switch to Base Sepolia
                        try {
                            await evmProvider.request({
                                method: 'wallet_switchEthereumChain',
                                params: [{ chainId: '0x14a34' }],
                            });
                            addLog('✅ Switched to Base Sepolia');
                        } catch (switchError) {
                            if (switchError.code === 4902) {
                                try {
                                    await evmProvider.request({
                                        method: 'wallet_addEthereumChain',
                                        params: [{
                                            chainId: '0x14a34',
                                            chainName: 'Base Sepolia',
                                            nativeCurrency: {
                                                name: 'Ethereum',
                                                symbol: 'ETH',
                                                decimals: 18
                                            },
                                            rpcUrls: ['https://sepolia.base.org'],
                                            blockExplorerUrls: ['https://sepolia.basescan.org']
                                        }]
                                    });
                                    addLog('✅ Added Base Sepolia network');
                                } catch (addError) {
                                    addLog('❌ Failed to add Base Sepolia');
                                }
                            }
                        }

                        if (ws && ws.readyState === WebSocket.OPEN) {
                            ws.send(JSON.stringify({
                                type: 'wallet_connect',
                                chain: 'evm',
                                address: address,
                                metadata: { chainId: chainId }
                            }));
                        }
                    } catch (error) {
                        addLog(`❌ EVM connection error: ${error.message}`);
                    }
                };

                const disconnectEVM = async () => {
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({
                            type: 'wallet_disconnect',
                            chain: 'evm'
                        }));
                    }
                    addLog('🔌 EVM wallet disconnected');
                };

                const signMessageEVM = async () => {
                    if (!evmProvider || !walletState.evm.address) {
                        alert('Please connect your EVM wallet first!');
                        return;
                    }

                    try {
                        addLog('✍️ Signing message...');
                        const message = `Sign this message to verify your wallet ownership.\\nTimestamp: ${Date.now()}`;
                        const signature = await evmProvider.request({
                            method: 'personal_sign',
                            params: [message, walletState.evm.address]
                        });

                        addLog(`✅ Message signed: ${signature.substring(0, 20)}...`);
                        alert(`Message signed!\\nSignature: ${signature.substring(0, 66)}...`);
                    } catch (error) {
                        addLog(`❌ Sign error: ${error.message}`);
                    }
                };

                const transferEVM = async () => {
                    if (!evmProvider || !walletState.evm.address) {
                        alert('Please connect your EVM wallet first!');
                        return;
                    }

                    const toAddress = prompt('Enter recipient address:');
                    if (!toAddress) return;

                    const amount = prompt('Enter amount in ETH:');
                    if (!amount) return;

                    try {
                        addLog(`💸 Transferring ${amount} ETH to ${toAddress.substring(0, 10)}...`);
                        const transactionParameters = {
                            from: walletState.evm.address,
                            to: toAddress,
                            value: '0x' + (parseFloat(amount) * 1e18).toString(16),
                        };

                        const txHash = await evmProvider.request({
                            method: 'eth_sendTransaction',
                            params: [transactionParameters],
                        });

                        addLog(`✅ Transaction sent: ${txHash}`);
                        alert(`Transaction sent!\\nTx Hash: ${txHash}\\nView on BaseScan: https://sepolia.basescan.org/tx/${txHash}`);
                    } catch (error) {
                        addLog(`❌ Transfer error: ${error.message}`);
                    }
                };

                // Solana Wallet Functions
                const connectSolana = async () => {
                    if (!solanaProvider) {
                        alert('Please install Phantom wallet!');
                        return;
                    }

                    try {
                        addLog('🔄 Connecting Solana wallet...');
                        const response = await solanaProvider.connect();
                        const address = response.publicKey.toString();

                        addLog(`✅ Solana wallet connected: ${address.substring(0, 10)}...`);

                        if (ws && ws.readyState === WebSocket.OPEN) {
                            ws.send(JSON.stringify({
                                type: 'wallet_connect',
                                chain: 'solana',
                                address: address,
                                metadata: { cluster: 'devnet' }
                            }));
                        }
                    } catch (error) {
                        addLog(`❌ Solana connection error: ${error.message}`);
                    }
                };

                const disconnectSolana = async () => {
                    if (solanaProvider) {
                        await solanaProvider.disconnect();
                    }

                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({
                            type: 'wallet_disconnect',
                            chain: 'solana'
                        }));
                    }
                    addLog('🔌 Solana wallet disconnected');
                };

                const signMessageSolana = async () => {
                    if (!solanaProvider || !walletState.solana.address) {
                        alert('Please connect your Solana wallet first!');
                        return;
                    }

                    try {
                        addLog('✍️ Signing message...');
                        const message = `Sign this message to verify your wallet ownership.\\nTimestamp: ${Date.now()}`;
                        const encodedMessage = new TextEncoder().encode(message);
                        const signedMessage = await solanaProvider.signMessage(encodedMessage, "utf8");

                        addLog(`✅ Message signed: ${signedMessage.signature.toString().substring(0, 20)}...`);
                        alert(`Message signed!\\nSignature: ${signedMessage.signature.toString().substring(0, 66)}...`);
                    } catch (error) {
                        addLog(`❌ Sign error: ${error.message}`);
                    }
                };

                const transferSolana = async () => {
                    if (!solanaProvider || !walletState.solana.address) {
                        alert('Please connect your Solana wallet first!');
                        return;
                    }

                    const toAddress = prompt('Enter recipient Solana address:');
                    if (!toAddress) return;

                    const amount = prompt('Enter amount in SOL:');
                    if (!amount) return;

                    try {
                        addLog(`💸 Transferring ${amount} SOL to ${toAddress.substring(0, 10)}...`);
                        const lamports = parseFloat(amount) * 1e9;

                        const connection = new solanaWeb3.Connection(
                            solanaWeb3.clusterApiUrl('devnet'),
                            'confirmed'
                        );

                        const transaction = new solanaWeb3.Transaction().add(
                            solanaWeb3.SystemProgram.transfer({
                                fromPubkey: solanaProvider.publicKey,
                                toPubkey: new solanaWeb3.PublicKey(toAddress),
                                lamports: lamports,
                            })
                        );

                        transaction.feePayer = solanaProvider.publicKey;
                        const { blockhash } = await connection.getRecentBlockhash();
                        transaction.recentBlockhash = blockhash;

                        const signed = await solanaProvider.signAndSendTransaction(transaction);
                        const txHash = signed.signature;

                        addLog(`✅ Transaction sent: ${txHash}`);
                        alert(`Transaction sent!\\nTx Hash: ${txHash}\\nView on Solscan: https://solscan.io/tx/${txHash}?cluster=devnet`);
                    } catch (error) {
                        addLog(`❌ Transfer error: ${error.message}`);
                    }
                };

                return (
                    <div className="min-h-screen p-4">
                        <div className="container mx-auto max-w-6xl">
                            <header className="text-center mb-8">
                                <h1 className="text-4xl font-bold mb-2">🔐 Multi-Wallet Test Interface</h1>
                                <p className="text-gray-600">Test EVM and Solana wallet connections</p>
                                <div className="mt-4">
                                    <span className={`status-badge ${connected ? 'status-connected' : 'status-disconnected'}`}>
                                        {connected ? '✅ Server Connected' : '❌ Server Disconnected'}
                                    </span>
                                </div>
                            </header>

                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
                                {/* EVM Wallet */}
                                <div className="wallet-card">
                                    <h3 className="text-2xl font-bold mb-2">⛓️ EVM Wallet</h3>
                                    <p className="text-sm mb-3 opacity-90">MetaMask, Coinbase Wallet, etc.</p>

                                    {walletState.evm.connected ? (
                                        <div>
                                            <div className="status-badge status-connected mb-3">Connected</div>
                                            <p className="text-sm mb-2 font-mono bg-white bg-opacity-20 p-2 rounded">
                                                {walletState.evm.address?.substring(0, 10)}...
                                                {walletState.evm.address?.substring(walletState.evm.address.length - 8)}
                                            </p>
                                            <p className="text-xs mb-3 opacity-75">
                                                Chain ID: {walletState.evm.chain_id}
                                            </p>
                                            <div className="flex flex-wrap gap-2">
                                                <button className="wallet-button text-sm" onClick={signMessageEVM}>
                                                    ✍️ Sign Message
                                                </button>
                                                <button className="wallet-button text-sm" onClick={transferEVM}>
                                                    💸 Transfer
                                                </button>
                                                <button className="wallet-button text-sm" onClick={disconnectEVM}>
                                                    🔌 Disconnect
                                                </button>
                                            </div>
                                        </div>
                                    ) : (
                                        <div>
                                            <div className="status-badge status-disconnected mb-3">Disconnected</div>
                                            <button
                                                className="wallet-button w-full"
                                                onClick={connectEVM}
                                                disabled={!evmProvider}
                                            >
                                                {evmProvider ? '🔗 Connect EVM Wallet' : '❌ No EVM Wallet Detected'}
                                            </button>
                                        </div>
                                    )}
                                </div>

                                {/* Solana Wallet */}
                                <div className="wallet-card solana">
                                    <h3 className="text-2xl font-bold mb-2">☀️ Solana Wallet</h3>
                                    <p className="text-sm mb-3 opacity-90">Phantom, Solflare, etc.</p>

                                    {walletState.solana.connected ? (
                                        <div>
                                            <div className="status-badge status-connected mb-3">Connected</div>
                                            <p className="text-sm mb-2 font-mono bg-white bg-opacity-20 p-2 rounded">
                                                {walletState.solana.address?.substring(0, 10)}...
                                                {walletState.solana.address?.substring(walletState.solana.address.length - 8)}
                                            </p>
                                            <p className="text-xs mb-3 opacity-75">
                                                Cluster: {walletState.solana.cluster}
                                            </p>
                                            <div className="flex flex-wrap gap-2">
                                                <button className="wallet-button text-sm" onClick={signMessageSolana}>
                                                    ✍️ Sign Message
                                                </button>
                                                <button className="wallet-button text-sm" onClick={transferSolana}>
                                                    💸 Transfer
                                                </button>
                                                <button className="wallet-button text-sm" onClick={disconnectSolana}>
                                                    🔌 Disconnect
                                                </button>
                                            </div>
                                        </div>
                                    ) : (
                                        <div>
                                            <div className="status-badge status-disconnected mb-3">Disconnected</div>
                                            <button
                                                className="wallet-button w-full"
                                                onClick={connectSolana}
                                                disabled={!solanaProvider}
                                            >
                                                {solanaProvider ? '🔗 Connect Solana Wallet' : '❌ No Solana Wallet Detected'}
                                            </button>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* Activity Log */}
                            <div className="bg-white rounded-lg shadow p-6">
                                <h2 className="text-2xl font-bold mb-4">📋 Activity Log</h2>
                                <div className="space-y-1 max-h-96 overflow-y-auto">
                                    {logs.length === 0 ? (
                                        <p className="text-gray-400 italic">No activity yet...</p>
                                    ) : (
                                        logs.map((log, i) => (
                                            <div key={i} className="log-entry">{log}</div>
                                        ))
                                    )}
                                </div>
                            </div>

                            {/* Instructions */}
                            <div className="mt-6 bg-blue-50 border border-blue-200 rounded-lg p-6">
                                <h3 className="text-xl font-bold mb-3 text-blue-900">📚 Testing Instructions</h3>
                                <div className="space-y-2 text-sm text-blue-800">
                                    <p><strong>EVM (Base Sepolia):</strong></p>
                                    <ul className="list-disc ml-6">
                                        <li>Install MetaMask or Coinbase Wallet browser extension</li>
                                        <li>Get testnet ETH from <a href="https://www.base.org/faucet" target="_blank" className="underline">Base Sepolia Faucet</a></li>
                                        <li>Click "Connect EVM Wallet" and approve the connection</li>
                                        <li>Test signing messages and transfers</li>
                                    </ul>
                                    <p className="mt-4"><strong>Solana (Devnet):</strong></p>
                                    <ul className="list-disc ml-6">
                                        <li>Install Phantom wallet browser extension</li>
                                        <li>Switch to Devnet in Phantom settings</li>
                                        <li>Get testnet SOL from <a href="https://faucet.solana.com/" target="_blank" className="underline">Solana Faucet</a></li>
                                        <li>Click "Connect Solana Wallet" and approve the connection</li>
                                        <li>Test signing messages and transfers</li>
                                    </ul>
                                </div>
                            </div>
                        </div>
                    </div>
                );
            }

            ReactDOM.render(<App />, document.getElementById('root'));
        </script>
    </body>
</html>
"""


@app.get("/")
async def get_index():
    """Serve the wallet test UI"""
    return HTMLResponse(HTML_CONTENT)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle WebSocket connections for real-time wallet state updates"""
    await websocket.accept()
    active_connections.append(websocket)
    logger.info(f"Client connected. Total connections: {len(active_connections)}")

    try:
        # Send initial state
        await websocket.send_json({"wallet_state": wallet_state})

        # Listen for messages
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")

            if msg_type == "wallet_connect":
                chain = message.get("chain")
                address = message.get("address")
                metadata = message.get("metadata", {})

                if chain == "evm":
                    wallet_state["evm"] = {
                        "connected": True,
                        "address": address,
                        "chain_id": metadata.get("chainId"),
                    }
                    logger.info(f"EVM wallet connected: {address}")
                elif chain == "solana":
                    wallet_state["solana"] = {
                        "connected": True,
                        "address": address,
                        "cluster": metadata.get("cluster", "devnet"),
                    }
                    logger.info(f"Solana wallet connected: {address}")

                # Broadcast to all clients
                await broadcast_state()

            elif msg_type == "wallet_disconnect":
                chain = message.get("chain")
                if chain in wallet_state:
                    wallet_state[chain] = {
                        "connected": False,
                        "address": None,
                    }
                    logger.info(f"{chain.upper()} wallet disconnected")
                    await broadcast_state()

            elif msg_type == "transaction":
                chain = message.get("chain")
                tx_hash = message.get("txHash")
                logger.info(f"{chain.upper()} transaction: {tx_hash}")

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        active_connections.remove(websocket)
        logger.info(f"Client disconnected. Total connections: {len(active_connections)}")


async def broadcast_state():
    """Broadcast wallet state to all connected clients"""
    if not active_connections:
        return

    disconnected = []
    for connection in active_connections:
        try:
            await connection.send_json({"wallet_state": wallet_state})
        except Exception as e:
            logger.error(f"Error broadcasting to client: {e}")
            disconnected.append(connection)

    for connection in disconnected:
        try:
            active_connections.remove(connection)
        except ValueError:
            pass


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "connections": len(active_connections),
        "wallets": wallet_state
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Multi-Wallet Test Server')
    parser.add_argument('--port', type=int, default=8001, help='Port to run the server on (default: 8001)')
    args = parser.parse_args()

    port = args.port

    logger.info("=" * 60)
    logger.info("Multi-Wallet Test Server Starting...")
    logger.info("=" * 60)
    logger.info("")
    logger.info(f"🌐 Server will be available at: http://localhost:{port}")
    logger.info("")
    logger.info("📝 Testing Instructions:")
    logger.info(f"  1. Open http://localhost:{port} in your browser")
    logger.info("  2. Install MetaMask and/or Phantom wallet extensions")
    logger.info("  3. Get testnet funds:")
    logger.info("     - Base Sepolia ETH: https://www.base.org/faucet")
    logger.info("     - Solana Devnet SOL: https://faucet.solana.com/")
    logger.info("  4. Test connect, sign, and transfer functions")
    logger.info("")
    logger.info("=" * 60)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
