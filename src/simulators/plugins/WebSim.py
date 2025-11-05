import asyncio
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
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
    wallet_action: str = ""
    wallet_status: str = ""
    system_latency: Optional[dict] = None

    def to_dict(self):
        return asdict(self)


class WebSim(Simulator):
    """
    WebSim simulator class for visualizing simulation data in a web interface.
    """

    def __init__(self, config: SimulatorConfig):
        super().__init__(config)
        self.messages: list[str] = []
        self.io_provider = IOProvider()

        # Initialize wallet manager for handling both robot and user wallets
        from actions.wallet.wallet_manager import WalletManager
        self.wallet_manager = WalletManager()

        self._initialized = False
        self._lock = threading.Lock()
        self._last_tick = time.time()
        self._tick_interval = 0.1  # 100ms tick rate

        self.state_dict = {}
        # Initialize state
        self.state = SimulatorState(
            inputs={},
            current_action="idle",
            last_speech="",
            current_emotion="",
            wallet_action="",
            wallet_status="",
            system_latency={
                "fuse_time": 0,
                "llm_start": 0,
                "processing": 0,
                "complete": 0,
            },
        )

        logging.info("Initializing WebSim...")

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
        from fastapi import Request

        @self.app.post("/api/user-wallet/connect")
        async def user_wallet_connect(request: Request):
            """API endpoint to register user wallet connection"""
            try:
                data = await request.json()
                address = data.get("address")
                chain_id = data.get("chainId")
                balance = data.get("balance")

                if not address or not chain_id:
                    return {"status": "error", "message": "Address and chainId required"}

                # Register user wallet in wallet manager
                self.wallet_manager.connect_user_wallet(address, chain_id, balance)

                # Add to IOProvider for robot to see
                wallet_name = data.get("walletName", "Unknown")
                status_message = f"action=connect status=success address={address} chain_id={chain_id} balance={balance} wallet={wallet_name}"
                self.io_provider.add_input("UserWallet", status_message, time.time())

                # Update WebSim state to show user wallet connection immediately
                with self._lock:
                    self.state.wallet_action = f"User connected {wallet_name}"
                    self.state.wallet_status = f"User wallet connected: {address}"

                # Trigger immediate broadcast
                self._last_tick = 0

                logging.info(f"User wallet connected: {address}")
                return {"status": "success", "message": "User wallet connected"}
            except Exception as e:
                logging.error(f"Error connecting user wallet: {e}")
                return {"status": "error", "message": str(e)}

        @self.app.post("/api/user-wallet/disconnect")
        async def user_wallet_disconnect(request: Request):
            """API endpoint to handle user wallet disconnection"""
            try:
                await self.wallet_manager.disconnect_user_wallet()

                # Add to IOProvider for robot to see
                status_message = "action=disconnect status=success"
                self.io_provider.add_input("UserWallet", status_message, time.time())

                # Update WebSim state to show user wallet disconnection
                with self._lock:
                    self.state.wallet_action = "User disconnected wallet"
                    self.state.wallet_status = "User wallet disconnected"

                # Trigger immediate broadcast
                self._last_tick = 0

                logging.info("User wallet disconnected")
                return {"status": "success", "message": "User wallet disconnected"}
            except Exception as e:
                logging.error(f"Error disconnecting user wallet: {e}")
                return {"status": "error", "message": str(e)}

        @self.app.post("/api/user-wallet/submit")
        async def user_wallet_submit(request: Request):
            """API endpoint to receive user wallet actions from browser"""
            try:
                data = await request.json()
                action_type = data.get("action_type")  # "sign" or "transfer"
                from_address = data.get("from_address")

                # Process action through wallet manager
                if action_type == "sign":
                    message = data.get("message")
                    signature = data.get("signature")
                    result = self.wallet_manager.process_user_signature(
                        message, signature, from_address
                    )
                    status_message = f"action=sign status={result['status']}"
                    if result["status"] == "success":
                        status_message += f" message={message} signature={signature[:20]}... from={from_address}"
                    else:
                        status_message += f" reason={result['message']}"

                elif action_type == "transfer":
                    to_address = data.get("to_address")
                    amount = data.get("amount")
                    tx_hash = data.get("tx_hash")
                    result = self.wallet_manager.process_user_transaction(
                        from_address, to_address, amount, tx_hash
                    )
                    status_message = f"action=transfer status={result['status']}"
                    if result["status"] == "success":
                        status_message += f" from={from_address} to={to_address} amount={amount} tx_hash={tx_hash}"
                    else:
                        status_message += f" reason={result['message']}"

                else:
                    return {"status": "error", "message": f"Unknown action type: {action_type}"}

                # Add to IOProvider for robot to see
                self.io_provider.add_input("UserWallet", status_message, time.time())

                # Update WebSim state to show user wallet action immediately
                with self._lock:
                    wallet_type = data.get("wallet_type", "unknown")
                    if action_type == "sign":
                        self.state.wallet_action = f"User signed message ({wallet_type})"
                        self.state.wallet_status = f"User wallet signed: {message[:50]}..."
                    elif action_type == "transfer":
                        self.state.wallet_action = f"User transferred {amount} ({wallet_type})"
                        self.state.wallet_status = f"User wallet transfer: {amount} to {to_address[:10]}...{to_address[-8:]}"

                # Trigger immediate broadcast
                self._last_tick = 0

                logging.info(f"User wallet action processed: {status_message}")
                return {"status": "success", "message": "Action received and processed by robot"}
            except Exception as e:
                logging.error(f"Error processing user wallet action: {e}")
                return {"status": "error", "message": str(e)}

        @self.app.get("/api/robot-wallet/addresses")
        async def get_robot_wallet_addresses():
            """API endpoint to get robot wallet addresses"""
            addresses = {
                "evm": None,
                "solana": None
            }

            # Get EVM address if configured
            eth_private_key = os.environ.get("ETH_PRIVATE_KEY")
            if eth_private_key:
                try:
                    from eth_account import Account
                    if not eth_private_key.startswith("0x"):
                        eth_private_key = "0x" + eth_private_key
                    account = Account.from_key(eth_private_key)
                    addresses["evm"] = account.address
                except Exception as e:
                    logging.error(f"Error getting EVM address: {e}")

            # Get Solana address if configured
            solana_private_key = os.environ.get("SOLANA_PRIVATE_KEY")
            if solana_private_key:
                try:
                    import base58
                    import json
                    from solders.keypair import Keypair

                    # Support both base58 string and JSON array formats
                    if solana_private_key.startswith("["):
                        key_bytes = bytes(json.loads(solana_private_key))
                    else:
                        key_bytes = base58.b58decode(solana_private_key)

                    keypair = Keypair.from_bytes(key_bytes)
                    addresses["solana"] = str(keypair.pubkey())
                except Exception as e:
                    logging.error(f"Error getting Solana address: {e}")

            return addresses

        @self.app.post("/api/wallet/{action}")
        async def wallet_action(action: str, request: Request):
            """API endpoint to trigger wallet actions for testing"""
            from actions.wallet.connector.coinbase import WalletCoinbaseConnector
            from actions.wallet.interface import WalletInput
            from actions.base import ActionConfig

            try:
                # Parse request body
                request_data = {}
                try:
                    request_data = await request.json()
                except Exception:
                    pass

                # Create wallet connector
                wallet_connector = WalletCoinbaseConnector(ActionConfig())

                # Create wallet input based on action
                if action == "poll":
                    wallet_input = WalletInput(action="poll")
                elif action == "sign":
                    message = request_data.get("message", "Test message")
                    wallet_input = WalletInput(action=f"sign:{message}")
                elif action == "transfer":
                    to_address = request_data.get("to_address", "")
                    amount = request_data.get("amount", 0)
                    wallet_input = WalletInput(
                        action=f"transfer:{to_address}:{amount}"
                    )
                else:
                    return {"status": "error", "message": f"Unknown action: {action}"}

                # Execute the action
                await wallet_connector.connect(wallet_input)

                return {"status": "success", "action": action}
            except Exception as e:
                logging.error(f"Error executing wallet action {action}: {e}")
                return {"status": "error", "message": str(e)}

        @self.app.get("/")
        async def get_index():
            return HTMLResponse(
                """
            <!DOCTYPE html>
            <html>
                <head>
                    <title>OpenMind Simulator</title>
                    <script src="https://unpkg.com/react@17/umd/react.development.js"></script>
                    <script src="https://unpkg.com/react-dom@17/umd/react-dom.development.js"></script>
                    <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
                    <script src="https://cdn.jsdelivr.net/npm/ethers@5.7.2/dist/ethers.umd.min.js"></script>
                    <script src="https://unpkg.com/@solana/web3.js@latest/lib/index.iife.min.js"></script>
                    <script type="text/javascript" src="https://unpkg.com/@walletconnect/ethereum-provider@2.11.2/dist/index.umd.js"></script>
                    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
                    <style>
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
                        .message-preview {
                            overflow: hidden;
                            text-overflow: ellipsis;
                            white-space: nowrap;
                            color: #6B7280;
                            font-size: 0.875rem;
                            flex: 1;
                            margin: 0 8px;
                            position: relative;
                            padding-right: 24px;
                        }
                        .message-arrow {
                            color: #6B7280;
                            font-size: 0.875rem;
                            min-width: 20px;
                            text-align: center;
                            transform: rotate(0deg);
                            transition: transform 0.2s;
                        }
                        .message-arrow.expanded {
                            transform: rotate(90deg);
                        }
                        .resize-handle {
                            color: #9CA3AF;
                            font-size: 1rem;
                            cursor: col-resize;
                            padding: 0 4px;
                            position: absolute;
                            right: 0;
                            top: 50%;
                            transform: translateY(-50%);
                        }
                        .message-timestamp {
                            color: #9CA3AF;
                            font-size: 0.75rem;
                            min-width: 60px;
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
                        .footer-logo {
                            height: 60px;
                            width: auto;
                            margin-left: 1rem;
                        }
                        .footer-links {
                            display: flex;
                            gap: 2rem;
                            margin-right: 2rem;
                        }
                        .footer-link {
                            color: #3B82F6;
                            text-decoration: none;
                            font-size: 1rem;
                            font-weight: 500;
                            transition: color 0.2s;
                            display: flex;
                            align-items: center;
                            gap: 0.5rem;
                        }
                        .footer-link:hover {
                            color: #2563EB;
                        }
                        .github-icon {
                            width: 20px;
                            height: 20px;
                        }
                        .message-content {
                            position: relative;
                            margin-top: 0.5rem;
                            background-color: #f9fafb;
                            border-radius: 0.375rem;
                            overflow: hidden;
                        }
                        .message-text {
                            white-space: pre-wrap;
                            word-break: break-word;
                            font-size: 0.875rem;
                            color: #374151;
                            padding: 0.5rem 1rem;
                            overflow-y: auto;
                        }
                        .content-resize-handle {
                            position: absolute;
                            right: 4px;
                            bottom: 4px;
                            width: 12px;
                            height: 12px;
                            cursor: nw-resize;
                            opacity: 0.6;
                            background-image: radial-gradient(circle, #9CA3AF 1.5px, transparent 1.5px);
                            background-size: 4px 4px;
                            transition: opacity 0.2s;
                        }
                        .content-resize-handle:hover {
                            opacity: 1;
                        }
                    </style>
                </head>
                <body class="bg-gray-50">
                    <div id="root"></div>
                    <script type="text/babel">
                        function App() {
                            const [state, setState] = React.useState({
                                inputs: {},
                                current_action: "idle",
                                last_speech: "",
                                current_emotion: "",
                                wallet_action: "",
                                wallet_status: "",
                                system_latency: {
                                    fuse_time: 0,
                                    llm_start: 0,
                                    processing: 0,
                                    complete: 0
                                }
                            });
                            const [error, setError] = React.useState(null);
                            const [connected, setConnected] = React.useState(false);
                            const [expandedMessages, setExpandedMessages] = React.useState({});
                            const [messageHeights, setMessageHeights] = React.useState({});
                            const [isResizing, setIsResizing] = React.useState(null);
                            const resizeRef = React.useRef(null);

                            // Browser wallet state (user wallet) - supporting both EVM and Solana
                            const [userWallet, setUserWallet] = React.useState({
                                connected: false,
                                address: null,
                                chainId: null,
                                balance: null,
                                provider: null,
                                signer: null,
                                walletName: null,
                                walletType: null, // 'evm' or 'solana'
                                instance: null
                            });
                            const [web3Modal, setWeb3Modal] = React.useState(null);
                            const [userSignMessage, setUserSignMessage] = React.useState("Hello from user wallet");
                            const [userTransferAddress, setUserTransferAddress] = React.useState("");
                            const [userTransferAmount, setUserTransferAmount] = React.useState("0.001");
                            const [userWalletLoading, setUserWalletLoading] = React.useState(false);
                            const [userWalletStatus, setUserWalletStatus] = React.useState("");
                            const [robotWalletAddresses, setRobotWalletAddresses] = React.useState({
                                evm: null,
                                solana: null
                            });

                            const startResizing = React.useCallback((messageId, e) => {
                                e.stopPropagation();
                                setIsResizing(messageId);
                                document.body.classList.add('no-select');
                            }, []);

                            const stopResizing = React.useCallback(() => {
                                setIsResizing(null);
                                document.body.classList.remove('no-select');
                            }, []);

                            // Web3Modal is no longer used - using direct wallet connection
                            React.useEffect(() => {
                                // Web3Modal initialization removed
                                setWeb3Modal(true); // Just set to true to indicate ready
                            }, []);

                            // Helper function to get the correct provider for each wallet
                            const getWalletProvider = (walletType) => {
                                console.log(`Getting provider for ${walletType}`);
                                console.log('Available providers:', {
                                    ethereum: !!window.ethereum,
                                    phantom: !!window.phantom,
                                    okxwallet: !!window.okxwallet,
                                    providers: window.ethereum && window.ethereum.providers ? window.ethereum.providers.map(p => ({
                                        isMetaMask: p.isMetaMask,
                                        isCoinbaseWallet: p.isCoinbaseWallet,
                                        isOkxWallet: p.isOkxWallet,
                                        isPhantom: p.isPhantom
                                    })) : []
                                });

                                if (walletType === 'metamask') {
                                    // MetaMask specific provider
                                    if (window.ethereum && window.ethereum.isMetaMask && !window.ethereum.isBraveWallet) {
                                        return window.ethereum;
                                    }
                                    // Try accessing MetaMask directly from providers array
                                    if (window.ethereum && window.ethereum.providers) {
                                        const provider = window.ethereum.providers.find(p => p.isMetaMask && !p.isBraveWallet);
                                        if (provider) return provider;
                                    }
                                    throw new Error('MetaMask not installed');
                                }

                                if (walletType === 'coinbase') {
                                    // Coinbase Wallet specific provider
                                    if (window.ethereum && window.ethereum.isCoinbaseWallet) {
                                        return window.ethereum;
                                    }
                                    if (window.ethereum && window.ethereum.providers) {
                                        const provider = window.ethereum.providers.find(p => p.isCoinbaseWallet);
                                        if (provider) return provider;
                                    }
                                    if (window.coinbaseWalletExtension) {
                                        return window.coinbaseWalletExtension;
                                    }
                                    throw new Error('Coinbase Wallet not installed');
                                }

                                if (walletType === 'okx') {
                                    // OKX Wallet specific provider
                                    if (window.okxwallet) {
                                        return window.okxwallet;
                                    }
                                    if (window.ethereum && window.ethereum.isOkxWallet) {
                                        return window.ethereum;
                                    }
                                    if (window.ethereum && window.ethereum.providers) {
                                        const provider = window.ethereum.providers.find(p => p.isOkxWallet);
                                        if (provider) return provider;
                                    }
                                    throw new Error('OKX Wallet not installed');
                                }

                                if (walletType === 'phantom-evm') {
                                    // Phantom EVM provider - try window.phantom.ethereum first
                                    if (window.phantom && window.phantom.ethereum) {
                                        console.log('Found phantom EVM via window.phantom.ethereum');
                                        return window.phantom.ethereum;
                                    }
                                    // Check if window.ethereum is actually Phantom
                                    if (window.ethereum && window.ethereum.isPhantom) {
                                        console.log('Found phantom EVM via window.ethereum.isPhantom');
                                        return window.ethereum;
                                    }
                                    // Check providers array
                                    if (window.ethereum && window.ethereum.providers) {
                                        const provider = window.ethereum.providers.find(p => p.isPhantom);
                                        if (provider) {
                                            console.log('Found phantom EVM in providers array');
                                            return provider;
                                        }
                                    }
                                    console.error('Phantom EVM not detected. Enable Ethereum in Phantom settings.');
                                    throw new Error('Phantom EVM not enabled. Please enable Ethereum in Phantom settings.');
                                }

                                throw new Error('Wallet not supported');
                            };

                            // Helper function to connect with injected provider (EVM)
                            const connectWithInjected = async (walletType, walletName) => {
                                try {
                                    console.log(`Connecting to ${walletName} (EVM)...`);
                                    const injectedProvider = getWalletProvider(walletType);
                                    console.log('Provider obtained:', injectedProvider);

                                    const provider = new ethers.providers.Web3Provider(injectedProvider);
                                    console.log('Web3Provider created');

                                    await provider.send("eth_requestAccounts", []);
                                    console.log('Accounts requested');

                                    const signer = provider.getSigner();
                                    const address = await signer.getAddress();
                                    console.log('Address obtained:', address);

                                    const network = await provider.getNetwork();
                                    const balance = await provider.getBalance(address);
                                    const balanceEth = ethers.utils.formatEther(balance);

                                    console.log(`${walletName} (EVM) connected successfully`);
                                    return {
                                        provider,
                                        signer,
                                        address,
                                        network,
                                        balanceEth,
                                        walletName,
                                        walletType: 'evm',
                                        instance: injectedProvider
                                    };
                                } catch (error) {
                                    console.error(`Error connecting to ${walletName}:`, error);
                                    throw error;
                                }
                            };

                            // Helper function to connect with Phantom Solana
                            const connectWithPhantomSolana = async () => {
                                try {
                                    console.log('Connecting to Phantom Solana...');

                                    if (!window.phantom || !window.phantom.solana) {
                                        throw new Error('Phantom wallet not installed');
                                    }

                                    const provider = window.phantom.solana;

                                    // Check if already connected
                                    if (provider.isConnected) {
                                        console.log('Already connected to Phantom Solana');
                                    } else {
                                        // Request connection
                                        await provider.connect();
                                        console.log('Connected to Phantom Solana');
                                    }

                                    const publicKey = provider.publicKey.toString();
                                    console.log('Public key:', publicKey);

                                    // Get balance using Solana web3.js
                                    const connection = new solanaWeb3.Connection(
                                        solanaWeb3.clusterApiUrl('devnet'),
                                        'confirmed'
                                    );
                                    const balance = await connection.getBalance(provider.publicKey);
                                    const balanceSol = balance / solanaWeb3.LAMPORTS_PER_SOL;

                                    console.log('Phantom Solana connected successfully');
                                    return {
                                        provider: connection,
                                        signer: provider,
                                        address: publicKey,
                                        network: { chainId: 'devnet', name: 'Solana Devnet' },
                                        balanceEth: balanceSol.toFixed(4), // Using same field for display
                                        walletName: 'Phantom (Solana)',
                                        walletType: 'solana',
                                        instance: provider
                                    };
                                } catch (error) {
                                    console.error('Error connecting to Phantom Solana:', error);
                                    throw error;
                                }
                            };

                            // Helper function to connect with WalletConnect v2
                            const connectWithWalletConnect = async () => {
                                try {
                                    console.log('Initializing WalletConnect...');
                                    // Check if WalletConnect provider is loaded
                                    if (!window.WalletConnectProvider && !window.EthereumProvider) {
                                        console.error('WalletConnect library not found in window object');
                                        throw new Error('WalletConnect library not loaded. Please refresh the page and try again.');
                                    }

                                    const EthereumProvider = window.EthereumProvider || window.WalletConnectProvider;
                                    console.log('WalletConnect EthereumProvider found:', !!EthereumProvider);

                                    console.log('Initializing provider with config...');
                                    const provider = await EthereumProvider.init({
                                        projectId: 'c0aa7252381fca7d3b63792fb8564bc5', // WalletConnect Cloud project ID
                                        chains: [84532], // Base Sepolia
                                        optionalChains: [1],
                                        showQrModal: true,
                                        qrModalOptions: {
                                            themeMode: 'light',
                                            themeVariables: {
                                                '--wcm-z-index': '9999'
                                            }
                                        },
                                        metadata: {
                                            name: 'OM1 WebSim',
                                            description: 'Connect your wallet to OM1 Robot',
                                            url: window.location.origin,
                                            icons: ['https://avatars.githubusercontent.com/u/37784886']
                                        }
                                    });
                                    console.log('Provider initialized');

                                    // Enable session (shows modal with QR code and wallet list)
                                    console.log('Enabling provider (showing modal)...');
                                    await provider.enable();
                                    console.log('Provider enabled');

                                    const ethersProvider = new ethers.providers.Web3Provider(provider);
                                    const signer = ethersProvider.getSigner();
                                    const address = await signer.getAddress();
                                    const network = await ethersProvider.getNetwork();
                                    const balance = await ethersProvider.getBalance(address);
                                    const balanceEth = ethers.utils.formatEther(balance);

                                    console.log('WalletConnect connected successfully');
                                    return {
                                        provider: ethersProvider,
                                        signer,
                                        address,
                                        network,
                                        balanceEth,
                                        walletName: 'WalletConnect',
                                        walletType: 'evm',
                                        instance: provider
                                    };
                                } catch (error) {
                                    console.error('WalletConnect connection error:', error);
                                    // Provide more specific error messages
                                    if (error.message && error.message.includes('User closed modal')) {
                                        throw new Error('Connection cancelled by user');
                                    } else if (error.message && error.message.includes('User rejected')) {
                                        throw new Error('Connection rejected by user');
                                    }
                                    throw error;
                                }
                            };

                            // User browser wallet handlers - with wallet selection
                            const connectUserWallet = async (selectedWallet) => {
                                setUserWalletLoading(true);
                                const walletDisplayName = selectedWallet === 'metamask' ? 'MetaMask' :
                                                         selectedWallet === 'coinbase' ? 'Coinbase Wallet' :
                                                         selectedWallet === 'okx' ? 'OKX Wallet' :
                                                         selectedWallet === 'phantom-evm' ? 'Phantom (EVM)' :
                                                         selectedWallet === 'phantom-solana' ? 'Phantom (Solana)' :
                                                         selectedWallet === 'walletconnect' ? 'WalletConnect' : 'wallet';
                                setUserWalletStatus(`Connecting to ${walletDisplayName}...`);

                                try {
                                    let result;

                                    if (selectedWallet === 'metamask') {
                                        result = await connectWithInjected('metamask', 'MetaMask');
                                    } else if (selectedWallet === 'coinbase') {
                                        result = await connectWithInjected('coinbase', 'Coinbase Wallet');
                                    } else if (selectedWallet === 'okx') {
                                        result = await connectWithInjected('okx', 'OKX Wallet');
                                    } else if (selectedWallet === 'phantom-evm') {
                                        result = await connectWithInjected('phantom-evm', 'Phantom (EVM)');
                                    } else if (selectedWallet === 'phantom-solana') {
                                        result = await connectWithPhantomSolana();
                                    } else if (selectedWallet === 'walletconnect') {
                                        result = await connectWithWalletConnect();
                                    } else {
                                        throw new Error('Please select a wallet');
                                    }

                                    // Notify robot about wallet connection
                                    await fetch('/api/user-wallet/connect', {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify({
                                            address: result.address,
                                            chainId: result.network.chainId,
                                            balance: result.balanceEth,
                                            walletName: result.walletName
                                        })
                                    });

                                    setUserWallet({
                                        connected: true,
                                        address: result.address,
                                        chainId: result.network.chainId,
                                        balance: result.balanceEth,
                                        provider: result.provider,
                                        signer: result.signer,
                                        walletName: result.walletName,
                                        walletType: result.walletType,
                                        instance: result.instance
                                    });

                                    setUserWalletStatus(`✅ Connected via ${result.walletName}: ${result.address.substring(0, 6)}...${result.address.substring(38)}`);
                                } catch (error) {
                                    console.error('Wallet connection error:', error);
                                    if (error.message && (error.message.includes("User closed modal") || error.message.includes("User rejected"))) {
                                        setUserWalletStatus("Connection cancelled");
                                    } else {
                                        setUserWalletStatus(`❌ Error: ${error.message}`);
                                    }
                                } finally {
                                    setUserWalletLoading(false);
                                }
                            };

                            const disconnectUserWallet = async () => {
                                // Disconnect WalletConnect if used
                                if (userWallet.walletName === 'WalletConnect' && userWallet.instance && userWallet.instance.disconnect) {
                                    try {
                                        await userWallet.instance.disconnect();
                                    } catch (e) {
                                        console.log('WalletConnect disconnect error:', e);
                                    }
                                }

                                // Disconnect Phantom Solana if used
                                if (userWallet.walletType === 'solana' && userWallet.instance && userWallet.instance.disconnect) {
                                    try {
                                        await userWallet.instance.disconnect();
                                    } catch (e) {
                                        console.log('Phantom Solana disconnect error:', e);
                                    }
                                }

                                // Notify robot about wallet disconnection
                                await fetch('/api/user-wallet/disconnect', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' }
                                });

                                setUserWallet({
                                    connected: false,
                                    address: null,
                                    chainId: null,
                                    balance: null,
                                    provider: null,
                                    signer: null,
                                    walletName: null,
                                    walletType: null,
                                    instance: null
                                });
                                setUserWalletStatus("Disconnected");
                            };

                            const handleUserSignMessage = async () => {
                                if (!userWallet.connected) {
                                    setUserWalletStatus("❌ Please connect wallet first");
                                    return;
                                }

                                setUserWalletLoading(true);
                                setUserWalletStatus("Signing message...");
                                try {
                                    let signature;

                                    if (userWallet.walletType === 'solana') {
                                        // Solana message signing
                                        const encodedMessage = new TextEncoder().encode(userSignMessage);
                                        const signedMessage = await userWallet.signer.signMessage(encodedMessage, 'utf8');
                                        signature = btoa(String.fromCharCode.apply(null, signedMessage.signature));
                                        console.log('Solana signature:', signature);
                                    } else {
                                        // EVM message signing
                                        signature = await userWallet.signer.signMessage(userSignMessage);
                                        console.log('EVM signature:', signature);
                                    }

                                    // Submit to robot
                                    const response = await fetch('/api/user-wallet/submit', {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify({
                                            action_type: 'sign',
                                            message: userSignMessage,
                                            signature: signature,
                                            from_address: userWallet.address,
                                            wallet_type: userWallet.walletType
                                        })
                                    });

                                    const result = await response.json();
                                    if (result.status === 'success') {
                                        setUserWalletStatus(`✅ Message signed and sent to robot\\nSignature: ${signature.substring(0, 20)}...`);
                                    } else {
                                        setUserWalletStatus(`❌ Error: ${result.message}`);
                                    }
                                } catch (error) {
                                    setUserWalletStatus(`❌ Error: ${error.message}`);
                                } finally {
                                    setUserWalletLoading(false);
                                }
                            };

                            const handleUserTransfer = async () => {
                                if (!userWallet.connected) {
                                    setUserWalletStatus("❌ Please connect wallet first");
                                    return;
                                }

                                if (!userTransferAddress || !userTransferAmount) {
                                    setUserWalletStatus("❌ Please provide address and amount");
                                    return;
                                }

                                setUserWalletLoading(true);
                                setUserWalletStatus("Sending transaction...");
                                try {
                                    let txHash;

                                    if (userWallet.walletType === 'solana') {
                                        // Solana transfer
                                        const transaction = new solanaWeb3.Transaction().add(
                                            solanaWeb3.SystemProgram.transfer({
                                                fromPubkey: userWallet.signer.publicKey,
                                                toPubkey: new solanaWeb3.PublicKey(userTransferAddress),
                                                lamports: parseFloat(userTransferAmount) * solanaWeb3.LAMPORTS_PER_SOL
                                            })
                                        );

                                        const { blockhash } = await userWallet.provider.getRecentBlockhash();
                                        transaction.recentBlockhash = blockhash;
                                        transaction.feePayer = userWallet.signer.publicKey;

                                        const signed = await userWallet.signer.signTransaction(transaction);
                                        const signature = await userWallet.provider.sendRawTransaction(signed.serialize());

                                        setUserWalletStatus(`⏳ Transaction sent: ${signature}\\nWaiting for confirmation...`);

                                        await userWallet.provider.confirmTransaction(signature);
                                        txHash = signature;

                                        console.log('Solana transaction confirmed:', txHash);
                                    } else {
                                        // EVM transfer
                                        const tx = await userWallet.signer.sendTransaction({
                                            to: userTransferAddress,
                                            value: ethers.utils.parseEther(userTransferAmount)
                                        });

                                        setUserWalletStatus(`⏳ Transaction sent: ${tx.hash}\\nWaiting for confirmation...`);

                                        await tx.wait();
                                        txHash = tx.hash;

                                        console.log('EVM transaction confirmed:', txHash);
                                    }

                                    // Submit to robot
                                    const response = await fetch('/api/user-wallet/submit', {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify({
                                            action_type: 'transfer',
                                            from_address: userWallet.address,
                                            to_address: userTransferAddress,
                                            amount: userTransferAmount,
                                            tx_hash: txHash,
                                            wallet_type: userWallet.walletType
                                        })
                                    });

                                    const result = await response.json();
                                    if (result.status === 'success') {
                                        setUserWalletStatus(`✅ Transfer confirmed and sent to robot\\nTx: ${txHash.substring(0, 20)}...`);
                                    } else {
                                        setUserWalletStatus(`❌ Error: ${result.message}`);
                                    }
                                } catch (error) {
                                    setUserWalletStatus(`❌ Error: ${error.message}`);
                                } finally {
                                    setUserWalletLoading(false);
                                }
                            };

                            const handleResize = React.useCallback((e) => {
                                if (isResizing && resizeRef.current) {
                                    const container = resizeRef.current;
                                    const containerRect = container.getBoundingClientRect();
                                    const newHeight = Math.max(100, e.clientY - containerRect.top);
                                    setMessageHeights(prev => ({
                                        ...prev,
                                        [isResizing]: newHeight
                                    }));
                                }
                            }, [isResizing]);

                            React.useEffect(() => {
                                // Fetch robot wallet addresses on component mount
                                fetch('/api/robot-wallet/addresses')
                                    .then(res => res.json())
                                    .then(addresses => {
                                        console.log('Robot wallet addresses:', addresses);
                                        setRobotWalletAddresses(addresses);
                                    })
                                    .catch(err => console.error('Error fetching robot wallet addresses:', err));

                                const ws = new WebSocket(`ws://${window.location.host}/ws`);

                                ws.onopen = () => {
                                    console.log('Connected to WebSocket');
                                    setConnected(true);
                                };

                                ws.onmessage = (event) => {
                                    const data = JSON.parse(event.data);
                                    setState(data);
                                };

                                ws.onerror = (error) => {
                                    console.error('WebSocket error:', error);
                                    setError('Failed to connect to server');
                                };

                                ws.onclose = () => {
                                    setConnected(false);
                                    setError('Connection lost. Reconnecting...');
                                    setTimeout(() => window.location.reload(), 2000);
                                };

                                return () => ws.close();
                            }, []);

                            React.useEffect(() => {
                                if (isResizing) {
                                    window.addEventListener('mousemove', handleResize);
                                    window.addEventListener('mouseup', stopResizing);
                                    return () => {
                                        window.removeEventListener('mousemove', handleResize);
                                        window.removeEventListener('mouseup', stopResizing);
                                    };
                                }
                            }, [isResizing, handleResize, stopResizing]);

                            const groupedMessages = React.useMemo(() => {
                                const groups = {};
                                Object.entries(state.inputs || {}).forEach(([key, value]) => {
                                    const inputType = value.input_type || 'Unknown';
                                    if (!groups[inputType]) {
                                        groups[inputType] = [];
                                    }
                                    groups[inputType].push({ id: key, ...value });
                                });
                                return groups;
                            }, [state.inputs]);

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
                                <div className="min-h-screen p-4 pb-16">
                                    <div className="container mx-auto">
                                        <div className="flex">
                                            {/* Input History */}
                                            <div className="bg-white rounded-lg shadow p-4" style={{ width: '33%' }}>
                                                <div className="flex flex-col">
                                                    <h2 className="text-xl font-bold mb-4">Input History</h2>
                                                    <div className="space-y-2">
                                                        {Object.entries(groupedMessages)
                                                            .sort(([a], [b]) => a.localeCompare(b))
                                                            .map(([inputType, messages]) => (
                                                                <div key={inputType}>
                                                                    <h3 className="text-sm font-semibold text-gray-700 mb-2">
                                                                        {inputType}
                                                                    </h3>
                                                                    {messages
                                                                        .sort((a, b) => b.timestamp - a.timestamp)
                                                                        .map((message) => (
                                                                            <div key={message.id} className="mb-2">
                                                                                <div
                                                                                    className="message-header"
                                                                                    onClick={() => setExpandedMessages(prev => ({
                                                                                        ...prev,
                                                                                        [message.id]: !prev[message.id]
                                                                                    }))}
                                                                                >
                                                                                    <span className={`message-arrow ${expandedMessages[message.id] ? 'expanded' : ''}`}>
                                                                                        ▶
                                                                                    </span>
                                                                                    <span className="message-timestamp">
                                                                                        {message.timestamp.toFixed(3)}s
                                                                                    </span>
                                                                                    <span className="message-preview">
                                                                                        {message.input.substring(0, 50)}
                                                                                        {message.input.length > 50 ? '...' : ''}
                                                                                    </span>
                                                                                </div>
                                                                                {expandedMessages[message.id] && (
                                                                                    <div
                                                                                        className="message-content"
                                                                                        ref={isResizing === message.id ? resizeRef : null}
                                                                                        style={{ height: messageHeights[message.id] || 'auto', minHeight: '100px' }}
                                                                                    >
                                                                                        <div className="message-text">
                                                                                            {message.input}
                                                                                        </div>
                                                                                        <div
                                                                                            className="content-resize-handle"
                                                                                            onMouseDown={(e) => startResizing(message.id, e)}
                                                                                        />
                                                                                    </div>
                                                                                )}
                                                                            </div>
                                                                        ))}
                                                                </div>
                                                            ))}
                                                    </div>
                                                </div>
                                            </div>

                                            {/* Main Display */}
                                            <div className="flex-1 ml-4">
                                                <div className="bg-white rounded-lg shadow p-4 mb-4">
                                                    <h2 className="text-xl font-bold mb-4">Current State</h2>
                                                    <div className="space-y-4">
                                                        <div>
                                                            <span className="font-semibold">Action:</span>
                                                            <span className="ml-2 text-blue-600">{state.current_action}</span>
                                                        </div>
                                                        <div>
                                                            <span className="font-semibold">Last Speech:</span>
                                                            <div className="mt-1 p-2 bg-gray-50 rounded">
                                                                {state.last_speech || "No speech yet"}
                                                            </div>
                                                        </div>
                                                        <div>
                                                            <span className="font-semibold">Emotion:</span>
                                                            <span className="ml-2 text-purple-600">{state.current_emotion}</span>
                                                        </div>
                                                        <div>
                                                            <span className="font-semibold">Wallet Action:</span>
                                                            <span className="ml-2 text-green-600">{state.wallet_action || "None"}</span>
                                                        </div>
                                                        <div>
                                                            <span className="font-semibold">Wallet Status:</span>
                                                            <div className="mt-1 p-2 bg-gray-50 rounded">
                                                                {state.wallet_status || "No wallet activity"}
                                                            </div>
                                                        </div>
                                                    </div>
                                                </div>

                                                <div className="bg-white rounded-lg shadow p-4 mb-4">
                                                    <h2 className="text-xl font-bold mb-4">System Latency</h2>
                                                    <div className="space-y-2">
                                                        {Object.entries(state.system_latency || {}).map(([key, value]) => (
                                                            <div key={key} className="flex justify-between items-center">
                                                                <span className="font-semibold">{key}:</span>
                                                                <span className="text-gray-600">
                                                                    {value ? value.toFixed(3) : '0.000'}s
                                                                </span>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>

                                                {/* Robot Wallet Info */}
                                                <div className="bg-white rounded-lg shadow p-4 mb-4">
                                                    <h2 className="text-xl font-bold mb-4">🤖 Robot Wallet Addresses</h2>
                                                    <div className="space-y-3">
                                                        <div className="p-3 bg-blue-50 border border-blue-200 rounded">
                                                            <p className="font-semibold text-blue-800 mb-1">⛓️ EVM Address (Base Sepolia)</p>
                                                            <p className="text-xs font-mono text-blue-900 break-all">
                                                                {robotWalletAddresses.evm || 'Not configured (set ETH_PRIVATE_KEY)'}
                                                            </p>
                                                        </div>
                                                        <div className="p-3 bg-purple-50 border border-purple-200 rounded">
                                                            <p className="font-semibold text-purple-800 mb-1">☀️ Solana Address (Devnet)</p>
                                                            <p className="text-xs font-mono text-purple-900 break-all">
                                                                {robotWalletAddresses.solana || 'Not configured (set SOLANA_PRIVATE_KEY)'}
                                                            </p>
                                                        </div>
                                                        <div className="text-xs text-gray-600 mt-2">
                                                            <p>💡 Send funds to these addresses to test incoming transfer detection</p>
                                                            <p>⚡ Robot polls balance every 0.5 seconds and notifies on incoming transfers</p>
                                                        </div>
                                                    </div>
                                                </div>

                                                <div className="bg-white rounded-lg shadow p-4 mb-4">
                                                    <h2 className="text-xl font-bold mb-4">👤 User Wallet (Browser)</h2>
                                                    <div className="mb-3 p-3 bg-gradient-to-r from-purple-50 to-blue-50 border border-purple-200 rounded text-sm">
                                                        <p className="font-semibold text-purple-800 mb-1">🔗 Universal Wallet Connection</p>
                                                        <p className="text-purple-700">
                                                            <strong>Supported wallets:</strong> MetaMask, Coinbase Wallet, OKX Wallet, Phantom, Trust Wallet, Rainbow, and 300+ more via WalletConnect.
                                                        </p>
                                                        <p className="text-purple-600 text-xs mt-1">
                                                            All wallet actions are signed securely in your browser and transmitted to the robot.
                                                        </p>
                                                    </div>
                                                    <div className="space-y-4">
                                                        {/* Wallet Connection */}
                                                        <div className="border-b pb-4">
                                                            <h3 className="font-semibold mb-2">Wallet Connection</h3>
                                                            {!userWallet.connected ? (
                                                                <div className="space-y-2">
                                                                    <button
                                                                        onClick={() => connectUserWallet('metamask')}
                                                                        disabled={userWalletLoading}
                                                                        className="w-full bg-orange-500 hover:bg-orange-600 text-white px-4 py-2 rounded disabled:opacity-50"
                                                                    >
                                                                        {userWalletLoading ? 'Connecting...' : '🦊 MetaMask'}
                                                                    </button>
                                                                    <button
                                                                        onClick={() => connectUserWallet('coinbase')}
                                                                        disabled={userWalletLoading}
                                                                        className="w-full bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded disabled:opacity-50"
                                                                    >
                                                                        {userWalletLoading ? 'Connecting...' : '🔵 Coinbase Wallet'}
                                                                    </button>
                                                                    <button
                                                                        onClick={() => connectUserWallet('okx')}
                                                                        disabled={userWalletLoading}
                                                                        className="w-full bg-black hover:bg-gray-800 text-white px-4 py-2 rounded disabled:opacity-50"
                                                                    >
                                                                        {userWalletLoading ? 'Connecting...' : 'OKX Wallet'}
                                                                    </button>
                                                                    <button
                                                                        onClick={() => connectUserWallet('phantom-solana')}
                                                                        disabled={userWalletLoading}
                                                                        className="w-full bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded disabled:opacity-50"
                                                                    >
                                                                        {userWalletLoading ? 'Connecting...' : '👻 Phantom (Solana)'}
                                                                    </button>
                                                                    <button
                                                                        onClick={() => connectUserWallet('phantom-evm')}
                                                                        disabled={userWalletLoading}
                                                                        className="w-full bg-purple-500 hover:bg-purple-600 text-white px-4 py-2 rounded disabled:opacity-50"
                                                                    >
                                                                        {userWalletLoading ? 'Connecting...' : '👻 Phantom (EVM)'}
                                                                    </button>
                                                                    <button
                                                                        onClick={() => connectUserWallet('walletconnect')}
                                                                        disabled={userWalletLoading}
                                                                        className="w-full bg-gradient-to-r from-blue-500 to-purple-500 hover:from-blue-600 hover:to-purple-600 text-white px-4 py-2 rounded disabled:opacity-50"
                                                                    >
                                                                        {userWalletLoading ? 'Connecting...' : '🔗 WalletConnect (300+ Wallets)'}
                                                                    </button>
                                                                </div>
                                                            ) : (
                                                                <div>
                                                                    <div className="mb-2 p-3 bg-green-50 border border-green-200 rounded text-sm">
                                                                        <p><strong>Wallet:</strong> {userWallet.walletName}</p>
                                                                        <p><strong>Type:</strong> {userWallet.walletType === 'solana' ? '☀️ Solana' : '⛓️ EVM'}</p>
                                                                        <p><strong>Address:</strong> {userWallet.address}</p>
                                                                        <p><strong>Chain:</strong> {userWallet.walletType === 'solana' ? 'Solana Devnet' : `Chain ID ${userWallet.chainId}`}</p>
                                                                        <p><strong>Balance:</strong> {parseFloat(userWallet.balance).toFixed(4)} {userWallet.walletType === 'solana' ? 'SOL' : 'ETH'}</p>
                                                                    </div>
                                                                    <button
                                                                        onClick={disconnectUserWallet}
                                                                        className="bg-gray-500 hover:bg-gray-600 text-white px-4 py-2 rounded text-sm"
                                                                    >
                                                                        Disconnect
                                                                    </button>
                                                                </div>
                                                            )}
                                                        </div>

                                                        {/* Sign Message */}
                                                        <div className="border-b pb-4">
                                                            <h3 className="font-semibold mb-2">Sign Message</h3>
                                                            <input
                                                                type="text"
                                                                value={userSignMessage}
                                                                onChange={(e) => setUserSignMessage(e.target.value)}
                                                                placeholder="Message to sign"
                                                                disabled={!userWallet.connected}
                                                                className="w-full border rounded px-3 py-2 mb-2 disabled:bg-gray-100"
                                                            />
                                                            <button
                                                                onClick={handleUserSignMessage}
                                                                disabled={userWalletLoading || !userWallet.connected}
                                                                className="bg-green-500 hover:bg-green-600 text-white px-4 py-2 rounded disabled:opacity-50"
                                                            >
                                                                {userWalletLoading ? 'Signing...' : '✍️ Sign Message'}
                                                            </button>
                                                        </div>

                                                        {/* Transfer Assets */}
                                                        <div className="pb-4">
                                                            <h3 className="font-semibold mb-2">Transfer Assets</h3>
                                                            <input
                                                                type="text"
                                                                value={userTransferAddress}
                                                                onChange={(e) => setUserTransferAddress(e.target.value)}
                                                                placeholder="Destination address"
                                                                disabled={!userWallet.connected}
                                                                className="w-full border rounded px-3 py-2 mb-2 disabled:bg-gray-100"
                                                            />
                                                            <input
                                                                type="number"
                                                                step="0.001"
                                                                value={userTransferAmount}
                                                                onChange={(e) => setUserTransferAmount(e.target.value)}
                                                                placeholder="Amount (ETH)"
                                                                disabled={!userWallet.connected}
                                                                className="w-full border rounded px-3 py-2 mb-2 disabled:bg-gray-100"
                                                            />
                                                            <button
                                                                onClick={handleUserTransfer}
                                                                disabled={userWalletLoading || !userWallet.connected || !userTransferAddress}
                                                                className="bg-blue-500 hover:bg-blue-600 text-white px-4 py-2 rounded disabled:opacity-50"
                                                            >
                                                                {userWalletLoading ? 'Sending...' : '💸 Send Transaction'}
                                                            </button>
                                                        </div>

                                                        {/* User Wallet Status */}
                                                        {userWalletStatus && (
                                                            <div className="mt-4 p-3 bg-gray-100 rounded">
                                                                <pre className="text-sm whitespace-pre-wrap">{userWalletStatus}</pre>
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>

                                            </div>
                                        </div>
                                    </div>
                                    <div className="footer">
                                        <img
                                            src="/assets/OM_Logo_b_transparent.png"
                                            alt="OpenMind Logo"
                                            className="footer-logo"
                                        />
                                        <div className="footer-links">
                                            <a
                                                href="https://github.com/OpenmindAGI/OM1"
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="footer-link"
                                            >
                                                <svg className="github-icon" viewBox="0 0 24 24" fill="currentColor">
                                                    <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                                                </svg>
                                                GitHub
                                            </a>
                                            <a
                                                href="https://docs.openmind.org/introduction"
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="footer-link"
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
            )

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self.active_connections.append(websocket)
            try:
                await websocket.send_json(self.state.to_dict())
                while True:
                    await websocket.receive_text()
            except Exception as e:
                logging.error(f"WebSocket error: {e}")
            finally:
                self.active_connections.remove(websocket)

        # Start server thread
        try:
            logging.info("Starting WebSim server thread...")
            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()
            time.sleep(1)

            if self.server_thread.is_alive():
                # Using ANSI color codes for cyan text and bold
                logging.info(
                    "\033[1;36mWebSim server started successfully - Open http://localhost:8000 in your browser\033[0m"
                )
                self._initialized = True
            else:
                logging.error("WebSim server failed to start")
        except Exception as e:
            logging.error(f"Error starting WebSim server thread: {e}")

    def _run_server(self):
        """Run the FastAPI server"""
        config = uvicorn.Config(
            app=self.app,
            host="0.0.0.0",  # Still bind to all interfaces
            port=8000,
            log_level="error",
            server_header=False,
            # Override the default startup message
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

            # Broadcast to all clients
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
            logging.debug(f"GET {input_info}")
            if input_type == "GovernanceEthereum":
                continue
            if input_type == "Universal Laws":
                continue
            if input_info.timestamp is not None:
                if input_info.timestamp < earliest_time:
                    earliest_time = float(input_info.timestamp)
        return earliest_time if earliest_time != float("inf") else 0.0

    def tick(self) -> None:
        """Update simulator state"""
        if self._initialized:
            try:
                # Get or create event loop
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
                logging.debug(f"earliest_time: {earliest_time}")

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
                    elif action.type == "wallet":
                        new_wallet_action = action.value
                        if new_wallet_action != self.state.wallet_action:
                            self.state.wallet_action = new_wallet_action
                            updated = True

                # Check for WalletStatus input to update wallet status display
                wallet_status_input = self.io_provider.inputs.get("WalletStatus")
                if wallet_status_input:
                    new_wallet_status = wallet_status_input.input
                    if new_wallet_status != self.state.wallet_status:
                        self.state.wallet_status = new_wallet_status
                        updated = True

                self.state_dict = {
                    "current_action": self.state.current_action,
                    "last_speech": self.state.last_speech,
                    "current_emotion": self.state.current_emotion,
                    "wallet_action": self.state.wallet_action,
                    "wallet_status": self.state.wallet_status,
                    "system_latency": system_latency,
                    "inputs": input_rezeroed,
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
