import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from llm.output_model import Action
from providers.io_provider import Input, IOProvider
from simulators.base import Simulator, SimulatorConfig


@dataclass
class SimulatorState:
    inputs: dict
    current_action: str = "idle"
    last_speech: str = ""
    current_emotion: str = ""
    system_latency: Optional[dict] = None
    wallet_state: Optional[dict] = None

    def to_dict(self):
        return asdict(self)


class WebSim(Simulator):
    """
    WebSim simulator class for visualizing simulation data in a web interface.
    Now includes multi-chain wallet support (EVM + Solana).
    """

    def __init__(self, config: SimulatorConfig):
        super().__init__(config)
        self.messages: list[str] = []
        self.io_provider = IOProvider()

        self._initialized = False
        self._lock = threading.Lock()
        self._last_tick = time.time()
        self._tick_interval = 0.1  # 100ms tick rate

        self.state_dict = {}
        self.wallet_provider = None  # Will be set if WalletMultiProvider is active

        # Initialize state
        self.state = SimulatorState(
            inputs={},
            current_action="idle",
            last_speech="",
            current_emotion="",
            system_latency={
                "fuse_time": 0,
                "llm_start": 0,
                "processing": 0,
                "complete": 0,
            },
            wallet_state={
                "evm": {"connected": False, "address": None, "chain_id": None},
                "solana": {"connected": False, "address": None, "cluster": None},
            },
        )

        logging.info("Initializing WebSim with Wallet Support...")

        # Initialize FastAPI app
        self.app = FastAPI()

        # Mount assets directory
        assets_path = os.path.join(os.path.dirname(__file__), "assets")
        if not os.path.exists(assets_path):
            os.makedirs(assets_path)
        self.app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

        # Ensure the logo exists in assets directory
        logo_path = os.path.join(assets_path, "OM_Logo_b_transparent.png")
        if not os.path.exists(logo_path):
            logging.warning(f"Logo not found at {logo_path}")

        self.active_connections: List[WebSocket] = []

        # Setup routes
        @self.app.get("/")
        async def get_index():
            return HTMLResponse(self.get_html())

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self.active_connections.append(websocket)
            try:
                await websocket.send_json(self.state.to_dict())
                while True:
                    message = await websocket.receive_json()
                    await self.handle_wallet_message(message, websocket)
            except Exception as e:
                logging.error(f"WebSocket error: {e}")
            finally:
                self.active_connections.remove(websocket)

        @self.app.post("/api/wallet/connect")
        async def wallet_connect(data: dict):
            """Handle wallet connection"""
            chain = data.get("chain")
            address = data.get("address")
            metadata = data.get("metadata", {})

            if chain == "evm":
                self.state.wallet_state["evm"] = {
                    "connected": True,
                    "address": address,
                    "chain_id": metadata.get("chainId"),
                }
            elif chain == "solana":
                self.state.wallet_state["solana"] = {
                    "connected": True,
                    "address": address,
                    "cluster": metadata.get("cluster", "devnet"),
                }

            logging.info(f"{chain.upper()} wallet connected: {address}")
            await self.broadcast_state()
            return {"success": True}

        @self.app.post("/api/wallet/disconnect")
        async def wallet_disconnect(data: dict):
            """Handle wallet disconnection"""
            chain = data.get("chain")

            if chain in self.state.wallet_state:
                self.state.wallet_state[chain] = {
                    "connected": False,
                    "address": None,
                }

            logging.info(f"{chain.upper()} wallet disconnected")
            await self.broadcast_state()
            return {"success": True}

        # Start server thread
        try:
            logging.info("Starting WebSim server thread...")
            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()
            time.sleep(1)

            if self.server_thread.is_alive():
                logging.info(
                    "\033[1;36mWebSim server started successfully - Open http://localhost:8000 in your browser\033[0m"
                )
                self._initialized = True
            else:
                logging.error("WebSim server failed to start")
        except Exception as e:
            logging.error(f"Error starting WebSim server thread: {e}")

    async def handle_wallet_message(self, message: dict, websocket: WebSocket):
        """Handle wallet-related WebSocket messages"""
        msg_type = message.get("type")

        if msg_type == "wallet_connect":
            # Handle wallet connection
            chain = message.get("chain")
            address = message.get("address")
            metadata = message.get("metadata", {})

            if chain == "evm":
                self.state.wallet_state["evm"] = {
                    "connected": True,
                    "address": address,
                    "chain_id": metadata.get("chainId"),
                }
            elif chain == "solana":
                self.state.wallet_state["solana"] = {
                    "connected": True,
                    "address": address,
                    "cluster": metadata.get("cluster", "devnet"),
                }

            logging.info(f"{chain.upper()} wallet connected: {address}")
            await self.broadcast_state()

        elif msg_type == "wallet_disconnect":
            chain = message.get("chain")
            if chain in self.state.wallet_state:
                self.state.wallet_state[chain] = {
                    "connected": False,
                    "address": None,
                }
            logging.info(f"{chain.upper()} wallet disconnected")
            await self.broadcast_state()

        elif msg_type == "transaction":
            # Log transaction
            chain = message.get("chain")
            tx_hash = message.get("txHash")
            logging.info(f"{chain.upper()} transaction: {tx_hash}")
            await websocket.send_json({"type": "transaction_confirmed", "txHash": tx_hash})

    def get_html(self) -> str:
        """Generate the HTML for the web interface with wallet support"""
        return """
<!DOCTYPE html>
<html>
    <head>
        <title>OpenMind Simulator - Multi-Wallet</title>
        <meta charset="utf-8">
        <script src="https://unpkg.com/react@17/umd/react.development.js"></script>
        <script src="https://unpkg.com/react-dom@17/umd/react-dom.development.js"></script>
        <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
        <script src="https://cdn.ethers.io/lib/ethers-5.6.umd.min.js"></script>
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
            .message-header {
                cursor: pointer;
                padding: 8px;
                border-radius: 4px;
                background-color: #f3f4f6;
                transition: background-color 0.2s;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .message-header:hover {
                background-color: #e5e7eb;
            }
            .footer {
                position: fixed;
                bottom: 0;
                left: 0;
                right: 0;
                padding: 1rem;
                background-color: white;
                border-top: 1px solid #e5e7eb;
                display: flex;
                align-items: center;
                justify-content: space-between;
            }
        </style>
    </head>
    <body class="bg-gray-50">
        <div id="root"></div>
        <script type="text/babel">
            const { useState, useEffect, useCallback } = React;

            function App() {
                const [state, setState] = useState({
                    inputs: {},
                    current_action: "idle",
                    last_speech: "",
                    current_emotion: "",
                    system_latency: {
                        fuse_time: 0,
                        llm_start: 0,
                        processing: 0,
                        complete: 0
                    },
                    wallet_state: {
                        evm: { connected: false, address: null, chain_id: null },
                        solana: { connected: false, address: null, cluster: null }
                    }
                });
                const [error, setError] = useState(null);
                const [connected, setConnected] = useState(false);
                const [ws, setWs] = useState(null);
                const [evmProvider, setEvmProvider] = useState(null);
                const [solanaProvider, setSolanaProvider] = useState(null);

                // Initialize WebSocket
                useEffect(() => {
                    const websocket = new WebSocket(`ws://${window.location.host}/ws`);

                    websocket.onopen = () => {
                        console.log('Connected to WebSocket');
                        setConnected(true);
                        setWs(websocket);
                    };

                    websocket.onmessage = (event) => {
                        const data = JSON.parse(event.data);
                        setState(data);
                    };

                    websocket.onerror = (error) => {
                        console.error('WebSocket error:', error);
                        setError('Failed to connect to server');
                    };

                    websocket.onclose = () => {
                        setConnected(false);
                        setError('Connection lost. Reconnecting...');
                        setTimeout(() => window.location.reload(), 2000);
                    };

                    return () => websocket.close();
                }, []);

                // Initialize wallet providers
                useEffect(() => {
                    // Check for Ethereum provider (MetaMask, etc.)
                    if (typeof window.ethereum !== 'undefined') {
                        setEvmProvider(window.ethereum);
                    }

                    // Check for Solana provider (Phantom, etc.)
                    if (typeof window.solana !== 'undefined' && window.solana.isPhantom) {
                        setSolanaProvider(window.solana);
                    }
                }, []);

                // EVM Wallet Functions
                const connectEVM = async () => {
                    if (!evmProvider) {
                        alert('Please install MetaMask or another Ethereum wallet!');
                        return;
                    }

                    try {
                        const accounts = await evmProvider.request({
                            method: 'eth_requestAccounts'
                        });
                        const chainId = await evmProvider.request({
                            method: 'eth_chainId'
                        });

                        const address = accounts[0];

                        // Try to switch to Base Sepolia (chainId: 0x14a34 = 84532)
                        try {
                            await evmProvider.request({
                                method: 'wallet_switchEthereumChain',
                                params: [{ chainId: '0x14a34' }],
                            });
                        } catch (switchError) {
                            // Chain not added, try to add it
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
                                } catch (addError) {
                                    console.error('Failed to add Base Sepolia:', addError);
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
                        console.error('EVM connection error:', error);
                        alert('Failed to connect EVM wallet: ' + error.message);
                    }
                };

                const disconnectEVM = async () => {
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({
                            type: 'wallet_disconnect',
                            chain: 'evm'
                        }));
                    }
                };

                const signMessageEVM = async () => {
                    if (!evmProvider || !state.wallet_state.evm.address) {
                        alert('Please connect your EVM wallet first!');
                        return;
                    }

                    try {
                        const message = `Sign this message to verify your wallet ownership.\\nTimestamp: ${Date.now()}`;
                        const signature = await evmProvider.request({
                            method: 'personal_sign',
                            params: [message, state.wallet_state.evm.address]
                        });

                        alert(`Message signed!\\nSignature: ${signature.substring(0, 20)}...`);
                    } catch (error) {
                        console.error('Sign error:', error);
                        alert('Failed to sign message: ' + error.message);
                    }
                };

                const transferEVM = async () => {
                    if (!evmProvider || !state.wallet_state.evm.address) {
                        alert('Please connect your EVM wallet first!');
                        return;
                    }

                    const toAddress = prompt('Enter recipient address:');
                    if (!toAddress) return;

                    const amount = prompt('Enter amount in ETH:');
                    if (!amount) return;

                    try {
                        const transactionParameters = {
                            from: state.wallet_state.evm.address,
                            to: toAddress,
                            value: '0x' + (parseFloat(amount) * 1e18).toString(16),
                        };

                        const txHash = await evmProvider.request({
                            method: 'eth_sendTransaction',
                            params: [transactionParameters],
                        });

                        if (ws && ws.readyState === WebSocket.OPEN) {
                            ws.send(JSON.stringify({
                                type: 'transaction',
                                chain: 'evm',
                                txHash: txHash,
                                from: state.wallet_state.evm.address,
                                to: toAddress,
                                amount: amount
                            }));
                        }

                        alert(`Transaction sent!\\nTx Hash: ${txHash}`);
                    } catch (error) {
                        console.error('Transfer error:', error);
                        alert('Failed to send transaction: ' + error.message);
                    }
                };

                // Solana Wallet Functions
                const connectSolana = async () => {
                    if (!solanaProvider) {
                        alert('Please install Phantom wallet!');
                        return;
                    }

                    try {
                        const response = await solanaProvider.connect();
                        const address = response.publicKey.toString();

                        if (ws && ws.readyState === WebSocket.OPEN) {
                            ws.send(JSON.stringify({
                                type: 'wallet_connect',
                                chain: 'solana',
                                address: address,
                                metadata: { cluster: 'devnet' }
                            }));
                        }
                    } catch (error) {
                        console.error('Solana connection error:', error);
                        alert('Failed to connect Solana wallet: ' + error.message);
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
                };

                const signMessageSolana = async () => {
                    if (!solanaProvider || !state.wallet_state.solana.address) {
                        alert('Please connect your Solana wallet first!');
                        return;
                    }

                    try {
                        const message = `Sign this message to verify your wallet ownership.\\nTimestamp: ${Date.now()}`;
                        const encodedMessage = new TextEncoder().encode(message);
                        const signedMessage = await solanaProvider.signMessage(encodedMessage, "utf8");

                        alert(`Message signed!\\nSignature: ${signedMessage.signature.toString().substring(0, 20)}...`);
                    } catch (error) {
                        console.error('Sign error:', error);
                        alert('Failed to sign message: ' + error.message);
                    }
                };

                const transferSolana = async () => {
                    if (!solanaProvider || !state.wallet_state.solana.address) {
                        alert('Please connect your Solana wallet first!');
                        return;
                    }

                    const toAddress = prompt('Enter recipient Solana address:');
                    if (!toAddress) return;

                    const amount = prompt('Enter amount in SOL:');
                    if (!amount) return;

                    try {
                        const lamports = parseFloat(amount) * 1e9; // Convert SOL to lamports

                        // Create connection to Solana devnet
                        const connection = new solanaWeb3.Connection(
                            solanaWeb3.clusterApiUrl('devnet'),
                            'confirmed'
                        );

                        // Create transaction
                        const transaction = new solanaWeb3.Transaction().add(
                            solanaWeb3.SystemProgram.transfer({
                                fromPubkey: solanaProvider.publicKey,
                                toPubkey: new solanaWeb3.PublicKey(toAddress),
                                lamports: lamports,
                            })
                        );

                        // Get recent blockhash
                        transaction.feePayer = solanaProvider.publicKey;
                        const { blockhash } = await connection.getRecentBlockhash();
                        transaction.recentBlockhash = blockhash;

                        // Sign and send transaction
                        const signed = await solanaProvider.signAndSendTransaction(transaction);
                        const txHash = signed.signature;

                        if (ws && ws.readyState === WebSocket.OPEN) {
                            ws.send(JSON.stringify({
                                type: 'transaction',
                                chain: 'solana',
                                txHash: txHash,
                                from: state.wallet_state.solana.address,
                                to: toAddress,
                                amount: amount
                            }));
                        }

                        alert(`Transaction sent!\\nTx Hash: ${txHash}\\nView on Solscan: https://solscan.io/tx/${txHash}?cluster=devnet`);
                    } catch (error) {
                        console.error('Transfer error:', error);
                        alert('Failed to send transaction: ' + error.message);
                    }
                };

                if (error) {
                    return (
                        <div className="min-h-screen flex items-center justify-center">
                            <div className="text-red-600">{error}</div>
                        </div>
                    );
                }

                if (!connected) {
                    return (
                        <div className="min-h-screen flex items-center justify-center">
                            <div>Connecting...</div>
                        </div>
                    );
                }

                return (
                    <div className="min-h-screen p-4 pb-24">
                        <div className="container mx-auto">
                            <h1 className="text-3xl font-bold mb-6 text-center">
                                OpenMind Multi-Wallet Interface
                            </h1>

                            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                                {/* Wallet Column */}
                                <div>
                                    <h2 className="text-2xl font-bold mb-4">Wallets</h2>

                                    {/* EVM Wallet */}
                                    <div className="wallet-card">
                                        <h3 className="text-xl font-bold mb-2">EVM Wallet</h3>
                                        <p className="text-sm mb-3 opacity-90">MetaMask, Coinbase Wallet</p>

                                        {state.wallet_state.evm.connected ? (
                                            <>
                                                <p className="text-sm mb-2 font-mono">
                                                    {state.wallet_state.evm.address?.substring(0, 10)}...
                                                    {state.wallet_state.evm.address?.substring(state.wallet_state.evm.address.length - 8)}
                                                </p>
                                                <p className="text-xs mb-3 opacity-75">
                                                    Chain ID: {state.wallet_state.evm.chain_id}
                                                </p>
                                                <div className="flex flex-wrap gap-2">
                                                    <button className="wallet-button text-sm" onClick={signMessageEVM}>
                                                        Sign Message
                                                    </button>
                                                    <button className="wallet-button text-sm" onClick={transferEVM}>
                                                        Transfer
                                                    </button>
                                                    <button className="wallet-button text-sm" onClick={disconnectEVM}>
                                                        Disconnect
                                                    </button>
                                                </div>
                                            </>
                                        ) : (
                                            <button className="wallet-button" onClick={connectEVM}>
                                                Connect EVM Wallet
                                            </button>
                                        )}
                                    </div>

                                    {/* Solana Wallet */}
                                    <div className="wallet-card solana">
                                        <h3 className="text-xl font-bold mb-2">Solana Wallet</h3>
                                        <p className="text-sm mb-3 opacity-90">Phantom, Solflare</p>

                                        {state.wallet_state.solana.connected ? (
                                            <>
                                                <p className="text-sm mb-2 font-mono">
                                                    {state.wallet_state.solana.address?.substring(0, 10)}...
                                                    {state.wallet_state.solana.address?.substring(state.wallet_state.solana.address.length - 8)}
                                                </p>
                                                <p className="text-xs mb-3 opacity-75">
                                                    Cluster: {state.wallet_state.solana.cluster}
                                                </p>
                                                <div className="flex flex-wrap gap-2">
                                                    <button className="wallet-button text-sm" onClick={signMessageSolana}>
                                                        Sign Message
                                                    </button>
                                                    <button className="wallet-button text-sm" onClick={transferSolana}>
                                                        Transfer
                                                    </button>
                                                    <button className="wallet-button text-sm" onClick={disconnectSolana}>
                                                        Disconnect
                                                    </button>
                                                </div>
                                            </>
                                        ) : (
                                            <button className="wallet-button" onClick={connectSolana}>
                                                Connect Solana Wallet
                                            </button>
                                        )}
                                    </div>
                                </div>

                                {/* Input History Column */}
                                <div className="bg-white rounded-lg shadow p-4">
                                    <h2 className="text-xl font-bold mb-4">Input History</h2>
                                    <div className="space-y-2 max-h-96 overflow-y-auto">
                                        {Object.entries(state.inputs || {}).map(([key, value]) => (
                                            <div key={key} className="message-header">
                                                <span className="text-sm">{value.input_type || 'Unknown'}</span>
                                                <span className="text-xs text-gray-500">
                                                    {value.timestamp?.toFixed(2)}s
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                {/* Status Column */}
                                <div>
                                    <div className="bg-white rounded-lg shadow p-4 mb-4">
                                        <h2 className="text-xl font-bold mb-4">Current State</h2>
                                        <div className="space-y-3">
                                            <div>
                                                <span className="font-semibold">Action:</span>
                                                <span className="ml-2 text-blue-600">{state.current_action}</span>
                                            </div>
                                            <div>
                                                <span className="font-semibold">Emotion:</span>
                                                <span className="ml-2 text-purple-600">{state.current_emotion}</span>
                                            </div>
                                        </div>
                                    </div>

                                    <div className="bg-white rounded-lg shadow p-4">
                                        <h2 className="text-xl font-bold mb-4">System Latency</h2>
                                        <div className="space-y-2">
                                            {Object.entries(state.system_latency || {}).map(([key, value]) => (
                                                <div key={key} className="flex justify-between">
                                                    <span className="font-semibold text-sm">{key}:</span>
                                                    <span className="text-gray-600 text-sm">
                                                        {value ? value.toFixed(3) : '0.000'}s
                                                    </span>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div className="footer">
                            <img
                                src="/assets/OM_Logo_b_transparent.png"
                                alt="OpenMind Logo"
                                style={{height: '60px'}}
                            />
                            <div style={{display: 'flex', gap: '2rem'}}>
                                <a
                                    href="https://github.com/OpenmindAGI/OM1"
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-blue-600 hover:text-blue-800 font-medium"
                                >
                                    GitHub
                                </a>
                                <a
                                    href="https://docs.openmind.org/introduction"
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-blue-600 hover:text-blue-800 font-medium"
                                >
                                    Documentation
                                </a>
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

    def _run_server(self):
        """Run the FastAPI server"""
        config = uvicorn.Config(
            app=self.app,
            host="0.0.0.0",
            port=8000,
            log_level="error",
            server_header=False,
            log_config={
                "version": 1,
                "disable_existing_loggers": False,
                "formatters": {
                    "default": {
                        "()": "uvicorn.logging.DefaultFormatter",
                        "fmt": "%(message)s",
                    },
                },
                "handlers": {
                    "default": {
                        "formatter": "default",
                        "class": "logging.StreamHandler",
                        "stream": "ext://sys.stderr",
                    },
                },
                "loggers": {
                    "uvicorn": {"handlers": ["default"], "level": "ERROR"},
                    "uvicorn.error": {"level": "ERROR"},
                },
            },
        )
        server = uvicorn.Server(config)
        server.run()

    async def broadcast_state(self):
        """Broadcast current state to all connected clients"""
        if not self.active_connections:
            return

        try:
            disconnected = []
            for connection in self.active_connections:
                try:
                    await connection.send_json(self.state_dict)
                except Exception as e:
                    logging.error(f"Error broadcasting to client: {e}")
                    disconnected.append(connection)

            for connection in disconnected:
                try:
                    self.active_connections.remove(connection)
                except ValueError:
                    pass

        except Exception as e:
            logging.error(f"Error in broadcast_state: {e}")

    def get_earliest_time(self, inputs: Dict[str, Input]) -> float:
        """Get earliest timestamp from inputs"""
        earliest_time = float("inf")
        for input_type, input_info in inputs.items():
            if input_type in ["GovernanceEthereum", "Universal Laws"]:
                continue
            if input_info.timestamp is not None:
                if input_info.timestamp < earliest_time:
                    earliest_time = float(input_info.timestamp)
        return earliest_time if earliest_time != float("inf") else 0.0

    def tick(self) -> None:
        """Update simulator state"""
        if self._initialized:
            try:
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                try:
                    loop.run_until_complete(self.broadcast_state())
                except Exception:
                    loop = asyncio.get_event_loop()
                    loop.create_task(self.broadcast_state())

            except Exception as e:
                logging.error(f"Error in tick: {e}")

            time.sleep(0.5)

    def sim(self, actions: List[Action]) -> None:
        """Handle simulation updates from commands"""
        if not self._initialized:
            logging.warning("WebSim not initialized, skipping sim update")
            return

        try:
            updated = False
            with self._lock:
                earliest_time = self.get_earliest_time(self.io_provider.inputs)

                input_rezeroed = []
                for input_type, input_info in self.io_provider.inputs.items():
                    timestamp = 0
                    if (
                        input_type != "GovernanceEthereum"
                        and input_info.timestamp is not None
                    ):
                        timestamp = input_info.timestamp - earliest_time
                    input_rezeroed.append(
                        {
                            "input_type": input_type,
                            "timestamp": timestamp,
                            "input": input_info.input,
                        }
                    )

                # Process system latency relative to earliest time
                fuser_end_time = self.io_provider.fuser_end_time or 0
                llm_start_time = self.io_provider.llm_start_time or 0
                llm_end_time = self.io_provider.llm_end_time or 0

                system_latency = {
                    "fuse_time": (
                        fuser_end_time - earliest_time if fuser_end_time else 0
                    ),
                    "llm_start": (
                        llm_start_time - earliest_time if llm_start_time else 0
                    ),
                    "processing": (
                        llm_end_time - llm_start_time
                        if (llm_end_time and llm_start_time)
                        else 0
                    ),
                    "complete": llm_end_time - earliest_time if llm_end_time else 0,
                }

                for action in actions:
                    if action.type == "move":
                        new_action = action.value
                        if new_action != self.state.current_action:
                            self.state.current_action = new_action
                            updated = True
                    elif action.type == "speak":
                        new_speech = action.value
                        if new_speech != self.state.last_speech:
                            self.state.last_speech = new_speech
                            updated = True
                    elif action.type == "emotion":
                        new_emotion = action.value
                        if new_emotion != self.state.current_emotion:
                            self.state.current_emotion = new_emotion
                            updated = True

                self.state_dict = {
                    "current_action": self.state.current_action,
                    "last_speech": self.state.last_speech,
                    "current_emotion": self.state.current_emotion,
                    "system_latency": system_latency,
                    "inputs": input_rezeroed,
                    "wallet_state": self.state.wallet_state,
                }

                logging.info(f"Inputs and LLM Outputs: {self.state_dict}")

            if updated:
                self._last_tick = 0
                self.tick()

        except Exception as e:
            logging.error(f"Error in sim update: {e}")

    async def cleanup(self):
        """Clean up resources"""
        logging.info("Cleaning up WebSim...")
        self._initialized = False

        for connection in self.active_connections[:]:
            try:
                await connection.close()
            except Exception as e:
                logging.error(f"Error closing connection: {e}")
        self.active_connections.clear()
