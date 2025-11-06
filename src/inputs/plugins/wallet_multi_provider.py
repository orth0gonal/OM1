"""
Multi-chain wallet provider supporting EVM and Solana wallets.
Handles connect, sign, and transfer operations for multiple wallet types.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from inputs.base import FuserInput, SensorConfig


@dataclass
class WalletTransaction:
    """Represents a wallet transaction"""

    chain: str  # 'evm' or 'solana'
    from_address: str
    to_address: Optional[str] = None
    amount: Optional[float] = None
    signature: Optional[str] = None
    tx_hash: Optional[str] = None
    timestamp: float = 0.0


class WalletMultiProvider(FuserInput[Dict]):
    """
    Multi-chain wallet provider that handles:
    - EVM wallets (MetaMask, Coinbase Wallet, etc.) via RainbowKit
    - Solana wallets (Phantom, Solflare, etc.) via Solana Wallet Adapter

    Provides connect, sign, and transfer functionality for both chains.
    """

    def __init__(self, config: SensorConfig):
        super().__init__(config)
        self.connected_wallets: Dict[str, Dict] = {
            "evm": {"connected": False, "address": None, "chain_id": None},
            "solana": {"connected": False, "address": None, "cluster": None},
        }
        self.transactions: List[WalletTransaction] = []
        self.pending_operations: List[Dict] = []
        logging.info("WalletMultiProvider initialized")

    async def _poll(self) -> Optional[Dict]:
        """
        Poll for wallet events and pending operations.
        Returns wallet state and recent transactions.
        """
        # Check if there are any new transactions or wallet state changes
        if self.transactions:
            recent_tx = self.transactions[-1]
            return {
                "type": "transaction",
                "chain": recent_tx.chain,
                "from": recent_tx.from_address,
                "to": recent_tx.to_address,
                "amount": recent_tx.amount,
                "tx_hash": recent_tx.tx_hash,
                "timestamp": recent_tx.timestamp,
            }

        # Return current wallet state
        return {
            "type": "wallet_state",
            "evm": self.connected_wallets["evm"],
            "solana": self.connected_wallets["solana"],
        }

    def _raw_to_text(self, wallet_data: Optional[Dict]) -> str:
        """Convert wallet data to human-readable text"""
        if not wallet_data:
            return "No wallet activity"

        if wallet_data.get("type") == "transaction":
            chain = wallet_data.get("chain", "unknown")
            from_addr = wallet_data.get("from", "unknown")[:10]
            to_addr = wallet_data.get("to", "unknown")[:10] if wallet_data.get("to") else "N/A"
            amount = wallet_data.get("amount", 0)
            tx_hash = wallet_data.get("tx_hash", "N/A")[:10]

            return f"{chain.upper()} Transaction: {amount} tokens from {from_addr}... to {to_addr}... (tx: {tx_hash}...)"

        elif wallet_data.get("type") == "wallet_state":
            evm = wallet_data.get("evm", {})
            solana = wallet_data.get("solana", {})

            evm_status = f"EVM: {'Connected' if evm.get('connected') else 'Disconnected'}"
            if evm.get("connected") and evm.get("address"):
                evm_status += f" ({evm['address'][:10]}...)"

            solana_status = f"Solana: {'Connected' if solana.get('connected') else 'Disconnected'}"
            if solana.get("connected") and solana.get("address"):
                solana_status += f" ({solana['address'][:10]}...)"

            return f"Wallet Status - {evm_status}, {solana_status}"

        return "Unknown wallet event"

    def handle_wallet_connect(self, chain: str, address: str, metadata: Dict = None):
        """Handle wallet connection event"""
        metadata = metadata or {}

        if chain == "evm":
            self.connected_wallets["evm"] = {
                "connected": True,
                "address": address,
                "chain_id": metadata.get("chain_id"),
            }
            logging.info(f"EVM wallet connected: {address}")
        elif chain == "solana":
            self.connected_wallets["solana"] = {
                "connected": True,
                "address": address,
                "cluster": metadata.get("cluster", "devnet"),
            }
            logging.info(f"Solana wallet connected: {address}")

    def handle_wallet_disconnect(self, chain: str):
        """Handle wallet disconnection event"""
        if chain in self.connected_wallets:
            self.connected_wallets[chain] = {
                "connected": False,
                "address": None,
            }
            logging.info(f"{chain.upper()} wallet disconnected")

    def handle_transaction(
        self,
        chain: str,
        from_address: str,
        to_address: str = None,
        amount: float = None,
        signature: str = None,
        tx_hash: str = None,
    ):
        """Handle transaction event"""
        import time

        tx = WalletTransaction(
            chain=chain,
            from_address=from_address,
            to_address=to_address,
            amount=amount,
            signature=signature,
            tx_hash=tx_hash,
            timestamp=time.time(),
        )
        self.transactions.append(tx)
        logging.info(f"Transaction recorded: {chain} - {tx_hash}")

    def get_wallet_state(self) -> Dict:
        """Get current wallet connection state"""
        return {
            "evm": self.connected_wallets["evm"],
            "solana": self.connected_wallets["solana"],
            "transaction_count": len(self.transactions),
        }

    def formatted_latest_buffer(self) -> str:
        """Format the latest wallet activity for the LLM"""
        if not self.buffer:
            return "No recent wallet activity"

        latest = self.buffer[-1]
        return self._raw_to_text(latest)
