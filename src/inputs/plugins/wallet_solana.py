import asyncio
import base58
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import List, Optional

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed

from inputs.base import SensorConfig
from inputs.base.loop import FuserInput
from providers.io_provider import IOProvider


@dataclass
class Message:
    timestamp: float
    message: str


class WalletSolana(FuserInput[float]):
    """
    Queries current SOL balance and reports a balance increase
    """

    def __init__(self, config: SensorConfig = SensorConfig()):
        super().__init__(config)

        # Track IO
        self.io_provider = IOProvider()
        self.messages: List[Message] = []

        self.POLL_INTERVAL = 0.5  # seconds between blockchain data updates
        self.keypair: Optional[Keypair] = None
        self.client: Optional[AsyncClient] = None
        self.pubkey: Optional[Pubkey] = None

        # Get private key from environment
        private_key = os.environ.get("SOLANA_PRIVATE_KEY")
        if not private_key:
            logging.error("SOLANA_PRIVATE_KEY environment variable is not set")
            self.SOL_balance = 0.0
            self.SOL_balance_previous = 0.0
            return

        # Get RPC URL (default to Devnet)
        rpc_url = os.environ.get("SOLANA_RPC_URL", "https://api.devnet.solana.com")

        try:
            # Initialize Solana client
            self.client = AsyncClient(rpc_url, commitment=Confirmed)

            # Create keypair from private key
            # Support both base58 string and JSON array formats
            if private_key.startswith("["):
                # JSON array format: [1,2,3,...]
                key_bytes = bytes(json.loads(private_key))
            else:
                # Base58 format
                key_bytes = base58.b58decode(private_key)

            self.keypair = Keypair.from_bytes(key_bytes)
            self.pubkey = self.keypair.pubkey()

            logging.info(f"WalletSolana initialized with address: {self.pubkey}")
            logging.info(f"Connected to network: {rpc_url}")

            # Get initial balance (will be done in first poll since we need async)
            self.SOL_balance = 0.0
            self.SOL_balance_previous = 0.0
            logging.info("Testing: WalletSolana: Initialized")
        except Exception as e:
            logging.error(f"Error initializing Solana wallet: {e}")
            logging.error("Make sure SOLANA_PRIVATE_KEY is set correctly (base58 or JSON array)")
            self.keypair = None
            self.client = None
            self.pubkey = None
            self.SOL_balance = 0.0
            self.SOL_balance_previous = 0.0

    async def _poll(self) -> List[float]:
        """
        Poll for Solana Wallet balance updates.

        Returns
        -------
        List[float]
            [current_balance, balance_change]
        """
        await asyncio.sleep(self.POLL_INTERVAL)

        if not self.keypair or not self.client or not self.pubkey:
            logging.warning("WalletSolana: Wallet not initialized, skipping poll")
            return [self.SOL_balance, 0.0]

        try:
            # Get current balance
            response = await self.client.get_balance(self.pubkey)
            balance_lamports = response.value
            self.SOL_balance = float(balance_lamports) / 1_000_000_000  # Convert lamports to SOL

            logging.info(
                f"WalletSolana: Wallet refreshed: {self.SOL_balance} SOL, previous balance was {self.SOL_balance_previous}"
            )

            balance_change = self.SOL_balance - self.SOL_balance_previous
            self.SOL_balance_previous = self.SOL_balance
        except Exception as e:
            logging.error(f"WalletSolana: Error polling wallet: {e}")
            balance_change = 0.0

        return [self.SOL_balance, balance_change]

    async def _raw_to_text(self, raw_input: List[float]) -> Optional[Message]:
        """
        Convert balance data to human-readable message.

        Parameters
        ----------
        raw_input : List[float]
            [current_balance, balance_change]

        Returns
        -------
        Message
            Timestamped status or transaction notification
        """
        balance_change = raw_input[1]

        message = ""

        if balance_change > 0:
            message = f"{balance_change:.5f}"
            logging.info(f"\n\nWalletSolana balance change: {message}")
        else:
            return None

        logging.debug(f"WalletSolana: {message}")
        return Message(timestamp=time.time(), message=message)

    async def raw_to_text(self, raw_input: List[float]):
        """
        Process balance update and manage message buffer.

        Parameters
        ----------
        raw_input : List[float]
            Raw balance data
        """
        pending_message = await self._raw_to_text(raw_input)

        if pending_message is not None:
            self.messages.append(pending_message)

    def formatted_latest_buffer(self) -> Optional[str]:
        """
        Format and clear the buffer contents. If there are multiple SOL transactions,
        combine them into a single message.

        Returns
        -------
        Optional[str]
            Formatted string of buffer contents or None if buffer is empty
        """
        if len(self.messages) == 0:
            return None

        transaction_sum = 0

        # all the messages, by definition, are non-zero
        for message in self.messages:
            transaction_sum += float(message.message)

        last_message = self.messages[-1]
        result_message = Message(
            timestamp=last_message.timestamp,
            message=f"You just received {transaction_sum:.5f} SOL.",
        )

        result = f"""
{self.__class__.__name__} INPUT
// START
{result_message.message}
// END
"""

        self.io_provider.add_input(
            self.__class__.__name__, result_message.message, result_message.timestamp
        )
        self.messages = []
        return result

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup client"""
        if self.client:
            await self.client.close()
