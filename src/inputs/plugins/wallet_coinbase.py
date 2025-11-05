import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import List, Optional

from eth_account import Account
from web3 import Web3

from inputs.base import SensorConfig
from inputs.base.loop import FuserInput
from providers.io_provider import IOProvider


@dataclass
class Message:
    timestamp: float
    message: str


# TODO(Kyle): Support Cryptos other than ETH
class WalletCoinbase(FuserInput[float]):
    """
    Queries current ETH balance and reports a balance increase
    """

    def __init__(self, config: SensorConfig = SensorConfig()):
        super().__init__(config)

        # Track IO
        self.io_provider = IOProvider()
        self.messages: List[Message] = []

        self.POLL_INTERVAL = 0.5  # seconds between blockchain data updates
        self.account: Optional[Account] = None
        self.w3: Optional[Web3] = None

        # Get private key from environment
        private_key = os.environ.get("ETH_PRIVATE_KEY")
        if not private_key:
            logging.error("ETH_PRIVATE_KEY environment variable is not set")
            self.ETH_balance = 0.0
            self.ETH_balance_previous = 0.0
            return

        # Get RPC URL (default to Base Sepolia testnet)
        rpc_url = os.environ.get("ETH_RPC_URL", "https://sepolia.base.org")

        try:
            # Initialize Web3 connection
            self.w3 = Web3(Web3.HTTPProvider(rpc_url))

            # Create account from private key
            if not private_key.startswith("0x"):
                private_key = "0x" + private_key
            self.account = Account.from_key(private_key)

            logging.info(f"WalletCoinbase initialized with address: {self.account.address}")
            logging.info(f"Connected to network: {rpc_url}")

            # Get initial balance
            balance_wei = self.w3.eth.get_balance(self.account.address)
            self.ETH_balance = float(self.w3.from_wei(balance_wei, 'ether'))
            self.ETH_balance_previous = self.ETH_balance
            logging.info("Testing: WalletCoinbase: Initialized")
        except Exception as e:
            logging.error(f"Error initializing wallet: {e}")
            logging.error("Make sure ETH_PRIVATE_KEY is set correctly")
            self.account = None
            self.w3 = None
            self.ETH_balance = 0.0
            self.ETH_balance_previous = 0.0

    async def _poll(self) -> List[float]:
        """
        Poll for Ethereum Wallet balance updates.

        Returns
        -------
        List[float]
            [current_balance, balance_change]
        """
        await asyncio.sleep(self.POLL_INTERVAL)

        if not self.account or not self.w3:
            logging.warning("WalletCoinbase: Wallet not initialized, skipping poll")
            return [self.ETH_balance, 0.0]

        try:
            # Get current balance
            balance_wei = self.w3.eth.get_balance(self.account.address)
            self.ETH_balance = float(self.w3.from_wei(balance_wei, 'ether'))

            logging.info(
                f"WalletCoinbase: Wallet refreshed: {self.ETH_balance} ETH, previous balance was {self.ETH_balance_previous}"
            )

            balance_change = self.ETH_balance - self.ETH_balance_previous
            self.ETH_balance_previous = self.ETH_balance
        except Exception as e:
            logging.error(f"WalletCoinbase: Error polling wallet: {e}")
            balance_change = 0.0

        return [self.ETH_balance, balance_change]

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
            logging.info(f"\n\nWalletCoinbase balance change: {message}")
        else:
            return None

        logging.debug(f"WalletCoinbase: {message}")
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
        Format and clear the buffer contents. If there are multiple ETH transactions,
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
            message=f"You just received {transaction_sum:.5f} ETH.",
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
