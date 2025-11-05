"""Coinbase wallet provider for robot-owned wallets."""
import asyncio
import logging
import os
from typing import Optional

from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

from .base import WalletInfo, WalletProvider


class CoinbaseProvider(WalletProvider):
    """
    Coinbase wallet provider using private key.
    This is used for robot-owned wallets, not user wallets.
    """

    def __init__(self, rpc_url: Optional[str] = None):
        """
        Initialize Coinbase provider.

        Parameters
        ----------
        rpc_url : Optional[str]
            RPC endpoint URL. Defaults to Base Sepolia testnet.
        """
        self.account: Optional[Account] = None
        self.w3: Optional[Web3] = None
        self.rpc_url = rpc_url or os.environ.get("ETH_RPC_URL", "https://sepolia.base.org")

    async def connect(self) -> WalletInfo:
        """Connect to wallet using ETH_PRIVATE_KEY environment variable."""
        private_key = os.environ.get("ETH_PRIVATE_KEY")
        if not private_key:
            raise ValueError("ETH_PRIVATE_KEY environment variable is not set")

        try:
            # Initialize Web3 connection
            self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))

            # Create account from private key
            if not private_key.startswith("0x"):
                private_key = "0x" + private_key
            self.account = Account.from_key(private_key)

            # Get balance
            balance_wei = self.w3.eth.get_balance(self.account.address)
            balance = float(self.w3.from_wei(balance_wei, 'ether'))

            chain_id = self.w3.eth.chain_id

            logging.info(f"Coinbase Provider connected: {self.account.address}")
            logging.info(f"Network: {self.rpc_url}, Chain ID: {chain_id}")

            return WalletInfo(
                address=self.account.address,
                chain_id=chain_id,
                balance=balance,
                provider_name="coinbase"
            )
        except Exception as e:
            logging.error(f"Error connecting to Coinbase wallet: {e}")
            raise

    async def get_balance(self, address: str) -> float:
        """Get wallet balance."""
        if not self.w3:
            raise RuntimeError("Wallet not connected")

        loop = asyncio.get_running_loop()
        balance_wei = await loop.run_in_executor(
            None, self.w3.eth.get_balance, address
        )
        return float(self.w3.from_wei(balance_wei, 'ether'))

    async def sign_message(self, message: str) -> str:
        """Sign a message with the robot's wallet."""
        if not self.account:
            raise RuntimeError("Wallet not connected")

        loop = asyncio.get_running_loop()
        encoded_message = encode_defunct(text=message)
        signed_message = await loop.run_in_executor(
            None, self.account.sign_message, encoded_message
        )
        return signed_message.signature.hex()

    async def send_transaction(
        self, to_address: str, amount: float, data: Optional[str] = None
    ) -> str:
        """Send a transaction from the robot's wallet."""
        if not self.account or not self.w3:
            raise RuntimeError("Wallet not connected")

        loop = asyncio.get_running_loop()

        def _build_and_send_tx():
            nonce = self.w3.eth.get_transaction_count(self.account.address)
            gas_price = self.w3.eth.gas_price
            value_wei = self.w3.to_wei(amount, 'ether')

            transaction = {
                'nonce': nonce,
                'to': self.w3.to_checksum_address(to_address),
                'value': value_wei,
                'gas': 21000,
                'gasPrice': gas_price,
                'chainId': self.w3.eth.chain_id,
            }

            if data:
                transaction['data'] = data

            signed_txn = self.account.sign_transaction(transaction)
            tx_hash = self.w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            tx_receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            return tx_hash.hex(), tx_receipt

        tx_hash, tx_receipt = await loop.run_in_executor(None, _build_and_send_tx)
        logging.info(f"Transaction sent: {tx_hash}, Status: {tx_receipt['status']}")
        return tx_hash

    async def disconnect(self) -> None:
        """Disconnect from wallet."""
        self.account = None
        self.w3 = None
        logging.info("Coinbase Provider disconnected")
